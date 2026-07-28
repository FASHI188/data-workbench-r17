#!/usr/bin/env python3
from __future__ import annotations

import probe_stage3_s3g1j_parser_grammar_v11 as probe
from stage3_financial_pdf_parser_v8 import parse_pdf_bytes

probe.parse_pdf_bytes = parse_pdf_bytes

if __name__ == "__main__":
    raise SystemExit(probe.main())
