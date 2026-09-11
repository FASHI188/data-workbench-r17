#!/usr/bin/env python3
from __future__ import annotations

import finalize_stage3_filing_ledger as base

# Stage2 V3.2.25 adds the missing SSE predecessor identity 601313 and raises
# the 2015+ code-time universe from 3,401 to 3,402 identities. Keep the
# original finalizer logic unchanged and override only the frozen dependency.
base.EXPECTED_IDENTITIES = 3402

if __name__ == "__main__":
    raise SystemExit(base.main())
