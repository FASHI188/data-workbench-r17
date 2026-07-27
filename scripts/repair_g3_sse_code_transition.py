#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import requests

import build_g3_ohlcv as g3

ROOT = Path(__file__).resolve().parents[1]
OLD = "601313"
NEW = "601360"
TARGET_SHARD = 7
AFFECTED_YEARS = {2015, 2016, 2017, 2018}


def fetch_raw(code: str) -> bytes:
    url = g3.sse_source_url(code)
    r = requests.get(
        url,
        headers={
            "User-Agent": g3.UA,
            "Referer": g3.SSE_REFERER,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
        timeout=60,
    )
    r.raise_for_status()
    if not r.content:
        raise RuntimeError(f"empty SSE day-k response for {code}")
    return r.content


def parse_registered_transition_source(
    raw: bytes,
    code: str,
    interval: tuple[date, date | None],
    end_day: date,
) -> tuple[list[dict[str, str]], dict]:
    payload = json.loads(raw.decode("utf-8"))
    if str(payload.get("code")) != code:
        raise ValueError(f"SSE code mismatch requested={code} payload={payload.get('code')}")
    source_rows = payload.get("kline") or []
    if not isinstance(source_rows, list):
        raise ValueError(f"SSE kline not list for {code}")

    rows: list[dict[str, str]] = []
    outside_lifecycle = 0
    last_day: date | None = None
    for item in source_rows:
        if not isinstance(item, list) or len(item) != 7:
            raise ValueError(f"SSE malformed kline {code}: {item!r}")
        s = str(item[0])
        day = date.fromisoformat(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
        if last_day is not None and day <= last_day:
            raise ValueError(f"SSE non-increasing dates {code}: {last_day} -> {day}")
        last_day = day
        if day < g3.COVERAGE_START or day > end_day:
            continue
        if not g3.active_on(interval, day):
            outside_lifecycle += 1
            continue
        o, h, l, c = map(g3.dec, item[1:5])
        g3.validate_ohlc(o, h, l, c)
        rows.append(
            {
                "exchange": "SSE",
                "code": code,
                "trade_date": day.isoformat(),
                "open": format(o, "f"),
                "high": format(h, "f"),
                "low": format(l, "f"),
                "close": format(c, "f"),
                "volume_shares": g3.norm_nonnegative_integer(item[5]),
                "amount_cny": g3.norm_nonnegative_integer(item[6]),
            }
        )
    return rows, {
        "code": code,
        "source_total_rows": len(source_rows),
        "normalized_rows": len(rows),
        "ignored_outside_registered_lifecycle": outside_lifecycle,
        "source_begin": payload.get("begin"),
        "source_end": payload.get("end"),
        "first_normalized_date": rows[0]["trade_date"] if rows else None,
        "last_normalized_date": rows[-1]["trade_date"] if rows else None,
    }


def read_gzip_rows(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="root containing sse/ and szse/")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    build = Path(args.root)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    sse = build / "sse"
    intervals = g3.load_intervals("SSE")
    if OLD not in intervals or NEW not in intervals:
        raise RuntimeError(f"corrected lifecycle missing {OLD}/{NEW}")
    old_iv = intervals[OLD]
    new_iv = intervals[NEW]
    if old_iv[1] != date(2018, 2, 28) or new_iv[0] != date(2018, 2, 28):
        raise RuntimeError(f"unexpected transition intervals old={old_iv} new={new_iv}")

    end_day = g3.coverage_end()
    rebuilt: dict[str, list[dict[str, str]]] = {}
    source_diags: dict[str, dict] = {}
    raw_evidence = {}
    for code, iv in ((OLD, old_iv), (NEW, new_iv)):
        raw = fetch_raw(code)
        rows, diag = parse_registered_transition_source(raw, code, iv, end_day)
        diag.update(
            {
                "url": g3.sse_source_url(code),
                "sha256": g3.sha256(raw),
                "bytes": len(raw),
                "repair_reason": "REGISTERED_CODE_TRANSITION_PIT_FILTER",
            }
        )
        rebuilt[code] = rows
        source_diags[code] = diag
        raw_path = outdir / f"sse_dayk_{code}.json"
        raw_path.write_bytes(raw)
        raw_evidence[code] = {"file": raw_path.name, "sha256": diag["sha256"], "bytes": len(raw)}

    # The successor endpoint may carry retroactively relabelled predecessor history.
    # This is expected only because the official code-transition is independently registered.
    if source_diags[NEW]["ignored_outside_registered_lifecycle"] <= 0:
        raise RuntimeError("successor source did not expose the retroactively relabelled history that triggered this repair")
    if not rebuilt[OLD]:
        raise RuntimeError("predecessor official source returned zero lifecycle rows")
    if not rebuilt[NEW]:
        raise RuntimeError("successor official source returned zero lifecycle rows")
    if max(date.fromisoformat(r["trade_date"]) for r in rebuilt[OLD]) >= date(2018, 2, 28):
        raise RuntimeError("predecessor rows survive transition")
    if min(date.fromisoformat(r["trade_date"]) for r in rebuilt[NEW]) != date(2018, 2, 28):
        raise RuntimeError("successor first row is not transition effective date")

    meta_path = sse / f"sse_shard{TARGET_SHARD:02d}_sources.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    sources = list(meta.get("sources") or [])
    old_sources = [x for x in sources if str(x.get("code")) in {OLD, NEW}]
    sources = [x for x in sources if str(x.get("code")) not in {OLD, NEW}]
    sources.extend([source_diags[OLD], source_diags[NEW]])
    sources.sort(key=lambda x: str(x.get("code") or ""))
    meta["sources"] = sources
    meta["securities"] = len(sources)

    files_by_year = {int(x["year"]): x for x in meta.get("files") or []}
    patch_counts = {}
    for year in sorted(AFFECTED_YEARS):
        fmeta = files_by_year.get(year)
        if fmeta is None:
            raise RuntimeError(f"target shard missing year metadata {year}")
        path = sse / fmeta["file"]
        rows = [r for r in read_gzip_rows(path) if r["code"] not in {OLD, NEW}]
        before = int(fmeta["rows"])
        add = []
        for code in (OLD, NEW):
            add.extend(r for r in rebuilt[code] if int(r["trade_date"][:4]) == year)
        rows.extend(add)
        n, digest = g3.write_gzip_csv(path, rows)
        fmeta["rows"] = n
        fmeta["sha256"] = digest
        patch_counts[str(year)] = {"before": before, "after": n, "inserted_transition_rows": len(add)}

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "gate": "G3_SSE_601313_601360_TARGETED_REPAIR",
        "pass": True,
        "transition": {"old_code": OLD, "new_code": NEW, "effective_date": "2018-02-28"},
        "old_source_entries_replaced": old_sources,
        "new_source_diagnostics": source_diags,
        "raw_evidence": raw_evidence,
        "patched_years": patch_counts,
        "untouched_years": [y for y in range(2019, end_day.year + 1)],
        "errors": [],
    }
    (outdir / "g3_sse_601313_601360_repair.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
