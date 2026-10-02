#!/usr/bin/env python3
from __future__ import annotations

import finalize_stage3_filing_ledger as base
from stage3_deterministic_gzip import deterministic_gzip_open

# Deterministic clean-integration refreeze. Historical S3G1E run/entrypoint
# remains untouched until this new path passes reproducibility acceptance.
base.EXPECTED_IDENTITIES = 3402
base.gzip.open = deterministic_gzip_open

if __name__ == "__main__":
    raise SystemExit(base.main())
