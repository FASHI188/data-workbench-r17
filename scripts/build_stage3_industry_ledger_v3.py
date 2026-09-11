#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from build_stage3_capco_industry_ledger import (
    extract_table_rows,
    normalize_record,
    load_intervals,
    load_transitions,
    g3_days,
    next_session,
    effective_code_for,
    sha,
)
from stage3_capco_discovery import discover_publications as discover_capco_publications
from stage3_csrc_industry_discovery import discover_csrc_publications

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
FIELDS = [
    "publication_title","publication_date","effective_session","available_at",
    "source_authority","source_page_url","source_page_sha256","source_pdf_url","source_pdf_sha256",
    "source_pdf_bytes","source_code","effective_code","company_name",
    "industry_code_primary","industry_codes_json","industry_names_json","raw_columns_json",
    "classification_system","parse_method","source_correction_json"
]

# The 2017Q1 CSRC PDF itself contains one internally inconsistent row:
# `603026 科森科技` under C26, while the issuer prospectus and subsequent CSRC
# classification identify 科森科技 as 603626 / C33.  Preserve the raw row in
# source_correction_json and correct only this independently evidenced source typo.
KERSEN_CORRECTION = {
    "publication_title": "2017年1季度上市公司行业分类结果",
    "wrong_code": "603026",
    "company_name_contains": "科森科技",
    "correct_code": "603626",
    "correct_industry_code_primary": "C33",
    "correct_industry_codes": ["C", "33", "C33"],
    "correct_industry_names": ["制造业", "金属制品业"],
    "evidence": [
        "https://www.csrc.gov.cn/csrc/c100103/c1452006/1452006/files/1616066689404_45886.pdf",
        "https://big5.sse.com.cn/site/cht/www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-23/603626_20260423_E9SL.pdf",
    ],
}


def norm_title(v: str) -> str:
    return re.sub(r"[.。\s]+$", "", re.sub(r"\s+", "", v or ""))


def period_year(title: str) -> int | None:
    m = re.search(r"(20\d{2})年", title or "")
    return int(m.group(1)) if m else None


def get_pdf(session: requests.Session, url: str, attempts: int = 5) -> bytes:
    last = None
    referer = "https://www.csrc.gov.cn/" if "csrc.gov.cn" in url else "https://www.capco.org.cn/"
    for i in range(attempts):
        try:
            r = session.get(url, headers={"User-Agent": UA, "Referer": referer}, timeout=90)
            r.raise_for_status()
            if not r.content.startswith(b"%PDF"):
                raise ValueError(f"not PDF type={r.headers.get('Content-Type')} bytes={len(r.content)}")
            return r.content
        except Exception as exc:
            last = exc
            if i + 1 < attempts:
                time.sleep(min(1.0 * (2 ** i), 8))
    raise RuntimeError(repr(last))


def select_authoritative_publications(session: requests.Session) -> tuple[list[dict], dict]:
    csrc_all = discover_csrc_publications(session)
    capco_all = discover_capco_publications(session)

    # CSRC is the earliest official publication authority for the legacy 2012
    # classification system through its final published total table (2021Q3).
    csrc = [
        p for p in csrc_all
        if p.get("publication_date")
        and date(2015, 1, 1) <= date.fromisoformat(p["publication_date"]) <= date(2021, 12, 31)
    ]
    # CAPCO becomes the total-table authority under the new guide; the first
    # discoverable aggregate result in this project is 2023H1, published 2024.
    capco = []
    for p in capco_all:
        y = period_year(str(p.get("title") or ""))
        if y is not None and y >= 2023 and p.get("publication_date"):
            q = dict(p)
            q["source_authority"] = "CAPCO_PRIMARY"
            capco.append(q)

    combined = csrc + capco
    dedup: dict[str, dict] = {}
    duplicate_period_titles = []
    for p in combined:
        key = norm_title(str(p.get("title") or ""))
        if key in dedup:
            duplicate_period_titles.append(key)
            # If the same period was somehow returned twice, earliest official
            # publication wins but the duplicate is surfaced in diagnostics.
            if str(p.get("publication_date") or "9999-99-99") < str(dedup[key].get("publication_date") or "9999-99-99"):
                dedup[key] = p
        else:
            dedup[key] = p
    selected = sorted(dedup.values(), key=lambda x:(x.get("publication_date") or "", norm_title(str(x.get("title") or ""))))
    diag = {
        "csrc_discovered": len(csrc_all),
        "csrc_selected_2015_through_2021q3": len(csrc),
        "capco_discovered": len(capco_all),
        "capco_selected_2023plus": len(capco),
        "selected_unique": len(selected),
        "duplicate_period_titles": duplicate_period_titles,
    }
    return selected, diag


def apply_source_correction(title: str, rec: dict) -> tuple[dict, dict | None]:
    if (
        norm_title(title) == norm_title(KERSEN_CORRECTION["publication_title"])
        and rec.get("source_code") == KERSEN_CORRECTION["wrong_code"]
        and KERSEN_CORRECTION["company_name_contains"] in str(rec.get("company_name") or "")
    ):
        before = dict(rec)
        fixed = dict(rec)
        fixed["source_code"] = KERSEN_CORRECTION["correct_code"]
        fixed["industry_code_primary"] = KERSEN_CORRECTION["correct_industry_code_primary"]
        fixed["industry_codes"] = list(KERSEN_CORRECTION["correct_industry_codes"])
        fixed["industry_names"] = list(KERSEN_CORRECTION["correct_industry_names"])
        correction = {
            "type": "OFFICIAL_SOURCE_TYPO_CORRECTION",
            "before": before,
            "after": fixed,
            "evidence": KERSEN_CORRECTION["evidence"],
        }
        return fixed, correction
    return rec, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--g2-intervals", required=True)
    ap.add_argument("--g3-root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    s = requests.Session()
    intervals = load_intervals(Path(a.g2_intervals))
    transitions = load_transitions()
    days = g3_days(Path(a.g3_root))
    if len(days) != 2808:
        errors.append(f"G3 trading-day count {len(days)} != 2808")

    publications, discovery_diag = select_authoritative_publications(s)
    if len(publications) != 34:
        errors.append(f"authoritative publication count {len(publications)} != 34")

    ledger = []
    pub_audit = []
    correction_audit = []
    duplicate_codes_after_correction = []

    for p in publications:
        pdf = p.get("preferred_pdf")
        if not pdf:
            errors.append(f"no preferred PDF for {p['title']} {p['detail_url']}")
            continue
        try:
            raw = get_pdf(s, str(pdf["url"]))
            rows, diag = extract_table_rows(raw)
            normalized = [x for x in (normalize_record(row) for row in rows) if x]
            pub_day = date.fromisoformat(str(p["publication_date"]))
            eff = next_session(pub_day, days)
            if eff is None:
                pub_audit.append({"title":p["title"],"publication_date":p["publication_date"],"status":"OUTSIDE_G3_AFTER_END"})
                continue
            local_seen = set()
            mainboard_count = 0
            for raw_rec in normalized:
                n, correction = apply_source_correction(str(p["title"]), raw_rec)
                ecode = effective_code_for(str(n["source_code"]), eff, intervals, transitions)
                if not ecode:
                    continue
                if ecode in local_seen:
                    duplicate_codes_after_correction.append({
                        "title":p["title"],"publication_date":p["publication_date"],"effective_code":ecode,
                        "source_code":n["source_code"],"company_name":n["company_name"],
                    })
                    continue
                local_seen.add(ecode)
                mainboard_count += 1
                correction_json = json.dumps(correction, ensure_ascii=False) if correction else ""
                if correction:
                    correction_audit.append({
                        "publication_title":p["title"],"publication_date":p["publication_date"],
                        "effective_session":eff.isoformat(),"effective_code":ecode,"correction":correction,
                    })
                authority = str(p.get("source_authority") or "CSRC_PRIMARY")
                system = "CAPCO_2023_GUIDE" if authority == "CAPCO_PRIMARY" else "CSRC_2012_GUIDE"
                ledger.append({
                    "publication_title":p["title"],"publication_date":p["publication_date"],
                    "effective_session":eff.isoformat(),
                    "available_at":datetime.combine(eff, datetime.min.time(), tzinfo=TZ).isoformat(),
                    "source_authority":authority,
                    "source_page_url":p["detail_url"],"source_page_sha256":p["detail_sha256"],
                    "source_pdf_url":pdf["url"],"source_pdf_sha256":sha(raw),"source_pdf_bytes":str(len(raw)),
                    "source_code":n["source_code"],"effective_code":ecode,"company_name":n["company_name"],
                    "industry_code_primary":n["industry_code_primary"],
                    "industry_codes_json":json.dumps(n["industry_codes"],ensure_ascii=False),
                    "industry_names_json":json.dumps(n["industry_names"],ensure_ascii=False),
                    "raw_columns_json":json.dumps(raw_rec["raw_columns"],ensure_ascii=False),
                    "classification_system":system,"parse_method":"PYMUPDF_TABLE_WITH_TEXT_FALLBACK",
                    "source_correction_json":correction_json,
                })
            pub_audit.append({
                "title":p["title"],"publication_date":p["publication_date"],"effective_session":eff.isoformat(),
                "source_authority":p.get("source_authority") or "CSRC_PRIMARY",
                "detail_url":p["detail_url"],"pdf_url":pdf["url"],"pdf_sha256":sha(raw),"pdf_bytes":len(raw),
                "raw_detected_rows":len(normalized),"mainboard_rows":mainboard_count,**diag,
            })
        except Exception as exc:
            errors.append(f"{p['title']}: {exc!r}")

    if duplicate_codes_after_correction:
        errors.append(
            f"duplicate mainboard codes remain after explicit source corrections: "
            f"{duplicate_codes_after_correction[:20]} count={len(duplicate_codes_after_correction)}"
        )
    if len(correction_audit) != 1:
        errors.append(f"expected exactly one frozen source typo correction, got {len(correction_audit)}")

    ledger.sort(key=lambda r:(r["effective_session"],r["effective_code"],r["publication_title"]))
    path = out / "stage3_industry_classification_ledger.csv.gz"
    with gzip.open(path,"wt",encoding="utf-8",newline="",compresslevel=9) as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(ledger)
    per_pub = defaultdict(int)
    for r in ledger:
        per_pub[(r["publication_title"],r["publication_date"])]+=1
    low = [
        {"title":k[0],"publication_date":k[1],"mainboard_rows":v}
        for k,v in per_pub.items() if v < 1000
    ]
    if low:
        errors.append(f"industry publications with implausibly low mainboard rows: {low[:20]} count={len(low)}")
    if len(per_pub) != 34:
        errors.append(f"publication snapshots with rows {len(per_pub)} != 34")

    report = {
        "gate":"S3G3B_POINT_IN_TIME_INDUSTRY_CLASSIFICATION_LEDGER_V3",
        "pass":not errors,
        "source_policy":{
            "legacy":"CSRC original statistical publication is authoritative through 2021Q3; CAPCO legacy mirrors are cross-check only.",
            "new":"CAPCO aggregate classification results are authoritative from the 2023 guide result series.",
            "gap":"No official aggregate 2021Q4/2022 total table was found; the last known classification remains the as-of state until superseded, and newly listed securities absent from the last published snapshot remain UNKNOWN.",
        },
        "discovery":discovery_diag,
        "publication_snapshots_with_rows":len(per_pub),
        "ledger_rows":len(ledger),
        "publication_audit":pub_audit,
        "source_corrections":correction_audit,
        "duplicate_codes_after_correction":duplicate_codes_after_correction,
        "low_coverage_publications":low,
        "ledger_sha256":sha(path.read_bytes()),
        "availability_policy":"Date-only official classification becomes usable on the first strictly later frozen G3 trading session.",
        "current_industry_backfill_used":False,
        "errors":errors,
    }
    (out/"stage3_industry_classification_audit.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    print(json.dumps({
        k:report[k] for k in (
            "gate","pass","discovery","publication_snapshots_with_rows","ledger_rows",
            "source_corrections","duplicate_codes_after_correction","low_coverage_publications","errors"
        )
    },ensure_ascii=False,indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
