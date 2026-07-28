#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

import requests

from extract_stage3_financial_pdf_values_v7 import parse_pdf_bytes

EXPECTED = {
    ("603798", "ANNUAL", "2020-12-31", "2021-04-30"): "1209876947",
    ("605177", "Q1", "2021-03-31", "2021-04-30"): "1209877352",
    ("605168", "Q1", "2021-03-31", "2021-04-19"): "1209718403",
    ("603856", "Q3", "2020-09-30", "2020-10-28"): "1208623550",
    ("603993", "Q3", "2020-09-30", "2020-10-29"): "1208635673",
}


def read_versions(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V12-selected-source-probe",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=90,
    )
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise ValueError(f"not PDF bytes={len(response.content)} content_type={response.headers.get('Content-Type')}")
    return response.content


def _obs_value(parsed: dict, concept: str) -> Decimal | None:
    obs = (parsed.get("observations") or {}).get(concept) or {}
    if obs.get("status") != "FOUND":
        return None
    value = obs.get("normalized_cny_value")
    return Decimal(str(value)) if value not in (None, "") else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    versions = read_versions(Path(args.versions))
    by_business = {
        (r["source_code"], r["report_family"], r["economic_date"], r["source_published_at"]): r
        for r in versions
    }
    session = requests.Session()
    rows = []
    errors: list[str] = []

    for business_key, expected_id in EXPECTED.items():
        selected = by_business.get(business_key)
        row = {
            "business_key": list(business_key),
            "expected_announcement_id": expected_id,
        }
        try:
            if not selected:
                raise AssertionError("missing V3 selected source")
            actual_id = selected["canonical_announcement_id"]
            row.update(
                {
                    "actual_announcement_id": actual_id,
                    "canonical_title": selected["canonical_title"],
                    "canonical_source_url": selected["canonical_source_url"],
                    "selection_class": selected["selection_class"],
                }
            )
            if actual_id != expected_id:
                raise AssertionError(f"expected selected id={expected_id} actual={actual_id}")

            raw = _download(session, selected["canonical_source_url"])
            parsed = parse_pdf_bytes(raw)
            balance = parsed.get("balance_sheet_block")
            validation_errors = parsed.get("validation_errors") or []
            row.update(
                {
                    "source_sha256": hashlib.sha256(raw).hexdigest(),
                    "source_bytes": len(raw),
                    "page_count": parsed.get("page_count"),
                    "declared_a_share_codes": parsed.get("declared_a_share_codes") or [],
                    "tier1_found": parsed.get("tier1_found"),
                    "tier2_found": parsed.get("tier2_found"),
                    "balance_sheet_block": balance,
                    "validation_errors": validation_errors,
                }
            )
            if validation_errors:
                raise AssertionError(f"validation errors: {validation_errors}")
            if not balance:
                raise AssertionError("missing validated balance-sheet block")

            a = _obs_value(parsed, "TOTAL_ASSETS")
            l = _obs_value(parsed, "TOTAL_LIABILITIES")
            e = _obs_value(parsed, "TOTAL_EQUITY")
            if None in (a, l, e):
                raise AssertionError(f"missing A/L/E A={a} L={l} E={e}")
            residual = abs(a - (l + e))
            relative = residual / max(abs(a), abs(l + e), Decimal("1"))
            row.update(
                {
                    "total_assets_cny": str(a),
                    "total_liabilities_cny": str(l),
                    "total_equity_cny": str(e),
                    "identity_residual_cny": str(residual),
                    "identity_relative_error": str(relative),
                    "status": "PASS",
                }
            )
            if relative > Decimal("0.005"):
                raise AssertionError(f"A=L+E relative error {relative} exceeds unchanged 0.005 gate")
        except Exception as exc:
            row["status"] = "FAIL"
            row["error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{business_key}: {type(exc).__name__}: {exc}")
        rows.append(row)

    report = {
        "gate": "S3G1J_V12_SELECTED_SOURCE_PDF_PROBE",
        "pass": not errors,
        "sample_count": len(EXPECTED),
        "authority": "V3-selected CNINFO original PDF bytes; SHA recorded by this diagnostic",
        "policy": {
            "source_selection_must_match_expected_correction": True,
            "original_pdf_required": True,
            "v11_1_parser_required": True,
            "v9_declared_issuer_witness_preserved": True,
            "validated_joint_balance_block_required": True,
            "a_equals_l_plus_e_tolerance_unchanged": "0.005",
            "this_probe_does_not_freeze_sha_as_final_authority": True,
        },
        "rows": rows,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
