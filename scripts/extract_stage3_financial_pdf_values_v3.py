#!/usr/bin/env python3
from __future__ import annotations

# Load the audited V2 candidate resolver first, then replace only the document
# parser used by the extraction loop with the V5 fail-closed balance-block
# parser.  This keeps tie/issuer/provenance policy unchanged during diagnosis.
import extract_stage3_financial_pdf_values_v2  # noqa: F401
import extract_stage3_financial_pdf_values as base
from stage3_financial_pdf_parser_v3 import parse_pdf_bytes

base.parse_pdf_bytes = parse_pdf_bytes
base.METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V3_BALANCE_BLOCK"


if __name__ == "__main__":
    raise SystemExit(base.main())
