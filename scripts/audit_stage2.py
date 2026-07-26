#!/usr/bin/env python3
"""Fail-closed Stage 2B hard-gate audit."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "stage2_hard_gates.json"
MASTER_DIR = ROOT / "data" / "current_master"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit_g1() -> tuple[bool, list[str]]:
    errors: list[str] = []
    manifest_path = MASTER_DIR / "manifest.json"
    combined_path = MASTER_DIR / "cn_main_a.csv"
    reconciliation_path = MASTER_DIR / "reconciliation.json"
    if not manifest_path.exists():
        return False, ["missing data/current_master/manifest.json"]
    if not combined_path.exists():
        return False, ["missing data/current_master/cn_main_a.csv"]
    if not reconciliation_path.exists():
        return False, ["missing independent data/current_master/reconciliation.json"]

    manifest = load_json(manifest_path)
    if manifest.get("hard_gate_status") != "PASS_CANDIDATE":
        errors.append("current-master manifest is not PASS_CANDIDATE")

    reconciliation = load_json(reconciliation_path)
    if reconciliation.get("status") != "RECONCILED" or reconciliation.get("g1_reconciled") is not True:
        errors.append("independent exchange-owned master reconciliation did not pass")
    for exchange_key in ("sse", "szse"):
        section = reconciliation.get(exchange_key, {})
        if section.get("set_equal") is not True:
            errors.append(f"{exchange_key.upper()} primary/control code sets differ")
        if section.get("primary_count") != section.get("control_count"):
            errors.append(f"{exchange_key.upper()} primary/control counts differ")
        if not section.get("control_sha256"):
            errors.append(f"{exchange_key.upper()} control SHA-256 missing")

    rows = list(csv.DictReader(combined_path.open(encoding="utf-8")))
    if not rows:
        errors.append("current master has zero rows")
        return False, errors

    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.get("exchange", ""), row.get("code", ""))
        if key in seen:
            errors.append(f"duplicate security: {key[0]}:{key[1]}")
        seen.add(key)
        if row.get("exchange") not in {"SSE", "SZSE"}:
            errors.append(f"invalid exchange: {row.get('exchange')}")
        if row.get("board") != "MAIN" or row.get("security_type") != "A_SHARE":
            errors.append(f"out-of-scope row: {key[0]}:{key[1]}")
        if row.get("exchange") == "SSE" and row.get("code", "").startswith(("688", "689")):
            errors.append(f"STAR contamination: {row.get('code')}")
        if row.get("exchange") == "SZSE" and row.get("code", "").startswith(("300", "301")):
            errors.append(f"ChiNext contamination: {row.get('code')}")
        if row.get("board_basis") == "DERIVED_CODE_PREFIX":
            errors.append(f"weak SZSE board evidence: {row.get('code')}")

    sse_rows = sum(r.get("exchange") == "SSE" for r in rows)
    szse_rows = sum(r.get("exchange") == "SZSE" for r in rows)
    if sse_rows < 1500:
        errors.append(f"implausibly small SSE main-A universe: {sse_rows}")
    if szse_rows < 1400:
        errors.append(f"implausibly small SZSE main-A universe: {szse_rows}")

    return not errors, errors


def audit_g2() -> tuple[bool, list[str], dict]:
    """Re-run the dedicated G2 audit instead of trusting a stale saved result."""
    script = ROOT / "scripts" / "audit_security_history.py"
    if not script.exists():
        return False, ["missing scripts/audit_security_history.py"], {}
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False, [f"G2 audit produced invalid JSON; stderr={proc.stderr.strip()[:1000]}"], {}

    errors = list(report.get("errors") or [])
    if proc.returncode != 0 and not errors:
        errors.append(f"G2 audit exited {proc.returncode}: {proc.stderr.strip()[:1000]}")
    ok = proc.returncode == 0 and report.get("pass") is True and not errors
    return ok, errors, report


def main() -> int:
    cfg = load_json(CONFIG)
    results: dict[str, dict] = {}

    g1_ok, g1_errors = audit_g1()
    results["G1"] = {"pass": g1_ok, "errors": g1_errors}

    g2_ok, g2_errors, g2_report = audit_g2()
    results["G2"] = {"pass": g2_ok, "errors": g2_errors, "details": g2_report}

    # G3-G5 remain fail-closed until their dedicated evidence chains exist and pass.
    for gate in cfg["hard_gates"]:
        gid = gate["id"]
        if gid not in {"G1", "G2"}:
            results[gid] = {"pass": False, "errors": [f"{gid} evidence chain not implemented or not passed yet"]}

    all_pass = all(v["pass"] for v in results.values())
    report = {
        "stage": "2B",
        "all_hard_gates_pass": all_pass,
        "alpha_training_allowed": all_pass,
        "results": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all_pass else 2


if __name__ == "__main__":
    sys.exit(main())
