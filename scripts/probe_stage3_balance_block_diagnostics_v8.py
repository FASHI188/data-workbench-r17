#!/usr/bin/env python3
from __future__ import annotations

import probe_stage3_balance_block_diagnostics_v5 as probe
from stage3_financial_pdf_parser_v5 import parse_pdf_bytes

probe.parse_pdf_bytes = parse_pdf_bytes

if __name__ == "__main__":
    raise SystemExit(probe.main())
