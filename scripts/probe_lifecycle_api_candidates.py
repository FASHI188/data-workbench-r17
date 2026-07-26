#!/usr/bin/env python3
"""Probe exchange-owned lifecycle API candidates without scraping exchange webpages.

The output is diagnostic only. Candidate endpoints must be structurally reconciled
before any row is admitted into the G2 lifecycle ledger.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
SSE_SQL = "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L"
SSE_REFERER = "https://www.sse.com.cn/"
SZSE_REFERER = "https://www.szse.cn/"


def parse_jsonp(raw: bytes):
    s = raw.decode("utf-8", errors="strict").strip()
    m = re.match(r"^[^(]+\((.*)\)\s*;?$", s, flags=re.S)
    if m:
        s = m.group(1)
    return json.loads(s)


def get(url: str, referer: str) -> bytes:
    s = requests.Session()
    headers = {
        "User-Agent": UA,
        "Referer": referer,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "X-Requested-With": "XMLHttpRequest",
    }
    r = s.get(url, headers=headers, timeout=45)
    r.raise_for_status()
    if not r.content:
        raise RuntimeError(f"empty response: {url}")
    return r.content


def recursive_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from recursive_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from recursive_dicts(v)


def summarize_sse(status: str) -> dict:
    encoded = quote(status, safe=",")
    url = (
        "https://query.sse.com.cn/sseQuery/commonQuery.do"
        "?jsonCallBack=cb123&STOCK_TYPE=1&REG_PROVINCE=&CSRC_CODE=&STOCK_CODE="
        f"&sqlId={SSE_SQL}&COMPANY_STATUS={encoded}&type=inParams&isPagination=true"
        "&pageHelp.cacheSize=1&pageHelp.beginPage=1&pageHelp.pageSize=5000&pageHelp.pageNo=1&pageHelp.endPage=1"
    )
    raw = get(url, SSE_REFERER)
    payload = parse_jsonp(raw)
    rows = payload.get("result") or payload.get("data") or []
    if not isinstance(rows, list):
        rows = []
    statuses = {}
    delisted = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        st = str(row.get("COMPANY_STATUS") or row.get("COMPANY_STATUS_CODE") or "")
        statuses[st] = statuses.get(st, 0) + 1
        dd = str(row.get("DELIST_DATE") or "").strip()
        if dd and dd != "-":
            delisted.append({
                "code": row.get("A_STOCK_CODE"),
                "name": row.get("COMPANY_ABBR"),
                "list_date": row.get("LIST_DATE") or row.get("A_LIST_DATE"),
                "delist_date": dd,
                "company_status": st,
                "list_board": row.get("LIST_BOARD"),
            })
    page_help = payload.get("pageHelp") if isinstance(payload, dict) else None
    return {
        "status_param": status,
        "url": url,
        "http_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "row_count": len(rows),
        "company_status_counts": statuses,
        "delist_date_count": len(delisted),
        "delist_samples": delisted[:30],
        "page_help": page_help,
        "payload_keys": list(payload.keys()) if isinstance(payload, dict) else [],
    }


def summarize_szse(catalog: str, tabkey: str, showtype: str) -> dict:
    if showtype == "JSON":
        url = f"https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID={catalog}&TABKEY={tabkey}&PAGENO=1"
    else:
        url = f"https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID={catalog}&TABKEY={tabkey}"
    raw = get(url, SZSE_REFERER)
    result = {
        "catalog": catalog,
        "tabkey": tabkey,
        "showtype": showtype,
        "url": url,
        "http_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "prefix_hex": raw[:24].hex(),
    }
    if showtype == "JSON":
        payload = json.loads(raw.decode("utf-8"))
        result["top_type"] = type(payload).__name__
        metadata = []
        samples = []
        for row in recursive_dicts(payload):
            if isinstance(row.get("metadata"), dict):
                metadata.append(row["metadata"])
            if any(k in row for k in ("zqdm", "agdm", "gsdm", "证券代码", "公司代码")):
                samples.append(row)
        result["metadata"] = metadata[:10]
        result["row_samples"] = samples[:20]
    return result


def main() -> int:
    outdir = Path("data/lifecycle_api_probe")
    outdir.mkdir(parents=True, exist_ok=True)
    report = {"sse": [], "szse": []}

    sse_params = ["", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "1,2,3,4,5,6,7,8,9,10"]
    for status in sse_params:
        try:
            report["sse"].append(summarize_sse(status))
        except Exception as exc:
            report["sse"].append({"status_param": status, "error": f"{type(exc).__name__}: {exc}"})

    for catalog, tab in [("1793_ssgs", "tab2"), ("1793_ssgs", "tab1"), ("1793", "tab2")]:
        for showtype in ("JSON", "xlsx"):
            try:
                report["szse"].append(summarize_szse(catalog, tab, showtype))
            except Exception as exc:
                report["szse"].append({
                    "catalog": catalog, "tabkey": tab, "showtype": showtype,
                    "error": f"{type(exc).__name__}: {exc}",
                })

    path = outdir / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
