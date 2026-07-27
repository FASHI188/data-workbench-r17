#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import time
from datetime import date, datetime, timedelta
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
COVERAGE_START = date(2015, 1, 1)
COVERAGE_END = date(2026, 7, 27)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def get(session: requests.Session, url: str) -> requests.Response:
    r = session.get(
        url,
        headers={"User-Agent": UA, "Referer": "https://www.cninfo.com.cn/"},
        timeout=60,
    )
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


def transitions() -> list[dict]:
    path = ROOT / "config/security_code_transitions.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def load_stage2_identities() -> set[str]:
    path = ROOT / "data/security_lifecycle/security_intervals.csv"
    out: set[str] = set()
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out.add(row["code"])
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


def payload_for(code: str, org: str, category: str, start: date, end: date) -> dict[str, str]:
    return {
        "pageNum": "1",
        "pageSize": "30",
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


def query_announcements(
    session: requests.Session,
    code: str,
    org: str,
    category: str,
    start: date,
    end: date,
) -> tuple[dict, bytes]:
    resp = post(session, payload_for(code, org, category, start, end))
    return resp.json(), resp.content


def freeze_pdf(session: requests.Session, item: dict) -> dict:
    adjunct = str(item.get("adjunctUrl") or "").lstrip("/")
    if not adjunct:
        raise ValueError("announcement has no adjunctUrl")
    url = STATIC_ROOT + adjunct
    pdf = get(session, url)
    ctype = pdf.headers.get("Content-Type", "")
    if not pdf.content.startswith(b"%PDF"):
        raise ValueError(f"not PDF content-type={ctype}")
    return {
        "announcement_id": item.get("announcementId"),
        "code": item.get("secCode"),
        "url": url,
        "bytes": len(pdf.content),
        "sha256": sha(pdf.content),
    }


def main() -> int:
    outdir = ROOT / "data/stage3_source_probe"
    outdir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    stock_resp = get(session, STOCK_MAP_URL)
    stock_obj = stock_resp.json()
    stock_list = stock_obj.get("stockList") or []
    stock_map = {
        str(x.get("code")): str(x.get("orgId"))
        for x in stock_list
        if x.get("code") and x.get("orgId")
    }
    transition_rows = transitions()
    transition_new = {r["old_code"]: r["new_code"] for r in transition_rows}
    stage2_codes = load_stage2_identities()

    direct_covered = {c for c in stage2_codes if c in stock_map}
    alias_covered = {
        c
        for c in stage2_codes - direct_covered
        if c in transition_new and transition_new[c] in stock_map
    }
    unresolved_stage2_codes = sorted(stage2_codes - direct_covered - alias_covered)

    errors: list[str] = []
    if unresolved_stage2_codes:
        errors.append(
            f"Stage2 identities without direct/official-transition CNINFO orgId: "
            f"{unresolved_stage2_codes[:50]} count={len(unresolved_stage2_codes)}"
        )

    sample_reports: list[dict] = []
    pdf_hashes: list[dict] = []
    code_diagnostics: list[dict] = []

    for code in SAMPLES:
        lookup_code = code
        org = stock_map.get(code)
        alias_used = None
        if not org and code in transition_new:
            lookup_code = transition_new[code]
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
            diag["status"] = "NO_ORG_ID_IN_CURRENT_STOCK_MAP_OR_OFFICIAL_TRANSITION_ALIAS"
            code_diagnostics.append(diag)
            continue

        for family, category in CATEGORIES.items():
            try:
                obj, raw = query_announcements(
                    session, lookup_code, org, category, COVERAGE_START, COVERAGE_END
                )
                announcements = obj.get("announcements") or []
                diag["category_counts"][family] = int(
                    obj.get("totalAnnouncement") or len(announcements)
                )
                page_digest = sha(raw)
                for item in announcements[:3]:
                    published_at, midnight = normalize_time(item.get("announcementTime"))
                    sample_reports.append(
                        {
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
                    )
                    if item.get("adjunctUrl") and len(pdf_hashes) < 8:
                        try:
                            pdf_hashes.append(freeze_pdf(session, item))
                        except Exception as exc:
                            errors.append(
                                f"PDF {code} {item.get('announcementId')}: {exc!r}"
                            )
                time.sleep(0.08)
            except Exception as exc:
                errors.append(f"query {code} {family}: {exc!r}")
        diag["status"] = "QUERY_ATTEMPTED"
        code_diagnostics.append(diag)

    identity_windows: list[dict] = []
    historical_pdf_hashes: list[dict] = []
    for t in transition_rows:
        old_code = t["old_code"]
        new_code = t["new_code"]
        eff = date.fromisoformat(t["effective_date"])
        old_org = stock_map.get(old_code) or stock_map.get(new_code)
        new_org = stock_map.get(new_code) or stock_map.get(old_code)
        for label, query_code, org, start, end, expected_code in (
            (
                "PRE_TRANSITION",
                old_code,
                old_org,
                COVERAGE_START,
                eff - timedelta(days=1),
                old_code,
            ),
            (
                "POST_TRANSITION",
                new_code,
                new_org,
                eff,
                COVERAGE_END,
                new_code,
            ),
        ):
            rec = {
                "exchange": t["exchange"],
                "old_code": old_code,
                "new_code": new_code,
                "effective_date": t["effective_date"],
                "window": label,
                "query_code": query_code,
                "org_id": org,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "expected_sec_code": expected_code,
            }
            if not org:
                rec["status"] = "NO_ORG_ID"
                errors.append(f"identity window has no orgId: {rec}")
                identity_windows.append(rec)
                continue
            try:
                obj, raw = query_announcements(
                    session, query_code, org, CATEGORIES["ANNUAL"], start, end
                )
                anns = obj.get("announcements") or []
                matching = [a for a in anns if str(a.get("secCode")) == expected_code]
                rec.update(
                    {
                        "total_announcement": int(
                            obj.get("totalAnnouncement") or len(anns)
                        ),
                        "returned_first_page": len(anns),
                        "returned_sec_codes": sorted(
                            {str(a.get("secCode")) for a in anns if a.get("secCode")}
                        ),
                        "expected_identity_match_count": len(matching),
                        "query_response_sha256": sha(raw),
                        "status": "PASS" if matching else "FAIL_NO_EXPECTED_IDENTITY",
                    }
                )
                if not matching:
                    errors.append(f"historical code identity not returned: {rec}")
                elif label == "PRE_TRANSITION":
                    try:
                        historical_pdf_hashes.append(
                            {
                                "purpose": f"{old_code}_PRE_TRANSITION",
                                **freeze_pdf(session, matching[0]),
                            }
                        )
                    except Exception as exc:
                        errors.append(f"historical PDF {old_code}: {exc!r}")
            except Exception as exc:
                rec["status"] = f"QUERY_ERROR:{exc!r}"
                errors.append(f"identity query {query_code} {label}: {exc!r}")
            identity_windows.append(rec)

    delisted_identity_check: dict = {
        "code": "601268",
        "window": "2015-01-01~2015-12-31",
    }
    org_601268 = stock_map.get("601268")
    if not org_601268:
        delisted_identity_check["status"] = "NO_ORG_ID"
        errors.append("601268 missing from CNINFO stock map")
    else:
        try:
            obj, raw = query_announcements(
                session,
                "601268",
                org_601268,
                CATEGORIES["ANNUAL"],
                date(2015, 1, 1),
                date(2015, 12, 31),
            )
            anns = obj.get("announcements") or []
            matching = [a for a in anns if str(a.get("secCode")) == "601268"]
            delisted_identity_check.update(
                {
                    "org_id": org_601268,
                    "total_announcement": int(
                        obj.get("totalAnnouncement") or len(anns)
                    ),
                    "expected_identity_match_count": len(matching),
                    "query_response_sha256": sha(raw),
                    "status": "PASS" if matching else "FAIL_NO_601268_REPORT",
                }
            )
            if not matching:
                errors.append("601268 has no 2015 annual-report identity match")
            else:
                try:
                    historical_pdf_hashes.append(
                        {
                            "purpose": "601268_DELISTED_IDENTITY",
                            **freeze_pdf(session, matching[0]),
                        }
                    )
                except Exception as exc:
                    errors.append(f"601268 historical PDF: {exc!r}")
        except Exception as exc:
            delisted_identity_check["status"] = f"QUERY_ERROR:{exc!r}"
            errors.append(f"601268 identity query: {exc!r}")

    timestamped = [r for r in sample_reports if r["announcement_time_local"]]
    non_midnight = [r for r in timestamped if not r["announcement_time_is_midnight"]]
    all_timestamps_midnight = bool(timestamped) and not non_midnight
    report = {
        "gate": "S3G1A_CNINFO_PERIODIC_FILING_SOURCE_PROBE_V2",
        "pass": (
            not errors
            and bool(sample_reports)
            and bool(pdf_hashes)
            and not unresolved_stage2_codes
            and all(r.get("status") == "PASS" for r in identity_windows)
            and delisted_identity_check.get("status") == "PASS"
        ),
        "stock_map_url": STOCK_MAP_URL,
        "stock_map_sha256": sha(stock_resp.content),
        "stock_map_rows": len(stock_list),
        "stage2_identity_count": len(stage2_codes),
        "stage2_identity_direct_org_id_count": len(direct_covered),
        "stage2_identity_transition_alias_org_id_count": len(alias_covered),
        "stage2_identity_unresolved_org_id_count": len(unresolved_stage2_codes),
        "stage2_identity_unresolved_org_id_samples": unresolved_stage2_codes[:100],
        "sample_codes": SAMPLES,
        "code_diagnostics": code_diagnostics,
        "sample_report_count": len(sample_reports),
        "timestamped_sample_count": len(timestamped),
        "non_midnight_timestamp_count": len(non_midnight),
        "all_sample_timestamps_midnight": all_timestamps_midnight,
        "timing_interpretation": "CNINFO periodic-report announcementTime resolved to midnight in the probe. Stage3 therefore treats CNINFO announcementTime as date-only for this source family and defers effective_session to the first later trading session. No same-day use is permitted from this field alone.",
        "pdf_hash_count": len(pdf_hashes),
        "pdf_hashes": pdf_hashes,
        "historical_identity_windows": identity_windows,
        "historical_identity_pdf_hashes": historical_pdf_hashes,
        "delisted_identity_check": delisted_identity_check,
        "sample_reports": sample_reports[:80],
        "errors": errors,
    }
    (outdir / "cninfo_periodic_filing_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
