#!/usr/bin/env python3
"""Seed current active securities into the G2 lifecycle event ledger.

This is a bootstrap only. It deliberately marks evidence as RETROSPECTIVE_PRIMARY:
the current exchange master can establish the historical listing date of a security
that is still listed today, but it does not by itself recover securities that were
already delisted before the current snapshot.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

FIELDS = [
    "exchange",
    "code",
    "event_type",
    "effective_date",
    "announced_at",
    "name",
    "source_url",
    "source_sha256",
    "evidence_class",
    "source_payload",
]


def valid_iso_date(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def row_digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def seed(master_path: Path) -> list[dict[str, str]]:
    with master_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise RuntimeError("current master is empty")

    events: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for n, row in enumerate(rows, start=2):
        exchange = row.get("exchange", "")
        code = row.get("code", "")
        listing_date = row.get("listing_date", "")
        payload = row.get("source_row_json", "")
        if exchange not in {"SSE", "SZSE"}:
            raise ValueError(f"row {n}: invalid exchange {exchange!r}")
        if len(code) != 6 or not code.isdigit():
            raise ValueError(f"row {n}: invalid code {code!r}")
        if not listing_date:
            raise ValueError(f"row {n}: missing listing_date for {exchange}:{code}")
        listing_date = valid_iso_date(listing_date)
        if not payload:
            raise ValueError(f"row {n}: missing source_row_json for {exchange}:{code}")
        key = (exchange, code)
        if key in seen:
            raise ValueError(f"row {n}: duplicate current security {exchange}:{code}")
        seen.add(key)
        events.append(
            {
                "exchange": exchange,
                "code": code,
                "event_type": "LIST",
                "effective_date": listing_date,
                "announced_at": "",
                "name": row.get("name", ""),
                "source_url": row.get("source_url", ""),
                "source_sha256": row_digest(payload),
                "evidence_class": "RETROSPECTIVE_PRIMARY",
                "source_payload": payload,
            }
        )
    return sorted(events, key=lambda x: (x["exchange"], x["code"], x["effective_date"]))


def write_csv(path: Path, events: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(events)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default="data/current_master/cn_main_a.csv")
    ap.add_argument("--out", default="data/security_lifecycle/current_list_seed.csv")
    args = ap.parse_args()

    events = seed(Path(args.master))
    write_csv(Path(args.out), events)
    counts = {
        "SSE": sum(e["exchange"] == "SSE" for e in events),
        "SZSE": sum(e["exchange"] == "SZSE" for e in events),
    }
    print(json.dumps({"status": "CURRENT_ONLY_BOOTSTRAP", "events": len(events), "counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
