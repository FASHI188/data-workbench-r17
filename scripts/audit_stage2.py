#!/usr/bin/env python3
"""Fail-closed Stage 2B hard-gate audit."""
from __future__ import annotations

import csv
import json
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
    if not manifest_path.exists():
        return False, ["missing data/current_master/manifest.json"]
    if not combined_path.exists():
        return False, ["missing data/current_master/cn_main_a.csv"]

    manifest = load_json(manifest_path)
    if manifest.get("hard_gate_status") != "PASS_CANDIDATE":
        errors.append("current-master manifest is not PASS_CANDIDATE")

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


def main() -> int:
    cfg = load_json(CONFIG)
    results = {}
    g1_ok, g1_errors = audit_g1()
    results["G1"] = {"pass": g1_ok, "errors": g1_errors}

    # G2-G5 remain fail-closed until their dedicated evidence chains exist.
    for gate in cfg["hard_gates"]:
        gid = gate["id"]
        if gid != "G1":
            results[gid] = {"pass": False, "errors": [f"{gid} evidence chain not implemented yet"]}

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
