#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
CATEGORY = "category_ndbg_szsh"
WINDOW = "2025-01-01~2025-05-31"
PAGE_SIZES = [30, 100, 200, 500, 1000]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch(session: requests.Session, page_size: int, page_num: int) -> requests.Response:
    payload = {
        "pageNum": str(page_num),
        "pageSize": str(page_size),
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": "",
        "searchkey": "",
        "secid": "",
        "category": CATEGORY,
        "trade": "",
        "seDate": WINDOW,
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
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
    return r


def main() -> int:
    outdir = ROOT / "data/stage3_source_probe"
    outdir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    trials = []
    errors = []
    for size in PAGE_SIZES:
        try:
            r = fetch(s, size, 1)
            obj = r.json()
            anns = obj.get("announcements") or []
            ids = [str(x.get("announcementId")) for x in anns if x.get("announcementId")]
            trials.append(
                {
                    "requested_page_size": size,
                    "returned_rows": len(anns),
                    "unique_ids": len(set(ids)),
                    "total_announcement": int(obj.get("totalAnnouncement") or 0),
                    "has_more": obj.get("hasMore"),
                    "response_sha256": sha(r.content),
                }
            )
        except Exception as exc:
            errors.append({"page_size": size, "error": repr(exc)})

    usable = [x for x in trials if x["returned_rows"] > 0 and x["unique_ids"] == x["returned_rows"]]
    chosen = max(usable, key=lambda x: x["returned_rows"], default=None)
    cross_page = None
    if chosen:
        size = chosen["requested_page_size"]
        try:
            r1 = fetch(s, size, 1)
            r2 = fetch(s, size, 2)
            a1 = r1.json().get("announcements") or []
            a2 = r2.json().get("announcements") or []
            ids1 = {str(x.get("announcementId")) for x in a1 if x.get("announcementId")}
            ids2 = {str(x.get("announcementId")) for x in a2 if x.get("announcementId")}
            cross_page = {
                "page_size": size,
                "page1_rows": len(a1),
                "page2_rows": len(a2),
                "overlap_ids": len(ids1 & ids2),
                "page1_sha256": sha(r1.content),
                "page2_sha256": sha(r2.content),
            }
            if ids1 & ids2:
                errors.append({"cross_page_duplicate_ids": sorted(ids1 & ids2)[:20]})
        except Exception as exc:
            errors.append({"cross_page_error": repr(exc)})

    report = {
        "gate": "S3G1B_CNINFO_BULK_PAGINATION_PROBE",
        "pass": not errors and chosen is not None and cross_page is not None,
        "query_url": QUERY_URL,
        "category": CATEGORY,
        "window": WINDOW,
        "trials": trials,
        "chosen_page_size": chosen["requested_page_size"] if chosen else None,
        "chosen_returned_rows": chosen["returned_rows"] if chosen else None,
        "cross_page": cross_page,
        "errors": errors,
    }
    (outdir / "cninfo_bulk_pagination_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
