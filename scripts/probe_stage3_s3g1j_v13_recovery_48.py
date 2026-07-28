#!/usr/bin/env python3
from __future__ import annotations

import probe_stage3_s3g1j_v12_recovery_48 as probe
from extract_stage3_financial_pdf_values_v8 import parse_pdf_bytes

probe.parse_pdf_bytes = parse_pdf_bytes

if __name__ == "__main__":
    raise SystemExit(probe.main())
