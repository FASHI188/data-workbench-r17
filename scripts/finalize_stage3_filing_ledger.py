#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")
EXPECTED_IDENTITIES = 3401
EXPECTED_G3_DAYS = 2808
OUT_FIELDS = [
    "exchange",
    "source_code",
    "effective_code",
    "org_id",
    "report_family",
    "announcement_id",
    "announcement_title",
    "source_published_at",
    "publication_precision",
    "economic_date",
    "effective_session",
    "available_at",
    "usable_in_stage2",
    "availability_reason",
    "revision_kind",
    "revision_sequence",
    "supersedes_announcement_id",
    "is_full_report_candidate",
    "source_url",
    "query_page",
    "query_response_sha256",
]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_intervals(path: Path) -> dict[tuple[str, str], tuple[date, date | None]]:
    out = {}
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            a = date.fromisoformat(r["listed_from"])
            b = date.fromisoformat(r["listed_to_exclusive"]) if r.get("listed_to_exclusive") else None
            out[(r["exchange"], r["code"])] = (a, b)
    return out


def load_transitions() -> list[dict]:
    path = ROOT / "config/security_code_transitions.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def active(interval: tuple[date, date | None] | None, day: date) -> bool:
    if interval is None:
        return False
    a, b = interval
    return day >= a and (b is None or day < b)


def remap_effective_code(
    exchange: str,
    source_code: str,
    session: date,
    intervals: dict[tuple[str, str], tuple[date, date | None]],
    transitions: list[dict],
) -> str | None:
    if active(intervals.get((exchange, source_code)), session):
        return source_code
    for t in transitions:
        if t["exchange"] != exchange:
            continue
        if t["old_code"] == source_code and session >= date.fromisoformat(t["effective_date"]):
            new_code = t["new_code"]
            if active(intervals.get((exchange, new_code)), session):
                return new_code
    return None


def g3_trading_days(g3root: Path) -> list[date]:
    days = set()
    candidates = sorted(g3root.rglob("szse_*.csv.gz"))
    if not candidates:
        raise RuntimeError(f"no SZSE G3 files found under {g3root}")
    for p in candidates:
        # Ignore accidental non-data gzip files by requiring the normalized schema.
        with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
            rd = csv.DictReader(f)
            if not rd.fieldnames or "trade_date" not in rd.fieldnames or "code" not in rd.fieldnames:
                continue
            for r in rd:
                if r.get("trade_date"):
                    days.add(date.fromisoformat(r["trade_date"]))
    return sorted(days)


def next_session(pub: date, trading_days: list[date]) -> date | None:
    i = bisect.bisect_right(trading_days, pub)
    return trading_days[i] if i < len(trading_days) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--g2-intervals", required=True)
    ap.add_argument("--g3-root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    root = Path(args.root)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    manifests = sorted(root.rglob("filing_ledger_shard*.manifest.json"))
    data_files = sorted(root.rglob("filing_ledger_shard*.csv.gz"))
    errors: list[str] = []
    if len(manifests) != 8:
        errors.append(f"expected 8 shard manifests, got {len(manifests)}")
    if len(data_files) != 8:
        errors.append(f"expected 8 shard data files, got {len(data_files)}")

    selected_total = 0
    source_pages = 0
    source_rows = 0
    full_candidates = 0
    zero_all = []
    stock_map_shas = set()
    rows: list[dict] = []
    category_totals = defaultdict(int)

    manifest_by_file = {}
    for mp in manifests:
        m = json.loads(mp.read_text(encoding="utf-8"))
        selected_total += int(m.get("selected_security_identities", 0))
        source_pages += int(m.get("request_pages", 0))
        source_rows += int(m.get("ledger_rows", 0))
        full_candidates += int(m.get("full_report_candidates", 0))
        zero_all += m.get("zero_all_category_securities") or []
        if m.get("stock_map_sha256"):
            stock_map_shas.add(m["stock_map_sha256"])
        for k, v in (m.get("category_source_totals") or {}).items():
            category_totals[k] += int(v)
        if m.get("errors"):
            errors.append(f"{mp.name} errors: {m['errors'][:30]}")
        manifest_by_file[m.get("data_file")] = m

    if selected_total != EXPECTED_IDENTITIES:
        errors.append(f"selected security identities {selected_total} != expected {EXPECTED_IDENTITIES}")
    if len(stock_map_shas) != 1:
        errors.append(f"CNINFO stock map changed across shards: {sorted(stock_map_shas)}")

    for p in data_files:
        m = manifest_by_file.get(p.name)
        if not m:
            errors.append(f"no manifest for {p.name}")
            continue
        actual = sha(p.read_bytes())
        if actual != m.get("data_sha256"):
            errors.append(f"data hash mismatch {p.name}")
            continue
        rows.extend(read_gz(p))
    if len(rows) != source_rows:
        errors.append(f"merged ledger rows {len(rows)} != manifest rows {source_rows}")

    # Announcement IDs should be unique to one code/family identity in this dataset.
    aid_map = defaultdict(set)
    for r in rows:
        aid_map[r["announcement_id"]].add((r["exchange"], r["code"], r["report_family"]))
    ambiguous_ids = {k: sorted(v) for k, v in aid_map.items() if len(v) > 1}
    if ambiguous_ids:
        sample = list(ambiguous_ids.items())[:20]
        errors.append(f"announcement IDs map to multiple code/family identities: {sample} count={len(ambiguous_ids)}")

    intervals = load_intervals(Path(args.g2_intervals))
    transitions = load_transitions()
    trading_days = g3_trading_days(Path(args.g3_root))
    if len(trading_days) != EXPECTED_G3_DAYS:
        errors.append(f"G3 trading-day count {len(trading_days)} != expected {EXPECTED_G3_DAYS}")

    finalized = []
    missing_pub = []
    missing_period = []
    missing_url = []
    unavailable_after_publication = []
    code_time_remaps = []

    for r in rows:
        pub_s = r.get("source_published_date") or ""
        is_full = r.get("is_full_report_candidate") == "1"
        if not pub_s:
            missing_pub.append((r["exchange"], r["code"], r["announcement_id"]))
            pub = None
        else:
            pub = date.fromisoformat(pub_s)
        if is_full and not r.get("economic_date"):
            missing_period.append((r["exchange"], r["code"], r["announcement_id"], r["announcement_title"]))
        if is_full and not r.get("source_url"):
            missing_url.append((r["exchange"], r["code"], r["announcement_id"]))

        eff = next_session(pub, trading_days) if pub else None
        effective_code = None
        usable = False
        reason = "MISSING_PUBLICATION_DATE" if not pub else "NO_LATER_G3_SESSION_WITHIN_STAGE2"
        available_at = ""
        if eff is not None:
            effective_code = remap_effective_code(
                r["exchange"], r["code"], eff, intervals, transitions
            )
            if effective_code:
                usable = True
                reason = "DATE_ONLY_NEXT_G3_TRADING_SESSION"
                available_at = datetime.combine(eff, datetime.min.time(), tzinfo=TZ).isoformat()
                if effective_code != r["code"]:
                    code_time_remaps.append(
                        {
                            "exchange": r["exchange"],
                            "source_code": r["code"],
                            "effective_code": effective_code,
                            "announcement_id": r["announcement_id"],
                            "publication_date": pub_s,
                            "effective_session": eff.isoformat(),
                        }
                    )
            else:
                reason = "NO_ACTIVE_SECURITY_IDENTITY_ON_NEXT_SESSION"
                unavailable_after_publication.append(
                    (r["exchange"], r["code"], r["announcement_id"], pub_s, eff.isoformat())
                )

        finalized.append(
            {
                "exchange": r["exchange"],
                "source_code": r["code"],
                "effective_code": effective_code or "",
                "org_id": r["org_id"],
                "report_family": r["report_family"],
                "announcement_id": r["announcement_id"],
                "announcement_title": r["announcement_title"],
                "source_published_at": pub_s,
                "publication_precision": "DATE_ONLY",
                "economic_date": r["economic_date"],
                "effective_session": eff.isoformat() if eff else "",
                "available_at": available_at,
                "usable_in_stage2": "1" if usable else "0",
                "availability_reason": reason,
                "revision_kind": r["revision_kind"],
                "revision_sequence": "",
                "supersedes_announcement_id": "",
                "is_full_report_candidate": r["is_full_report_candidate"],
                "source_url": r["source_url"],
                "query_page": r["query_page"],
                "query_response_sha256": r["query_response_sha256"],
            }
        )

    if missing_pub:
        errors.append(f"filing rows missing publication date: {missing_pub[:30]} count={len(missing_pub)}")
    if missing_period:
        errors.append(f"full-report candidates missing parsed economic date: {missing_period[:30]} count={len(missing_period)}")
    if missing_url:
        errors.append(f"full-report candidates missing source URL: {missing_url[:30]} count={len(missing_url)}")

    # Immutable revision chain is issuer(period/family)-based so code changes do not break it.
    groups = defaultdict(list)
    for i, r in enumerate(finalized):
        if r["is_full_report_candidate"] == "1" and r["economic_date"]:
            groups[(r["org_id"], r["report_family"], r["economic_date"])].append(i)
    multi_original = []
    revision_groups = 0
    for key, idxs in groups.items():
        idxs.sort(key=lambda i: (finalized[i]["source_published_at"], int(finalized[i]["announcement_id"]) if finalized[i]["announcement_id"].isdigit() else finalized[i]["announcement_id"]))
        if len(idxs) > 1:
            revision_groups += 1
        previous = ""
        originals = 0
        for seq, i in enumerate(idxs, start=1):
            finalized[i]["revision_sequence"] = str(seq)
            finalized[i]["supersedes_announcement_id"] = previous
            previous = finalized[i]["announcement_id"]
            originals += finalized[i]["revision_kind"] == "ORIGINAL_FULL_REPORT"
        if originals > 1:
            multi_original.append({"key": key, "announcement_ids": [finalized[i]["announcement_id"] for i in idxs]})

    # Multiple nominal originals are logged, not silently collapsed. They remain separate immutable versions.
    finalized.sort(key=lambda r: (r["source_published_at"], r["exchange"], r["source_code"], r["announcement_id"], r["report_family"]))
    out_path = outdir / "stage3_periodic_filing_ledger.csv.gz"
    with gzip.open(out_path, "wt", encoding="utf-8", newline="", compresslevel=9) as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(finalized)

    full_final = [r for r in finalized if r["is_full_report_candidate"] == "1"]
    usable_full = [r for r in full_final if r["usable_in_stage2"] == "1"]
    report = {
        "gate": "S3G1E_POINT_IN_TIME_PERIODIC_FILING_LEDGER",
        "pass": not errors,
        "coverage_start": "2015-01-01",
        "coverage_end": "2026-07-24",
        "security_identity_count": selected_total,
        "g3_trading_days": len(trading_days),
        "source_query_pages": source_pages,
        "source_category_totals": dict(category_totals),
        "ledger_rows": len(finalized),
        "full_report_candidates": len(full_final),
        "usable_full_report_candidates": len(usable_full),
        "revision_groups": revision_groups,
        "multiple_nominal_original_groups": len(multi_original),
        "multiple_nominal_original_samples": multi_original[:50],
        "date_only_policy": "Every CNINFO periodic-report filing is conservatively effective only on the first strictly later G3 trading session; same-day use is prohibited.",
        "code_time_effective_remaps": len(code_time_remaps),
        "code_time_effective_remap_samples": code_time_remaps[:100],
        "unavailable_after_publication_count": len(unavailable_after_publication),
        "unavailable_after_publication_samples": unavailable_after_publication[:100],
        "zero_all_category_security_count": len(set(zero_all)),
        "zero_all_category_security_samples": sorted(set(zero_all))[:100],
        "stock_map_sha256": next(iter(stock_map_shas)) if len(stock_map_shas) == 1 else None,
        "ledger_sha256": sha(out_path.read_bytes()),
        "errors": errors,
    }
    (outdir / "stage3_periodic_filing_ledger_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
