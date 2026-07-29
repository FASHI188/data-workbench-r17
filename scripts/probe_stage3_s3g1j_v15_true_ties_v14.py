#!/usr/bin/env python3
from __future__ import annotations

import probe_stage3_s3g1j_v15_true_ties as probe
import extract_stage3_financial_pdf_values_v9 as v14

# Keep the exact frozen true-tie sample and current resolver policy; only replace
# the per-candidate parser with accepted V14.1. This isolates parser-driven tie
# recovery from any resolver-policy relaxation.
probe.ext.parse_pdf_bytes = v14.parse_pdf_bytes

if __name__ == "__main__":
    raise SystemExit(probe.main())
