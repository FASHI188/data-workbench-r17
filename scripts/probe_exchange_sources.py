#!/usr/bin/env python3
"""Probe exchange-owned candidate endpoints from the execution environment.

This is diagnostics only. It never upgrades a source to authoritative evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"

SSE_PAGE = "https://www.sse.com.cn/assortment/stock/list/share/"
SZSE_PAGE = "https://www.szse.cn/certificate/maind/"

SOURCES = [
    {
        "id": "sse_current_sql",
        "warm": SSE_PAGE,
        "url": "https://query.sse.com.cn/sseQuery/commonQuery.do?jsonCallBack=jsonpCallback123456&STOCK_TYPE=1&REG_PROVINCE=&CSRC_CODE=&STOCK_CODE=&sqlId=COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L&COMPANY_STATUS=2%2C4%2C5%2C7%2C8&type=inParams&isPagination=true&pageHelp.cacheSize=1&pageHelp.beginPage=1&pageHelp.pageSize=25&pageHelp.pageNo=1&pageHelp.endPage=1",
        "origin": "https://www.sse.com.cn",
        "referer": SSE_PAGE,
    },
    {
        "id": "sse_legacy_list",
        "warm": SSE_PAGE,
        "url": "https://query.sse.com.cn/security/stock/getStockListData2.do?jsonCallBack=jsonpCallback123456&isPagination=true&stockCode=&csrcCode=&areaName=&stockType=1&pageHelp.cacheSize=1&pageHelp.beginPage=1&pageHelp.pageSize=25&pageHelp.pageNo=1&pageHelp.endPage=1",
        "origin": "https://www.sse.com.cn",
        "referer": SSE_PAGE,
    },
    {
        "id": "sse_legacy_download",
        "warm": SSE_PAGE,
        "url": "https://query.sse.com.cn/security/stock/downloadStockListFile.do?csrcCode=&stockCode=&areaName=&stockType=1",
        "origin": "https://www.sse.com.cn",
        "referer": SSE_PAGE,
    },
    {
        "id": "sse_quote_https_32042",
        "warm": "https://www.sse.com.cn/market/price/trends/",
        "url": "https://yunhq.sse.com.cn:32042/v1/sh1/list/exchange/equity?select=code%2Cname%2Ccpxxsubtype%2Ccpxxprodusta&begin=0&end=5",
        "origin": "https://www.sse.com.cn",
        "referer": "https://www.sse.com.cn/market/price/trends/",
    },
    {
        "id": "sse_quote_http_32041",
        "warm": "https://www.sse.com.cn/market/price/trends/",
        "url": "http://yunhq.sse.com.cn:32041/v1/sh1/list/exchange/equity?select=code%2Cname%2Ccpxxsubtype%2Ccpxxprodusta&begin=0&end=5",
        "origin": "https://www.sse.com.cn",
        "referer": "https://www.sse.com.cn/market/price/trends/",
    },
    {
        "id": "szse_json",
        "warm": SZSE_PAGE,
        "url": "https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=1110&TABKEY=tab1&PAGENO=1",
        "origin": "https://www.szse.cn",
        "referer": SZSE_PAGE,
    },
    {
        "id": "szse_xlsx",
        "warm": SZSE_PAGE,
        "url": "https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1110&TABKEY=tab1",
        "origin": "https://www.szse.cn",
        "referer": SZSE_PAGE,
    },
]


def probe(source: dict[str, str]) -> dict[str, Any]:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Connection": "keep-alive",
        }
    )
    result: dict[str, Any] = {"id": source["id"], "url": source["url"]}
    try:
        warm = s.get(source["warm"], timeout=20)
        result["warm_status"] = warm.status_code
        result["cookies_after_warm"] = sorted(s.cookies.keys())
    except Exception as exc:
        result["warm_error"] = f"{type(exc).__name__}: {exc}"

    headers = {
        "Referer": source["referer"],
        "Origin": source["origin"],
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        r = s.get(source["url"], headers=headers, timeout=30, allow_redirects=True)
        raw = r.content
        result.update(
            {
                "status": r.status_code,
                "final_url": r.url,
                "content_type": r.headers.get("content-type"),
                "length": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "prefix": raw[:240].decode("utf-8", errors="replace"),
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> int:
    out = {"results": [probe(x) for x in SOURCES]}
    path = Path("data/source_probe.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
