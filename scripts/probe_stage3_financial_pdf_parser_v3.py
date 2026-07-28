#!/usr/bin/env python3
from __future__ import annotations

import probe_stage3_financial_pdf_parser_v2 as probe
from stage3_financial_pdf_parser_v3 import parse_pdf_bytes

# Reuse the exact locked official PDF expectations while substituting only the
# V5 document parser.  The probe's source URLs, SHA evidence and tolerances stay
# unchanged.
probe.parse_pdf_bytes = parse_pdf_bytes


if __name__ == "__main__":
    raise SystemExit(probe.main())
