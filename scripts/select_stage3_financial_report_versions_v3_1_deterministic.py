#!/usr/bin/env python3
from __future__ import annotations

import select_stage3_financial_report_versions_v3 as v3
import select_stage3_financial_report_versions_v3_1 as v31  # installs V3.1 title policy on v3
from stage3_deterministic_gzip import deterministic_gzip_open

# Deterministic clean-integration selector. Historical S3G1G run remains
# untouched until a new refreeze passes the same-input reproducibility gate.
v3.gzip.open = deterministic_gzip_open

if __name__ == "__main__":
    raise SystemExit(v3.main())
