#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

import fitz
import requests

from stage3_financial_pdf_parser_v9 import parse_pdf_bytes as v14_parse
from stage3_financial_spatial_alias_v16_3 import diagnose_spatial_balance_sheet_v16_6

REPRESENTATIVE_IDS = {
    "1200948256",  # 600500 annual 2014
    "1203240204",  # 600115 annual 2016
    "1202637566",  # 600679 semi 2016
    "1204557640",  # 600754 annual 2017
    "1205969212",  # 601390 annual 2018
    "1207547788",  # 000028 annual 2019
    "1209728461",  # 000625 annual 2020
    "1212671853",  # 601166 annual 2021
    "1219442543",  # 601688 annual 2023
    "1221090309",  # 601390 semi 2024
    "1222949445",  # 601688 annual 2024
    "1223096939",  # 000736 annual 2024; V16.5 initially selected prior/restated period
}
EXPECTED_RECOVERED_IDS = {
    "1200948256", "1203240204", "1204557640", "1207547788", "1209728461",
    "1212671853", "1219442543", "1221090309", "1222949445", "1223096939",
}
EXPECTED_000736_CURRENT = {
    "TOTAL_ASSETS": "107697681763.55",
    "TOTAL_LIABILITIES": "96659072585.14",
    "TOTAL_EQUITY": "11038609178.41",
}
FORBIDDEN_000736_PRIOR = {
    "TOTAL_ASSETS": "122643867000.04",
    "TOTAL_LIABILITIES": "104968810113.49",
    "TOTAL_EQUITY": "17675056886.55",
}


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def download(session: requests.Session, url: str) -> tuple[bytes, str]:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V16.6-statement-period-diagnostic",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    return raw, hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    versions = read_versions(Path(args.versions))
    missing = sorted(REPRESENTATIVE_IDS - set(versions))
    if missing:
        raise ValueError(f"representative ids missing from frozen versions: {missing}")

    session = requests.Session()
    rows = []
    errors = []
    for announcement_id in sorted(REPRESENTATIVE_IDS):
        version = versions[announcement_id]
        row = {
            "announcement_id": announcement_id,
            "source_code": version["source_code"],
            "report_family": version["report_family"],
            "economic_date": version["economic_date"],
            "canonical_title": version["canonical_title"],
            "canonical_source_url": version["canonical_source_url"],
        }
        try:
            raw, digest = download(session, version["canonical_source_url"])
            current = v14_parse(raw)
            doc = fitz.open(stream=raw, filetype="pdf")
            spatial = diagnose_spatial_balance_sheet_v16_6(doc, version["economic_date"])
            row.update({
                "download_sha256": digest,
                "page_count": doc.page_count,
                "v14_has_valid_balance_block": bool(current.get("balance_sheet_block")) and not bool(current.get("validation_errors")),
                "v14_validation_errors": current.get("validation_errors") or [],
                "v14_tier2_found": current.get("tier2_found"),
                "v16_spatial": spatial,
            })
        except Exception as exc:
            row["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{announcement_id}: {type(exc).__name__}: {exc}")
        rows.append(row)

    recovered = [row for row in rows if (row.get("v16_spatial") or {}).get("recovered")]
    recovered_ids = {row["announcement_id"] for row in recovered}

    guard_row = next(row for row in rows if row["announcement_id"] == "1223096939")
    guard_spatial = guard_row.get("v16_spatial") or {}
    guard_selected = guard_spatial.get("selected") or {}
    guard_current_values = {
        concept: str((guard_selected.get(concept) or {}).get("value") or "")
        for concept in EXPECTED_000736_CURRENT
    }
    guard_periods_ok = all(
        ((guard_selected.get(concept) or {}).get("period_evidence") or {}).get("matched") is True
        and ((guard_selected.get(concept) or {}).get("period_evidence") or {}).get("expected_economic_date") == "2024-12-31"
        for concept in EXPECTED_000736_CURRENT
    )
    guard_exact_current = guard_spatial.get("recovered") is True and guard_current_values == EXPECTED_000736_CURRENT
    guard_prior_not_selected = all(
        guard_current_values.get(concept) != forbidden
        for concept, forbidden in FORBIDDEN_000736_PRIOR.items()
    )
    recovered_shape_ok = recovered_ids == EXPECTED_RECOVERED_IDS
    diagnostic_pass = (
        not errors
        and recovered_shape_ok
        and guard_exact_current
        and guard_periods_ok
        and guard_prior_not_selected
    )

    report = {
        "gate": "S3G1J_V16_6_STATEMENT_PERIOD_SPATIAL_DIAGNOSTIC",
        "diagnostic_pass": diagnostic_pass,
        "sample_count": len(rows),
        "v16_recovered_count": len(recovered),
        "v16_recovered_ids": sorted(recovered_ids),
        "expected_recovered_ids": sorted(EXPECTED_RECOVERED_IDS),
        "recovered_shape_ok": recovered_shape_ok,
        "period_false_positive_guard": {
            "announcement_id": "1223096939",
            "source_code": "000736",
            "expected_economic_date": "2024-12-31",
            "must_recover_current_period": True,
            "expected_current_values": EXPECTED_000736_CURRENT,
            "actual_current_values": guard_current_values,
            "exact_current_values": guard_exact_current,
            "period_evidence_ok": guard_periods_ok,
            "forbidden_prior_values": FORBIDDEN_000736_PRIOR,
            "prior_values_not_selected": guard_prior_not_selected,
            "reason": "V16.5 initially selected a 2023-12-31 pre-restatement block; V16.6 must select only the 2024-12-31 current block",
        },
        "policy": {
            "diagnostic_only": True,
            "accepted_v14_parser_remains_unchanged": True,
            "native_pdf_words_only": True,
            "no_ocr": True,
            "formal_statement_titles_are_x_y_bound": True,
            "statement_local_standalone_units_only": True,
            "text_line_standalone_units_allowed_only_inside_locked_statement_segment": True,
            "candidate_statement_segment_must_contain_frozen_economic_date": True,
            "accounting_identity_is_not_sufficient_without_period_match": True,
            "extraction_typo_normalization": "合幵->合并 inside formal-title parser only",
            "alias_position_is_spatial_not_string_prefix": True,
            "accounting_identity_tolerance": "0.005",
        },
        "rows": rows,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if diagnostic_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
