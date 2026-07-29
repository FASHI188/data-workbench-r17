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
from stage3_financial_spatial_alias_v16_3 import diagnose_spatial_balance_sheet_v16_3

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
    "1223096939",  # 000736 annual 2024
}


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def download(session: requests.Session, url: str) -> tuple[bytes, str]:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V16.3-statement-block-diagnostic",
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
            spatial = diagnose_spatial_balance_sheet_v16_3(doc)
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
    report = {
        "gate": "S3G1J_V16_3_STATEMENT_BLOCK_SPATIAL_DIAGNOSTIC",
        "diagnostic_pass": not errors,
        "sample_count": len(rows),
        "v16_recovered_count": len(recovered),
        "v16_recovered_ids": [row["announcement_id"] for row in recovered],
        "policy": {
            "diagnostic_only": True,
            "accepted_v14_parser_remains_unchanged": True,
            "native_pdf_words_only": True,
            "no_ocr": True,
            "formal_statement_titles_are_x_y_bound": True,
            "statement_local_standalone_units_only": True,
            "extraction_typo_normalization": "合幵->合并 inside formal-title parser only",
            "alias_position_is_spatial_not_string_prefix": True,
            "first_valid_amount_to_alias_right_is_current_column_candidate": True,
            "accounting_identity_tolerance": "0.005",
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
    raise SystemExit(main())
