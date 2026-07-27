#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import requests

from stage3_financial_pdf_parser import parse_pdf_bytes

ROOT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
SAMPLES = [
    {
        "name": "600519_2024_ANNUAL",
        "url": "https://static.cninfo.com.cn/finalpage/2025-04-03/1222993920.PDF",
        "expected": {
            "OPERATING_REVENUE": "170899152276.34",
            "OPERATING_COST": "13789482367.98",
            "NET_PROFIT_ATTRIBUTABLE_TO_PARENT": "86228146421.62",
            "NET_PROFIT_EX_NONRECURRING_ATTRIBUTABLE_TO_PARENT": "86240905977.42",
            "NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES": "92463692168.43",
            "TOTAL_ASSETS": "298944579918.70",
            "TOTAL_LIABILITIES": "56933264798.10",
            "EQUITY_ATTRIBUTABLE_TO_PARENT": "233105984399.47",
            "TOTAL_EQUITY": "242011315120.60"
        },
        "required_tier1": 6,
        "required_tier2": 3
    },
    {
        "name": "000001_2024_Q1_BANK",
        "url": "https://static.cninfo.com.cn/finalpage/2024-04-20/1219692666.PDF",
        "expected": {
            "OPERATING_REVENUE": "38770000000",
            "NET_PROFIT_ATTRIBUTABLE_TO_PARENT": "14932000000",
            "NET_PROFIT_EX_NONRECURRING_ATTRIBUTABLE_TO_PARENT": "14906000000",
            "NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES": "-21382000000",
            "TOTAL_ASSETS": "5729398000000",
            "EQUITY_ATTRIBUTABLE_TO_PARENT": "415632000000"
        },
        "required_tier1": 6,
        "required_tier2": 1
    },
    {
        "name": "000001_2018_SEMI_OLDER_FORMAT",
        "url": "https://static.cninfo.com.cn/finalpage/2018-08-16/1205289447.PDF",
        "expected": {
            "OPERATING_REVENUE": "57241000000",
            "NET_PROFIT_ATTRIBUTABLE_TO_PARENT": "13372000000",
            "NET_PROFIT_EX_NONRECURRING_ATTRIBUTABLE_TO_PARENT": "13326000000",
            "NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES": "7455000000",
            "TOTAL_ASSETS": "3367399000000",
            "EQUITY_ATTRIBUTABLE_TO_PARENT": "208188000000",
            "TOTAL_LIABILITIES": "3139258000000",
            "TOTAL_EQUITY": "228141000000"
        },
        "required_tier1": 6,
        "required_tier2": 2
    },
    {
        "name": "600519_2015_Q3_OLDER_FORMAT",
        "url": "https://static.cninfo.com.cn/finalpage/2015-10-23/1201716208.PDF",
        "expected": {},
        "required_tier1": 5,
        "required_tier2": 1
    }
]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def get_pdf(s: requests.Session, url: str) -> bytes:
    r = s.get(url, headers={"User-Agent": UA, "Referer": "https://www.cninfo.com.cn/"}, timeout=90)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise ValueError(f"not PDF: {url} type={r.headers.get('Content-Type')}")
    return r.content


def relerr(a: Decimal, b: Decimal) -> Decimal:
    return abs(a-b) / max(abs(b), Decimal("1"))


def main() -> int:
    out = ROOT / "data/stage3_source_probe"
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    results = []
    errors = []
    for spec in SAMPLES:
        try:
            raw = get_pdf(s, spec["url"])
            parsed = parse_pdf_bytes(raw)
            checks = []
            for concept, expected_s in spec["expected"].items():
                o = parsed["observations"][concept]
                if o["status"] != "FOUND":
                    errors.append(f"{spec['name']} {concept}: NOT_FOUND")
                    checks.append({"concept":concept,"pass":False,"reason":"NOT_FOUND"})
                    continue
                actual = Decimal(str(o["normalized_cny_value"]))
                expected = Decimal(expected_s)
                err = relerr(actual, expected)
                ok = err <= Decimal("0.000001")
                if not ok:
                    errors.append(f"{spec['name']} {concept}: actual={actual} expected={expected} relerr={err}")
                checks.append({"concept":concept,"pass":ok,"actual":str(actual),"expected":str(expected),"relative_error":str(err)})
            if parsed["tier1_found"] < int(spec["required_tier1"]):
                errors.append(f"{spec['name']}: tier1 coverage {parsed['tier1_found']} < {spec['required_tier1']}")
            if parsed["tier2_found"] < int(spec["required_tier2"]):
                errors.append(f"{spec['name']}: tier2 coverage {parsed['tier2_found']} < {spec['required_tier2']}")
            results.append({
                "name":spec["name"],"url":spec["url"],"bytes":len(raw),"sha256":sha(raw),
                "required_tier1":spec["required_tier1"],"required_tier2":spec["required_tier2"],
                "expected_checks":checks,"parsed":parsed
            })
        except Exception as exc:
            errors.append(f"{spec['name']}: {exc!r}")
            results.append({"name":spec["name"],"url":spec["url"],"error":repr(exc)})
    report = {
        "gate":"S3G1H_ORIGINAL_FILING_PDF_PARSER_PROBE",
        "pass":not errors,
        "sample_count":len(SAMPLES),
        "authority":"CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256",
        "results":results,
        "errors":errors,
    }
    (out/"financial_pdf_parser_probe.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if not errors else 2

if __name__ == "__main__":
    raise SystemExit(main())
