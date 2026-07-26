#!/usr/bin/env python3
"""Build survivorship-free security life intervals from official lifecycle events."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Event:
    exchange: str
    code: str
    event_type: str
    effective_date: date
    name: str
    source_url: str
    source_sha256: str
    evidence_class: str


@dataclass(frozen=True)
class Interval:
    exchange: str
    code: str
    name: str
    listed_from: str
    listed_to_exclusive: str | None
    list_evidence_class: str
    delist_evidence_class: str | None


def parse_date(s: str) -> date:
    return date.fromisoformat(s)


def load_events(path: Path) -> list[Event]:
    rows: list[Event] = []
    with path.open(encoding="utf-8", newline="") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            try:
                event = Event(
                    exchange=row["exchange"],
                    code=row["code"],
                    event_type=row["event_type"],
                    effective_date=parse_date(row["effective_date"]),
                    name=row.get("name", "") or "",
                    source_url=row["source_url"],
                    source_sha256=row["source_sha256"],
                    evidence_class=row["evidence_class"],
                )
            except Exception as exc:
                raise ValueError(f"bad lifecycle row {n}: {exc}") from exc
            if event.exchange not in {"SSE", "SZSE"}:
                raise ValueError(f"bad exchange at row {n}: {event.exchange}")
            if event.event_type not in {"LIST", "DELIST", "RENAME"}:
                raise ValueError(f"bad event_type at row {n}: {event.event_type}")
            if len(event.code) != 6 or not event.code.isdigit():
                raise ValueError(f"bad code at row {n}: {event.code}")
            if len(event.source_sha256) != 64:
                raise ValueError(f"bad sha256 at row {n}")
            rows.append(event)
    return rows


def build_intervals(events: list[Event]) -> list[Interval]:
    grouped: dict[tuple[str, str], list[Event]] = {}
    for e in events:
        grouped.setdefault((e.exchange, e.code), []).append(e)

    intervals: list[Interval] = []
    for key, seq in grouped.items():
        seq.sort(key=lambda e: (e.effective_date, {"LIST": 0, "RENAME": 1, "DELIST": 2}[e.event_type]))
        open_list: Event | None = None
        current_name = ""
        for e in seq:
            if e.event_type == "LIST":
                if open_list is not None:
                    raise ValueError(f"duplicate LIST without DELIST for {key[0]}:{key[1]}")
                open_list = e
                current_name = e.name or current_name
            elif e.event_type == "RENAME":
                if open_list is None:
                    raise ValueError(f"RENAME before LIST for {key[0]}:{key[1]}")
                current_name = e.name or current_name
            elif e.event_type == "DELIST":
                if open_list is None:
                    raise ValueError(f"DELIST before LIST for {key[0]}:{key[1]}")
                if e.effective_date <= open_list.effective_date:
                    raise ValueError(f"non-positive life interval for {key[0]}:{key[1]}")
                intervals.append(
                    Interval(
                        exchange=key[0], code=key[1], name=current_name or open_list.name,
                        listed_from=open_list.effective_date.isoformat(),
                        listed_to_exclusive=e.effective_date.isoformat(),
                        list_evidence_class=open_list.evidence_class,
                        delist_evidence_class=e.evidence_class,
                    )
                )
                open_list = None
                current_name = ""
        if open_list is not None:
            intervals.append(
                Interval(
                    exchange=key[0], code=key[1], name=current_name or open_list.name,
                    listed_from=open_list.effective_date.isoformat(), listed_to_exclusive=None,
                    list_evidence_class=open_list.evidence_class, delist_evidence_class=None,
                )
            )
    return sorted(intervals, key=lambda x: (x.exchange, x.code, x.listed_from))


def write_csv(path: Path, rows: list[Interval]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(Interval.__annotations__.keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(asdict(row))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="data/security_lifecycle/events.csv")
    ap.add_argument("--out", default="data/security_lifecycle/security_intervals.csv")
    args = ap.parse_args()

    events_path = Path(args.events)
    if not events_path.exists():
        print(json.dumps({"status": "FAIL", "reason": f"missing {events_path}"}, ensure_ascii=False))
        return 2
    events = load_events(events_path)
    intervals = build_intervals(events)
    if not intervals:
        raise RuntimeError("no lifecycle intervals built")
    write_csv(Path(args.out), intervals)
    print(json.dumps({"status": "BUILT", "events": len(events), "intervals": len(intervals)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
