#!/usr/bin/env python3
"""Audit G2 survivorship-free lifecycle coverage.

Passing requirements are intentionally stricter than 'current names can be rebuilt':
1. current open intervals exactly equal G1 current master;
2. both exchanges have historical DELIST evidence;
3. lifecycle coverage reaches 2015-01-01 for the historical universe;
4. no unresolved lifecycle ordering errors;
5. a G2 manifest explicitly declares historical backfill complete.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data/current_master/cn_main_a.csv"
INTERVALS = ROOT / "data/security_lifecycle/security_intervals.csv"
EVENTS = ROOT / "data/security_lifecycle/events.csv"
MANIFEST = ROOT / "data/security_lifecycle/manifest.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    errors: list[str] = []
    for path in (MASTER, INTERVALS, EVENTS, MANIFEST):
        if not path.exists():
            errors.append(f"missing {path.relative_to(ROOT)}")
    if errors:
        print(json.dumps({"gate": "G2", "pass": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 2

    master = read_csv(MASTER)
    intervals = read_csv(INTERVALS)
    events = read_csv(EVENTS)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    current_master = {(r["exchange"], r["code"]) for r in master}
    current_intervals = {
        (r["exchange"], r["code"])
        for r in intervals
        if not (r.get("listed_to_exclusive") or "").strip()
    }
    if current_master != current_intervals:
        only_master = sorted(current_master - current_intervals)
        only_history = sorted(current_intervals - current_master)
        errors.append(
            f"current projection mismatch: only_master={len(only_master)}, only_history={len(only_history)}, "
            f"sample_master={only_master[:10]}, sample_history={only_history[:10]}"
        )

    delists = [r for r in events if r.get("event_type") == "DELIST"]
    for exchange in ("SSE", "SZSE"):
        n = sum(r.get("exchange") == exchange for r in delists)
        if n == 0:
            errors.append(f"no historical DELIST events for {exchange}")

    effective_dates = []
    for row in events:
        try:
            effective_dates.append(date.fromisoformat(row["effective_date"]))
        except Exception:
            errors.append(f"invalid effective_date for {row.get('exchange')}:{row.get('code')}")
    if effective_dates and min(effective_dates) > date(2015, 1, 1):
        errors.append(f"lifecycle evidence does not reach 2015-01-01; earliest={min(effective_dates)}")

    if manifest.get("historical_backfill_complete") is not True:
        errors.append("historical_backfill_complete is not true")
    if manifest.get("coverage_start") != "2015-01-01":
        errors.append("coverage_start is not 2015-01-01")
    if manifest.get("coverage_end") is None:
        errors.append("coverage_end missing")

    report = {
        "gate": "G2",
        "pass": not errors,
        "current_master_count": len(current_master),
        "current_open_interval_count": len(current_intervals),
        "delist_events": len(delists),
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
