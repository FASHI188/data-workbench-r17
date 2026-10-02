#!/usr/bin/env python3
"""Fail-closed audit for a forward current-master candidate.

Unlike the frozen Stage2 audit, this checks the freshly fetched current master against its
same-run independent exchange reconciliation. It does not declare Stage2 or Stage4 ready.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER_DIR = ROOT / "data/current_master"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    errors: list[str] = []
    manifest_path = MASTER_DIR / "manifest.json"
    recon_path = MASTER_DIR / "reconciliation.json"
    combined_path = MASTER_DIR / "cn_main_a.csv"
    for p in (manifest_path, recon_path, combined_path):
        if not p.exists():
            errors.append(f"missing {p.relative_to(ROOT)}")
    if errors:
        print(json.dumps({"gate": "FORWARD_G1", "pass": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recon = json.loads(recon_path.read_text(encoding="utf-8"))
    master = rows(combined_path)
    if manifest.get("hard_gate_status") != "PASS_CANDIDATE":
        errors.append("manifest hard_gate_status is not PASS_CANDIDATE")
    if recon.get("g1_reconciled") is not True or recon.get("status") != "RECONCILED":
        errors.append("independent exchange reconciliation is not RECONCILED")
    if not master:
        errors.append("combined current master is empty")

    counts = {"SSE": 0, "SZSE": 0}
    keys: set[tuple[str, str]] = set()
    for r in master:
        ex, code = r.get("exchange", ""), r.get("code", "")
        if ex not in counts:
            errors.append(f"bad exchange {ex!r}")
            continue
        key = (ex, code)
        if key in keys:
            errors.append(f"duplicate identity {ex}:{code}")
        keys.add(key)
        counts[ex] += 1
    if counts["SSE"] != int((manifest.get("sse") or {}).get("rows") or -1):
        errors.append("SSE row count does not match manifest")
    if counts["SZSE"] != int((manifest.get("szse") or {}).get("rows") or -1):
        errors.append("SZSE row count does not match manifest")

    as_of_raw = str((manifest.get("szse") or {}).get("as_of") or "")
    try:
        as_of = date.fromisoformat(as_of_raw)
    except Exception:
        errors.append(f"invalid master as_of={as_of_raw!r}")
        as_of = None
    fetched_raw = str(manifest.get("fetched_at_utc") or "")
    try:
        fetched = datetime.fromisoformat(fetched_raw.replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            raise ValueError("timezone missing")
        if fetched > datetime.now(timezone.utc):
            errors.append("fetched_at_utc is in the future")
    except Exception:
        errors.append(f"invalid fetched_at_utc={fetched_raw!r}")

    report = {
        "gate": "FORWARD_G1",
        "pass": not errors,
        "master_as_of": as_of.isoformat() if as_of else None,
        "rows": len(master),
        "sse_rows": counts["SSE"],
        "szse_rows": counts["SZSE"],
        "reconciled": recon.get("g1_reconciled"),
        "errors": errors,
        "authoritative": False,
        "purpose": "forward freshness evidence; does not mutate frozen Stage2/Stage3 or unlock Stage4",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
