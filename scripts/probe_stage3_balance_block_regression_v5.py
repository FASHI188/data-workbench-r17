#!/usr/bin/env python3
from __future__ import annotations

import probe_stage3_balance_block_regression_v4 as probe
from stage3_financial_pdf_parser_v3 import parse_pdf_bytes

# Keep the exact twelve V4 old-format samples and accounting threshold.  Only
# swap the parser so the V5 hardening is measured against the same evidence.
probe.parse_pdf_bytes = parse_pdf_bytes


if __name__ == "__main__":
    raise SystemExit(probe.main())
