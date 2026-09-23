#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import time
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
STOCK_MAP_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
STATIC_ROOT = "https://static.cninfo.com.cn/"
START = date(2015, 1, 1)
END = date(2026, 7, 24)
PAGE_SIZE = 30
CATEGORIES = {
    "ANNUAL": ("category_ndbg_szsh", "年度报告", 12, 31),
    "SEMI": ("category_bndbg_szsh", "半年度报告", 6, 30),
    "Q1": ("category_yjdbg_szsh", "第一季度报告", 3, 31),
    "Q3": ("category_sjdbg_szsh", "第三季度报告", 9, 30),
}
FIELDS = [
    "exchange",
    "code",
    "org_id",
    "report_family",
    "announcement_id",
    "announcement_title",
    "source_published_date",
    "announcement_time_raw",
    "economic_date",
    "revision_kind",
    "is_full_report_candidate",
    "source_url",
    "query_page",
    "query_response_sha256",
]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def request_json(session: requests.Session, payload: dict[str, str], attempts: int = 6):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            r = session.post(
                QUERY_URL,
                data=payload,
                headers={
                    "User-Agent": UA,
                    "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=60,
            )
            r.raise_for_status()
            obj = r.json()
            if not isinstance(obj, dict) or "announcements" not in obj:
                raise ValueError(f"unexpected CNINFO payload keys={list(obj)[:20] if isinstance(obj,dict) else type(obj)}")
            return r.content, obj
        except Exception as exc:
            last = exc
            if attempt < attempts:
                time.sleep(min(0.6 * (2 ** (attempt - 1)), 8.0))
    raise RuntimeError(f"CNINFO query failed after {attempts} attempts: {last!r}")


def get_stock_map(session: requests.Session):
    r = session.get(
        STOCK_MAP_URL,
        headers={"User-Agent": UA, "Referer": "https://www.cninfo.com.cn/"},
        timeout=60,
    )
    r.raise_for_status()
    obj = r.json()
    rows = obj.get("stockList") or []
    m = {str(x.get("code")): str(x.get("orgId")) for x in rows if x.get("code") and x.get("orgId")}
    return r.content, rows, m


def load_intervals() -> list[dict]:
    rows = []
    path = ROOT / "data/security_lifecycle/security_intervals.csv"
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            a = date.fromisoformat(r["listed_from"])
            b = date.fromisoformat(r["listed_to_exclusive"]) if r.get("listed_to_exclusive") else None
            if a <= END and (b is None or b > START):
                rows.append({**r, "_from": a, "_to": b})
    rows.sort(key=lambda r: (r["exchange"], r["code"]))
    return rows


def window(row: dict) -> tuple[date, date]:
    a = max(START, row["_from"])
    b = END if row["_to"] is None else min(END, row["_to"] - timedelta(days=1))
    return a, b


def payload(code: str, org: str, category: str, start: date, end: date, page: int) -> dict[str, str]:
    return {
        "pageNum": str(page),
        "pageSize": str(PAGE_SIZE),
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": f"{code},{org}",
        "searchkey": "",
        "secid": "",
        "category": category,
        "trade": "",
        "seDate": f"{start.isoformat()}~{end.isoformat()}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }


def published_date(item: dict) -> str | None:
    raw = item.get("announcementTime")
    try:
        ms = int(raw)
    except Exception:
        return None
    # CNINFO periodic-report timestamps resolve to local midnight; UTC+8 date is stable.
    from datetime import datetime
    from zoneinfo import ZoneInfo
    dt = datetime.fromtimestamp(ms / 1000, tz=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Shanghai"))
    return dt.date().isoformat()


def classify_title(title: str, family: str) -> tuple[str, str, bool]:
    title_clean = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", title or ""))
    _, phrase, month, day = CATEGORIES[family]
    years = re.findall(r"(20\d{2})年", title_clean)
    year = int(years[0]) if years else None
    economic = date(year, month, day).isoformat() if year else ""

    has_phrase = phrase in title_clean
    is_summary = "摘要" in title_clean
    notice_words = ("更正公告", "补充公告", "关于", "取消", "问询", "回复")
    is_notice = any(x in title_clean for x in notice_words)
    revised_words = ("修订", "更正后", "更新后", "修正版", "更正版", "修订稿")
    is_revised = any(x in title_clean for x in revised_words)

    is_full = bool(year and has_phrase and not is_summary and not is_notice)
    if is_full and is_revised:
        kind = "REVISED_FULL_REPORT"
    elif is_full:
        kind = "ORIGINAL_FULL_REPORT"
    elif is_summary:
        kind = "SUMMARY"
    elif "更正" in title_clean or "补充" in title_clean:
        kind = "CORRECTION_OR_SUPPLEMENT_NOTICE"
    else:
        kind = "OTHER_CATEGORY_DOCUMENT"
    return economic, kind, is_full


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--shards", type=int, default=16)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if not (0 <= args.shard < args.shards):
        raise ValueError("invalid shard")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    intervals = load_intervals()
    selected = [r for i, r in enumerate(intervals) if i % args.shards == args.shard]
    session = requests.Session()
    stock_raw, stock_rows, stock_map = get_stock_map(session)

    errors = []
    rows = []
    requests_meta = []
    zero_all = []
    category_totals = {k: 0 for k in CATEGORIES}

    for idx, sec in enumerate(selected, start=1):
        code = sec["code"]
        org = stock_map.get(code)
        if not org:
            errors.append(f"missing CNINFO orgId for {sec['exchange']}:{code}")
            continue
        a, b = window(sec)
        security_count = 0
        for family, (category, _, _, _) in CATEGORIES.items():
            try:
                raw, obj = request_json(session, payload(code, org, category, a, b, 1))
                total = int(obj.get("totalAnnouncement") or 0)
                pages = max(1, math.ceil(total / PAGE_SIZE))
                page_objs = [(1, raw, obj)]
                for pageno in range(2, pages + 1):
                    raw2, obj2 = request_json(session, payload(code, org, category, a, b, pageno))
                    page_objs.append((pageno, raw2, obj2))
                    time.sleep(0.03)

                seen_ids = set()
                returned = 0
                for pageno, page_raw, page_obj in page_objs:
                    anns = page_obj.get("announcements") or []
                    returned += len(anns)
                    requests_meta.append(
                        {
                            "exchange": sec["exchange"],
                            "code": code,
                            "org_id": org,
                            "family": family,
                            "window_start": a.isoformat(),
                            "window_end": b.isoformat(),
                            "page": pageno,
                            "total_announcement": total,
                            "returned_rows": len(anns),
                            "sha256": sha(page_raw),
                        }
                    )
                    for item in anns:
                        aid = str(item.get("announcementId") or "")
                        if not aid:
                            errors.append(f"missing announcementId {code} {family} page={pageno}")
                            continue
                        if aid in seen_ids:
                            continue
                        seen_ids.add(aid)
                        sec_code = str(item.get("secCode") or "")
                        if sec_code != code:
                            errors.append(f"code filter mismatch requested={code} returned={sec_code} aid={aid}")
                            continue
                        title = str(item.get("announcementTitle") or "")
                        econ, revision, is_full = classify_title(title, family)
                        pub = published_date(item) or ""
                        adjunct = str(item.get("adjunctUrl") or "").lstrip("/")
                        rows.append(
                            {
                                "exchange": sec["exchange"],
                                "code": code,
                                "org_id": org,
                                "report_family": family,
                                "announcement_id": aid,
                                "announcement_title": title,
                                "source_published_date": pub,
                                "announcement_time_raw": str(item.get("announcementTime") or ""),
                                "economic_date": econ,
                                "revision_kind": revision,
                                "is_full_report_candidate": "1" if is_full else "0",
                                "source_url": STATIC_ROOT + adjunct if adjunct else "",
                                "query_page": str(pageno),
                                "query_response_sha256": sha(page_raw),
                            }
                        )
                if returned < min(total, PAGE_SIZE * pages):
                    errors.append(f"pagination shortfall {code} {family}: total={total} returned={returned}")
                category_totals[family] += total
                security_count += total
            except Exception as exc:
                errors.append(f"query {sec['exchange']}:{code} {family}: {exc!r}")
            time.sleep(0.03)
        if security_count == 0:
            zero_all.append(f"{sec['exchange']}:{code}")
        if idx % 50 == 0:
            print(f"shard {args.shard}/{args.shards} {idx}/{len(selected)} securities", flush=True)

    # Same announcement may occasionally be classified into more than one category; keep one
    # immutable metadata row and audit duplicates explicitly.
    rows.sort(key=lambda r: (r["source_published_date"], r["exchange"], r["code"], r["announcement_id"], r["report_family"]))
    dup_keys = []
    seen = set()
    for r in rows:
        k = (r["exchange"], r["code"], r["announcement_id"], r["report_family"])
        if k in seen:
            dup_keys.append(k)
        seen.add(k)
    if dup_keys:
        errors.append(f"duplicate announcement rows: {dup_keys[:20]} count={len(dup_keys)}")

    data_path = outdir / f"filing_ledger_shard{args.shard:02d}.csv.gz"
    with gzip.open(data_path, "wt", encoding="utf-8", newline="", compresslevel=9) as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    manifest = {
        "stage": "S3G1E_PERIODIC_FILING_LEDGER_SHARD",
        "shard": args.shard,
        "shards": args.shards,
        "coverage_start": START.isoformat(),
        "coverage_end": END.isoformat(),
        "selected_security_identities": len(selected),
        "ledger_rows": len(rows),
        "full_report_candidates": sum(r["is_full_report_candidate"] == "1" for r in rows),
        "category_source_totals": category_totals,
        "request_pages": len(requests_meta),
        "request_page_metadata": requests_meta,
        "stock_map_rows": len(stock_rows),
        "stock_map_sha256": sha(stock_raw),
        "zero_all_category_securities": zero_all,
        "data_file": data_path.name,
        "data_sha256": sha(data_path.read_bytes()),
        "errors": errors,
    }
    (outdir / f"filing_ledger_shard{args.shard:02d}.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "shard": args.shard,
                "selected": len(selected),
                "rows": len(rows),
                "full_report_candidates": manifest["full_report_candidates"],
                "request_pages": len(requests_meta),
                "zero_all": len(zero_all),
                "errors": len(errors),
            },
            ensure_ascii=False,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
