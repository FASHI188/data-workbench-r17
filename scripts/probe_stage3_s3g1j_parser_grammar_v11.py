#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

import requests

from stage3_financial_pdf_parser_v6 import parse_pdf_bytes

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/stage3_source_probe_v11/s3g1j_parser_grammar_v11.json"

SAMPLES = [
    {
        "code": "600011",
        "label": "2014 annual combined-company title + unit-wei grammar",
        "url": "https://static.cninfo.com.cn/finalpage/2015-03-25/1200738245.PDF",
        "sha256": "ef0ec9a29d84344070cbeae3153a402db2da451ad80e82e50027770b349382db",
        "expected": {
            "TOTAL_ASSETS": "272164949588",
            "TOTAL_LIABILITIES": "188745048295",
            "TOTAL_EQUITY": "83419901293",
        },
    },
    {
        "code": "600618",
        "label": "2014 annual English financial statements",
        "url": "https://static.cninfo.com.cn/finalpage/2015-03-31/1200764410.PDF",
        "sha256": "59ea43113ecdf9907007f0ff2be3a06c5401e89e1054ef2c967e010f3e99a8f0",
        "expected": {
            "TOTAL_ASSETS": "5754717626.22",
            "TOTAL_LIABILITIES": "3498456005.50",
            "TOTAL_EQUITY": "2256261620.72",
            "OPERATING_REVENUE": "7015409267.56",
            "OPERATING_COST": "6375944582.66",
            "NET_PROFIT_ATTRIBUTABLE_TO_PARENT": "-592502499.95",
            "NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES": "-29059999.83",
        },
    },
    {
        "code": "601997",
        "label": "2019Q3 banking statement uses asset-total alias",
        "url": "https://static.cninfo.com.cn/finalpage/2019-10-29/1207030672.PDF",
        "sha256": "ae0168baa7c97c84fb91e06c2c5cc374a3031634fc77d6d501814826426f55fd",
        "expected": {
            "TOTAL_ASSETS": "552718354000",
            "TOTAL_LIABILITIES": "513748019000",
            "TOTAL_EQUITY": "38970335000",
        },
    },
    {
        "code": "600016",
        "label": "2022Q3 combined-bank title + unit-wei grammar",
        "url": "https://static.cninfo.com.cn/finalpage/2022-10-29/1214966958.PDF",
        "sha256": "0bd374f9395e4b84486ec34e2a908d2ee2d7809ec84fe7a5b91aa982947b8077",
        "expected": {
            "TOTAL_ASSETS": "7133921000000",
            "TOTAL_LIABILITIES": "6522726000000",
            "TOTAL_EQUITY": "611195000000",
        },
    },
    {
        "code": "600036",
        "label": "2022Q3 unaudited-prefix title + junyi unit grammar + asset-total alias",
        "url": "https://static.cninfo.com.cn/finalpage/2022-10-29/1214960794.PDF",
        "sha256": "399b58f6b8ca17e614474557c53ffa3718ce2b20634d9b04ee48f5b7e2316701",
        "expected": {
            "TOTAL_ASSETS": "9707111000000",
            "TOTAL_LIABILITIES": "8779344000000",
            "TOTAL_EQUITY": "927767000000",
        },
    },
]


def _download(session: requests.Session, sample: dict) -> bytes:
    response = session.get(sample["url"], timeout=90)
    response.raise_for_status()
    raw = response.content
    actual = hashlib.sha256(raw).hexdigest()
    if actual != sample["sha256"]:
        raise AssertionError(f"{sample['code']} SHA mismatch expected={sample['sha256']} actual={actual}")
    return raw


def _value(parsed: dict, concept: str) -> Decimal | None:
    obs = (parsed.get("observations") or {}).get(concept) or {}
    if obs.get("status") != "FOUND":
        return None
    return Decimal(str(obs.get("normalized_cny_value")))


def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 S3G1J-V11-probe"})
    rows = []
    errors: list[str] = []

    for sample in SAMPLES:
        row = {k: sample[k] for k in ("code", "label", "url", "sha256")}
        try:
            raw = _download(session, sample)
            parsed = parse_pdf_bytes(raw)
            row["validation_errors"] = parsed.get("validation_errors") or []
            row["balance_sheet_block"] = parsed.get("balance_sheet_block")
            row["tier1_found"] = parsed.get("tier1_found")
            row["tier2_found"] = parsed.get("tier2_found")
            if row["validation_errors"]:
                raise AssertionError(f"validation errors: {row['validation_errors']}")
            if not row["balance_sheet_block"]:
                raise AssertionError("missing validated balance_sheet_block")

            observed = {}
            for concept, expected_raw in sample["expected"].items():
                actual = _value(parsed, concept)
                expected = Decimal(expected_raw)
                observed[concept] = str(actual) if actual is not None else None
                if actual != expected:
                    raise AssertionError(f"{concept} expected={expected} actual={actual}")
            row["observed"] = observed

            a = _value(parsed, "TOTAL_ASSETS")
            l = _value(parsed, "TOTAL_LIABILITIES")
            e = _value(parsed, "TOTAL_EQUITY")
            if a is None or l is None or e is None or a != l + e:
                raise AssertionError(f"exact accounting identity failed A={a} L={l} E={e}")
            row["exact_identity"] = True
            row["status"] = "PASS"
        except Exception as exc:
            row["status"] = "FAIL"
            row["error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{sample['code']}: {type(exc).__name__}: {exc}")
        rows.append(row)

    report = {
        "gate": "S3G1J_V11_OFFICIAL_PDF_GRAMMAR_REGRESSION",
        "pass": not errors,
        "sample_count": len(SAMPLES),
        "hard_rules": {
            "official_pdf_sha_required": True,
            "exact_expected_values_required": True,
            "exact_a_equals_l_plus_e_required_for_probe": True,
            "production_relative_identity_tolerance_unchanged": "0.005",
            "no_current_f10_backfill": True,
            "no_tie_or_provenance_relaxation": True,
        },
        "rows": rows,
        "errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
