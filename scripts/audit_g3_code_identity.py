#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = {"SSE": "sse", "SZSE": "szse"}


def transition_bar_dates(g3: Path, exchange: str, old: str, new: str) -> tuple[list[date], list[date]]:
    subdir = SUPPORTED.get(exchange)
    if subdir is None:
        raise ValueError(f"unsupported transition exchange: {exchange}")
    root = g3 / subdir
    old_dates: list[date] = []
    new_dates: list[date] = []
    paths = sorted(root.glob(f"{subdir}_*.csv.gz"))
    if not paths:
        raise ValueError(f"no G3 annual files for {exchange} under {root}")
    for p in paths:
        with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                code = r.get("code")
                if code == old:
                    old_dates.append(date.fromisoformat(r["trade_date"]))
                elif code == new:
                    new_dates.append(date.fromisoformat(r["trade_date"]))
    return old_dates, new_dates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    g3 = Path(a.root)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    transitions = json.loads((ROOT / "config/security_code_transitions.json").read_text(encoding="utf-8"))
    result = []

    for t in transitions:
        exchange = str(t["exchange"])
        old = str(t["old_code"])
        new = str(t["new_code"])
        eff = date.fromisoformat(str(t["effective_date"]))
        try:
            old_dates, new_dates = transition_bar_dates(g3, exchange, old, new)
        except Exception as exc:
            errors.append(f"{exchange} {old}->{new}: {exc}")
            result.append({
                "exchange": exchange,
                "old_code": old,
                "new_code": new,
                "effective_date": t["effective_date"],
                "old_bar_count": 0,
                "new_bar_count": 0,
            })
            continue

        if not old_dates:
            errors.append(f"predecessor has zero official G3 bars: {exchange}:{old}")
        if not new_dates:
            errors.append(f"successor has zero official G3 bars: {exchange}:{new}")
        if old_dates and max(old_dates) >= eff:
            errors.append(f"predecessor bar survives transition {exchange}:{old}: {max(old_dates)} >= {eff}")
        if new_dates and min(new_dates) < eff:
            errors.append(f"successor bar predates transition {exchange}:{new}: {min(new_dates)} < {eff}")
        if new_dates and min(new_dates) != eff:
            errors.append(f"successor first official bar is not transition effective date {exchange}:{new}: {min(new_dates)} != {eff}")

        result.append({
            "exchange": exchange,
            "old_code": old,
            "new_code": new,
            "effective_date": t["effective_date"],
            "old_bar_count": len(old_dates),
            "old_first": min(old_dates).isoformat() if old_dates else None,
            "old_last": max(old_dates).isoformat() if old_dates else None,
            "new_bar_count": len(new_dates),
            "new_first": min(new_dates).isoformat() if new_dates else None,
            "new_last": max(new_dates).isoformat() if new_dates else None,
        })

    report = {
        "gate": "G3_CODE_TIME_IDENTITY",
        "pass": not errors,
        "supported_exchanges": sorted(SUPPORTED),
        "transitions": result,
        "errors": errors,
    }
    (out / "g3_code_identity_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
