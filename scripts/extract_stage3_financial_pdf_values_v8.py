#!/usr/bin/env python3
from __future__ import annotations

import extract_stage3_financial_pdf_values_v6 as v9
from stage3_financial_pdf_parser_v8 import parse_pdf_bytes as v13_parse_pdf_bytes

METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V8_IDENTITY_ARBITRATION"


def parse_pdf_bytes(raw: bytes) -> dict:
    parsed = dict(v13_parse_pdf_bytes(raw))
    parsed["declared_a_share_codes"] = v9.declared_a_share_codes(raw)
    return parsed


v9.base.parse_pdf_bytes = parse_pdf_bytes
v9.base.filter_candidates_by_issuer = v9.filter_candidates_by_issuer
v9.base.resolve_candidates = v9.resolve_candidates
v9.base.METHOD = METHOD


if __name__ == "__main__":
    raise SystemExit(v9.base.main())
