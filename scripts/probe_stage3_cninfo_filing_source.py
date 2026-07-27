#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
TZ = ZoneInfo("Asia/Shanghai")
STOCK_MAP_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
STATIC_ROOT = "https://static.cninfo.com.cn/"
CATEGORIES = {
    "ANNUAL": "category_ndbg_szsh",
    "SEMI": "category_bndbg_szsh",
    "Q1": "category_yjdbg_szsh",
    "Q3": "category_sjdbg_szsh",
}
SAMPLES = ["000001", "600519", "601268", "000022", "001872", "000043", "001914"]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def get(session: requests.Session, url: str) -> requests.Response:
    r = session.get(url, headers={"User-Agent": UA, "Referer": "https://www.cninfo.com.cn/"}, timeout=60)
    r.raise_for_status()
    return r


def post(session: requests.Session, payload: dict[str, str]) -> requests.Response:
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


def load_transition_aliases() -> dict[str, str]:
    path = ROOT / "config/security_code_transitions.json"
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for row in json.loads(path.read_text(encoding="utf-8")):
        out[row["old_code"]] = row["new_code"]
    return out


def normalize_time(value: object) -> tuple[str | None, bool]:
    if value is None:
        return None, True
    try:
        x = int(value)
    except Exception:
        return None, True
    dt = datetime.fromtimestamp(x / 1000, tz=ZoneInfo("UTC")).astimezone(TZ)
    is_midnight = dt.hour == 0 and dt.minute == 0 and dt.second == 0
    return dt.isoformat(), is_midnight


def main() -> int:
    outdir = ROOT / "data/stage3_source_probe"
    outdir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    stock_resp = get(session, STOCK_MAP_URL)
    stock_obj = stock_resp.json()
    stock_list = stock_obj.get("stockList") or []
    stock_map = {str(x.get("code")): str(x.get("orgId")) for x in stock_list if x.get("code") and x.get("orgId")}
    aliases = load_transition_aliases()

    errors: list[str] = []
    sample_reports: list[dict] = []
    pdf_hashes: list[dict] = []
    code_diagnostics: list[dict] = []

    for code in SAMPLES:
        lookup_code = code
        org = stock_map.get(code)
        alias_used = None
        if not org and code in aliases:
            lookup_code = aliases[code]
            org = stock_map.get(lookup_code)
            alias_used = lookup_code if org else None
        diag = {
            "requested_code": code,
            "lookup_code": lookup_code,
            "alias_used": alias_used,
            "org_id_found": bool(org),
            "org_id": org,
            "category_counts": {},
        }
        if not org:
            diag["status"] = "NO_ORG_ID_IN_CURRENT_STOCK_MAP"
            code_diagnostics.append(diag)
            continue

        for family, category in CATEGORIES.items():
            payload = {
                "pageNum": "1",
                "pageSize": "30",
                "column": "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": f"{lookup_code},{org}",
                "searchkey": "",
                "secid": "",
                "category": category,
                "trade": "",
                "seDate": "2015-01-01~2026-07-27",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            try:
                resp = post(session, payload)
                obj = resp.json()
                announcements = obj.get("announcements") or []
                diag["category_counts"][family] = int(obj.get("totalAnnouncement") or len(announcements))
                page_digest = sha(resp.content)
                for item in announcements[:3]:
                    published_at, midnight = normalize_time(item.get("announcementTime"))
                    rec = {
                        "requested_code": code,
                        "query_code": lookup_code,
                        "sec_code": item.get("secCode"),
                        "sec_name": item.get("secName"),
                        "org_id": item.get("orgId"),
                        "announcement_id": item.get("announcementId"),
                        "announcement_title": item.get("announcementTitle"),
                        "announcement_time_raw": item.get("announcementTime"),
                        "announcement_time_local": published_at,
                        "announcement_time_is_midnight": midnight,
                        "adjunct_url": item.get("adjunctUrl"),
                        "report_family": family,
                        "query_response_sha256": page_digest,
                    }
                    sample_reports.append(rec)
                    adjunct = str(item.get("adjunctUrl") or "").lstrip("/")
                    if adjunct and len(pdf_hashes) < 8:
                        try:
                            pdf = get(session, STATIC_ROOT + adjunct)
                            ctype = pdf.headers.get("Content-Type", "")
                            if not pdf.content.startswith(b"%PDF"):
                                raise ValueError(f"not PDF content-type={ctype}")
                            pdf_hashes.append({
                                "announcement_id": item.get("announcementId"),
                                "code": item.get("secCode"),
                                "url": STATIC_ROOT + adjunct,
                                "bytes": len(pdf.content),
                                "sha256": sha(pdf.content),
                            })
                        except Exception as exc:
                            errors.append(f"PDF {code} {item.get('announcementId')}: {exc!r}")
                time.sleep(0.1)
            except Exception as exc:
                errors.append(f"query {code} {family}: {exc!r}")
        diag["status"] = "QUERY_ATTEMPTED"
        code_diagnostics.append(diag)

    timestamped = [r for r in sample_reports if r["announcement_time_local"]]
    non_midnight = [r for r in timestamped if not r["announcement_time_is_midnight"]]
    report = {
        "gate": "S3G1A_CNINFO_PERIODIC_FILING_SOURCE_PROBE",
        "pass": not errors and bool(sample_reports) and bool(pdf_hashes),
        "stock_map_url": STOCK_MAP_URL,
        "stock_map_sha256": sha(stock_resp.content),
        "stock_map_rows": len(stock_list),
        "sample_codes": SAMPLES,
        "code_diagnostics": code_diagnostics,
        "sample_report_count": len(sample_reports),
        "timestamped_sample_count": len(timestamped),
        "non_midnight_timestamp_count": len(non_midnight),
        "timing_interpretation": "If CNINFO announcementTime resolves to midnight, Stage3 treats it as date-only and defers availability to the next trading session. Only independently verifiable non-midnight timestamps may use intraday timing.",
        "pdf_hash_count": len(pdf_hashes),
        "pdf_hashes": pdf_hashes,
        "sample_reports": sample_reports[:60],
        "errors": errors,
    }
    (outdir / "cninfo_periodic_filing_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
