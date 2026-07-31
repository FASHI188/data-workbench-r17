#!/usr/bin/env python3
from __future__ import annotations

import extract_stage3_financial_pdf_values_v12 as prior
from stage3_financial_pdf_parser_v13 import parse_pdf_bytes as v17_21_parse_pdf_bytes

base = prior.base
METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V13_V17_21_EXACT_REVERSE_ADJACENT_ASSET_TOTAL_FINAL_FALLBACK"
METHODOLOGY_VERSION = "V3.3.3-V17.21"

# Re-export deterministic formal-shard helpers from the accepted V17.17 driver.
sha_file = prior.sha_file
write_deterministic_csv_gz = prior.write_deterministic_csv_gz
slim_evidence = prior.slim_evidence


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    parsed = dict(v17_21_parse_pdf_bytes(raw, economic_date))
    parsed["declared_a_share_codes"] = prior.v15.v14.v9.declared_a_share_codes(raw)
    return parsed


def main() -> int:
    original_parse = prior.parse_pdf_bytes
    original_method = prior.METHOD
    original_methodology = prior.METHODOLOGY_VERSION
    prior.parse_pdf_bytes = parse_pdf_bytes
    prior.METHOD = METHOD
    prior.METHODOLOGY_VERSION = METHODOLOGY_VERSION
    try:
        return prior.main()
    finally:
        prior.parse_pdf_bytes = original_parse
        prior.METHOD = original_method
        prior.METHODOLOGY_VERSION = original_methodology


if __name__ == "__main__":
    raise SystemExit(main())
