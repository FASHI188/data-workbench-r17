#!/usr/bin/env python3
"""Fail-closed Stage2 G3 audit for generated official OHLCV artifacts.

G3 certifies that every official source request in the acquisition contract was executed,
normalized files match their recorded hashes/counts, lifecycle scope is respected, and
SSE/SZSE resolve to the same trading-day calendar. Per-security no-row days are not
classified as missing here because they can be legitimate suspensions; G4 must explain
those state gaps before the whole Stage2B Research-Ready gate can pass.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_START = date(2015, 1, 1)
FIELDS = ["exchange", "code", "trade_date", "open", "high", "low", "close", "volume_shares", "amount_cny"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def coverage_end() -> date:
    manifest = json.loads((ROOT / "data/current_master/manifest.json").read_text(encoding="utf-8"))
    raw = str(manifest.get("szse", {}).get("as_of") or "").strip()
    m = re.search(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})", raw)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else date(2026, 7, 24)


def load_intervals(exchange: str) -> dict[str, tuple[date, date | None]]:
    out = {}
    with (ROOT / "data/security_lifecycle/security_intervals.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["exchange"] != exchange:
                continue
            start = date.fromisoformat(row["listed_from"])
            end_s = (row.get("listed_to_exclusive") or "").strip()
            end = date.fromisoformat(end_s) if end_s else None
            if row["code"] in out:
                raise ValueError(f"multiple intervals for {exchange}:{row['code']}")
            out[row["code"]] = (start, end)
    return out


def active_on(interval: tuple[date, date | None], day: date) -> bool:
    return day >= interval[0] and (interval[1] is None or day < interval[1])


def relevant_codes(intervals: dict[str, tuple[date, date | None]], end_day: date) -> set[str]:
    return {c for c, iv in intervals.items() if (iv[1] is None or iv[1] > COVERAGE_START) and iv[0] <= end_day}


def validate_data_file(path: Path, exchange: str, intervals: dict[str, tuple[date, date | None]], expected_year: int) -> tuple[int, set[str], set[str]]:
    rows = 0
    dates: set[str] = set()
    codes: set[str] = set()
    prev: tuple[str, str] | None = None
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            raise ValueError(f"schema mismatch {path}: {reader.fieldnames}")
        for row in reader:
            rows += 1
            if row["exchange"] != exchange:
                raise ValueError(f"exchange mismatch in {path}: {row['exchange']}")
            day = date.fromisoformat(row["trade_date"])
            if day.year != expected_year:
                raise ValueError(f"year mismatch in {path}: {day}")
            interval = intervals.get(row["code"])
            if interval is None or not active_on(interval, day):
                raise ValueError(f"row outside lifecycle {exchange}:{row['code']}:{day}")
            key = (row["trade_date"], row["code"])
            if prev is not None and key <= prev:
                raise ValueError(f"non-increasing/duplicate key in {path}: {prev} -> {key}")
            prev = key
            o,h,l,c = [Decimal(row[x]) for x in ("open","high","low","close")]
            if min(o,h,l,c) < 0 or h < max(o,l,c) or l > min(o,h,c):
                raise ValueError(f"OHLC invariant failed {exchange}:{row['code']}:{day}")
            if int(row["volume_shares"]) < 0 or int(row["amount_cny"]) < 0:
                raise ValueError(f"negative volume/amount {exchange}:{row['code']}:{day}")
            dates.add(row["trade_date"])
            codes.add(row["code"])
    return rows, dates, codes


def weekdays(start: date, end: date) -> set[str]:
    out = set()
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.add(d.isoformat())
        d += timedelta(days=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="build/g3")
    ap.add_argument("--out", default="data/ohlcv")
    args = ap.parse_args()
    build = Path(args.root)
    outdir = Path(args.out)
    errors: list[str] = []
    warnings: list[str] = []
    end_day = coverage_end()
    sse_intervals = load_intervals("SSE")
    szse_intervals = load_intervals("SZSE")
    expected_sse = relevant_codes(sse_intervals, end_day)
    expected_szse = relevant_codes(szse_intervals, end_day)

    file_manifest: list[dict] = []
    sse_dates: set[str] = set()
    szse_dates: set[str] = set()
    sse_codes_seen: set[str] = set()
    sse_source_codes: set[str] = set()
    sse_shard_ids: set[int] = set()
    sse_shards_declared: set[int] = set()
    sse_rows_total = 0
    sse_source_norm_total = 0
    zero_sse_codes: list[str] = []

    sse_meta_files = sorted((build / "sse").glob("sse_shard*_sources.json"))
    if not sse_meta_files:
        errors.append("no SSE source manifests")
    for meta_path in sse_meta_files:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            shard = int(meta["shard"]); shards = int(meta["shards"])
            sse_shard_ids.add(shard); sse_shards_declared.add(shards)
            local_codes = set()
            for src in meta.get("sources", []):
                code = str(src.get("code") or "")
                if code in sse_source_codes:
                    raise ValueError(f"SSE code fetched in multiple shards: {code}")
                sse_source_codes.add(code); local_codes.add(code)
                if not re.fullmatch(r"[0-9a-f]{64}", str(src.get("sha256") or "")):
                    raise ValueError(f"bad SSE source sha: {code}")
                if int(src.get("bytes") or 0) <= 0:
                    raise ValueError(f"empty SSE source: {code}")
                n = int(src.get("normalized_rows") or 0)
                sse_source_norm_total += n
                if n == 0:
                    zero_sse_codes.append(code)
            for fmeta in meta.get("files", []):
                path = build / "sse" / fmeta["file"]
                if not path.exists():
                    raise ValueError(f"missing SSE data file {path}")
                actual_sha = sha256_file(path)
                if actual_sha != fmeta["sha256"]:
                    raise ValueError(f"SSE data sha mismatch {path.name}")
                year = int(fmeta["year"])
                n, dates, codes = validate_data_file(path, "SSE", sse_intervals, year)
                if n != int(fmeta["rows"]):
                    raise ValueError(f"SSE row-count mismatch {path.name}: {n} != {fmeta['rows']}")
                if not codes <= local_codes:
                    raise ValueError(f"SSE data file contains code outside shard source set {path.name}")
                sse_rows_total += n; sse_dates |= dates; sse_codes_seen |= codes
                file_manifest.append({"exchange":"SSE","year":year,"file":path.name,"rows":n,"sha256":actual_sha})
        except Exception as exc:
            errors.append(f"SSE manifest {meta_path.name}: {type(exc).__name__}: {exc}")

    if len(sse_shards_declared) != 1:
        errors.append(f"inconsistent SSE shard counts: {sorted(sse_shards_declared)}")
    elif sse_shards_declared and sse_shard_ids != set(range(next(iter(sse_shards_declared)))):
        errors.append(f"missing SSE shards: have={sorted(sse_shard_ids)} declared={next(iter(sse_shards_declared))}")
    if sse_source_codes != expected_sse:
        errors.append(f"SSE source universe mismatch expected={len(expected_sse)} actual={len(sse_source_codes)} only_expected={sorted(expected_sse-sse_source_codes)[:20]} only_actual={sorted(sse_source_codes-expected_sse)[:20]}")
    if sse_rows_total != sse_source_norm_total:
        errors.append(f"SSE normalized row accounting mismatch files={sse_rows_total} sources={sse_source_norm_total}")
    if zero_sse_codes:
        warnings.append(f"SSE lifecycle securities with zero normalized trade rows require G4 state explanation: {len(zero_sse_codes)}; sample={zero_sse_codes[:20]}")

    szse_rows_total = 0
    expected_years = set(range(COVERAGE_START.year, end_day.year + 1))
    actual_years: set[int] = set()
    szse_meta_files = sorted((build / "szse").glob("szse_*_sources.json"))
    if not szse_meta_files:
        errors.append("no SZSE source manifests")
    for meta_path in szse_meta_files:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            year = int(meta["year"]); actual_years.add(year)
            year_start = max(COVERAGE_START, date(year,1,1)); year_end = min(end_day, date(year,12,31))
            expected_requests = weekdays(year_start, year_end)
            sources = meta.get("sources", [])
            source_days = {str(s.get("day")) for s in sources}
            if source_days != expected_requests:
                raise ValueError(f"weekday request coverage mismatch year={year} expected={len(expected_requests)} actual={len(source_days)}")
            positive_days = set()
            source_norm = 0
            for src in sources:
                if not re.fullmatch(r"[0-9a-f]{64}", str(src.get("sha256") or "")):
                    raise ValueError(f"bad SZSE source sha {src.get('day')}")
                if int(src.get("bytes") or 0) <= 0:
                    raise ValueError(f"empty SZSE source {src.get('day')}")
                n = int(src.get("normalized_rows") or 0); source_norm += n
                if int(src.get("source_data_rows") or 0) > 0:
                    positive_days.add(str(src["day"]))
                    if n <= 0:
                        raise ValueError(f"SZSE market-data day has zero in-scope rows {src['day']}")
            path = build / "szse" / meta["data_file"]
            if not path.exists():
                raise ValueError(f"missing SZSE data file {path}")
            actual_sha = sha256_file(path)
            if actual_sha != meta["data_sha256"]:
                raise ValueError(f"SZSE data sha mismatch {path.name}")
            n, dates, codes = validate_data_file(path, "SZSE", szse_intervals, year)
            if n != int(meta["rows"]) or n != source_norm:
                raise ValueError(f"SZSE row accounting mismatch year={year}: file={n}, meta={meta['rows']}, source={source_norm}")
            if dates != positive_days:
                raise ValueError(f"SZSE trading-date/data mismatch year={year}: data={len(dates)} source={len(positive_days)}")
            if not codes <= expected_szse:
                raise ValueError(f"SZSE data contains out-of-universe codes year={year}")
            szse_rows_total += n; szse_dates |= dates
            file_manifest.append({"exchange":"SZSE","year":year,"file":path.name,"rows":n,"sha256":actual_sha})
        except Exception as exc:
            errors.append(f"SZSE manifest {meta_path.name}: {type(exc).__name__}: {exc}")
    if actual_years != expected_years:
        errors.append(f"SZSE year coverage mismatch expected={sorted(expected_years)} actual={sorted(actual_years)}")

    only_sse = sorted(sse_dates - szse_dates)
    only_szse = sorted(szse_dates - sse_dates)
    if only_sse or only_szse:
        errors.append(f"SSE/SZSE trading-day calendar mismatch only_sse={only_sse[:20]} only_szse={only_szse[:20]}")

    file_manifest.sort(key=lambda x: (x["exchange"], x["year"], x["file"]))
    dataset_fingerprint = hashlib.sha256("\n".join(f"{x['file']}:{x['sha256']}:{x['rows']}" for x in file_manifest).encode()).hexdigest()
    report = {
        "gate": "G3",
        "pass": not errors,
        "coverage_start": COVERAGE_START.isoformat(),
        "coverage_end": end_day.isoformat(),
        "sse_source_securities": len(sse_source_codes),
        "sse_securities_with_trade_rows": len(sse_codes_seen),
        "sse_rows": sse_rows_total,
        "szse_rows": szse_rows_total,
        "total_rows": sse_rows_total + szse_rows_total,
        "trading_days": len(sse_dates & szse_dates),
        "dataset_fingerprint": dataset_fingerprint,
        "zero_sse_codes_requiring_g4": zero_sse_codes,
        "individual_nontrade_days_deferred_to_g4": True,
        "errors": errors,
        "warnings": warnings,
    }
    manifest = {
        "version": "V3.2.20-g3-official-ohlcv",
        "status": "PASS" if not errors else "FAIL",
        "coverage_start": COVERAGE_START.isoformat(),
        "coverage_end": end_day.isoformat(),
        "scope": "SSE_MAIN_A + SZSE_MAIN_A",
        "storage_policy": "Normalized bulk OHLCV remains in authenticated GitHub Actions artifacts; the public source repository stores code, hashes, counts and audit metadata rather than redistributing the full exchange dataset.",
        "sources": {
            "SSE": "official yunhq dayk per lifecycle security",
            "SZSE_pre_2025_07": "official CATALOGID=1815_stock single-day full-market XLSX",
            "SZSE_from_2025_07": "official CATALOGID=1815_stock_snapshot single-day full-market XLSX",
        },
        "files": file_manifest,
        "audit": report,
    }
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "g3_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "g3_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
