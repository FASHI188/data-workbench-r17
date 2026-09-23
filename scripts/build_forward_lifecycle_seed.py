#!/usr/bin/env python3
"""Build a disposable forward lifecycle seed from the freshly reconciled current master.

This does NOT alter the frozen Stage2 seed in Git history. It is intended for an isolated
freshness evidence run where the workspace copy of current_list_seed.csv may be replaced
before reusing the existing strict G2 fetch/build/audit chain.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path

FIELDS = [
    "exchange", "code", "event_type", "effective_date", "announced_at", "name",
    "source_url", "source_sha256", "evidence_class", "source_payload",
]


def normalize_date(value: str) -> str:
    s = (value or "").strip()
    if re.fullmatch(r"\d{8}", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return date.fromisoformat(s).isoformat()


def load_manifest(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("hard_gate_status") != "PASS_CANDIDATE":
        raise ValueError("current master is not PASS_CANDIDATE")
    if not (obj.get("sse") or {}).get("sha256_raw"):
        raise ValueError("missing SSE source hash")
    if not (obj.get("szse") or {}).get("sha256_all_pages"):
        raise ValueError("missing SZSE source hash")
    return obj


def build_rows(master_csv: Path, manifest: dict) -> list[dict[str, str]]:
    with master_csv.open(encoding="utf-8", newline="") as f:
        master = list(csv.DictReader(f))
    if not master:
        raise ValueError("fresh current master is empty")

    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for row in master:
        ex = (row.get("exchange") or "").strip()
        code = (row.get("code") or "").strip()
        if ex not in {"SSE", "SZSE"}:
            raise ValueError(f"bad exchange: {ex!r}")
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError(f"bad code: {code!r}")
        key = (ex, code)
        if key in seen:
            raise ValueError(f"duplicate current identity: {ex}:{code}")
        seen.add(key)
        source_sha = manifest[ex.lower()]["sha256_raw" if ex == "SSE" else "sha256_all_pages"]
        payload = row.get("source_row_json") or ""
        if not payload:
            raise ValueError(f"missing source payload for {ex}:{code}")
        json.loads(payload)
        out.append({
            "exchange": ex,
            "code": code,
            "event_type": "LIST",
            "effective_date": normalize_date(row.get("listing_date") or ""),
            "announced_at": "",
            "name": row.get("name") or "",
            "source_url": row.get("source_url") or manifest[ex.lower()].get("url") or manifest[ex.lower()].get("url_template") or "",
            "source_sha256": source_sha,
            "evidence_class": "RETROSPECTIVE_PRIMARY",
            "source_payload": payload,
        })
    return sorted(out, key=lambda r: (r["exchange"], r["code"]))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master-csv", default="data/current_master/cn_main_a.csv")
    ap.add_argument("--manifest", default="data/current_master/manifest.json")
    ap.add_argument("--out", default="data/security_lifecycle/current_list_seed.csv")
    ap.add_argument("--summary", default="build/freshness-phase1/forward_lifecycle_seed.json")
    args = ap.parse_args()

    manifest = load_manifest(Path(args.manifest))
    rows = build_rows(Path(args.master_csv), manifest)
    write_rows(Path(args.out), rows)
    counts = {"SSE": 0, "SZSE": 0}
    for r in rows:
        counts[r["exchange"]] += 1
    report = {
        "status": "FORWARD_SEED_BUILT",
        "rows": len(rows),
        "sse": counts["SSE"],
        "szse": counts["SZSE"],
        "master_as_of": (manifest.get("szse") or {}).get("as_of"),
        "seed_sha256": sha256_file(Path(args.out)),
        "authoritative": False,
        "scope": "disposable freshness candidate workspace only",
    }
    Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
