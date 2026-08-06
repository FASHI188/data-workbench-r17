#!/usr/bin/env python3
from __future__ import annotations

import extract_stage3_financial_pdf_values_v2  # noqa: F401
import extract_stage3_financial_pdf_values as base
from stage3_financial_pdf_parser_v5 import parse_pdf_bytes

base.parse_pdf_bytes = parse_pdf_bytes
base.METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V5_BALANCE_TITLE_V8"

if __name__ == "__main__":
    raise SystemExit(base.main())
