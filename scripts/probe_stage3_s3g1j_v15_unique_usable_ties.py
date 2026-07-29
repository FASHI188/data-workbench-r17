#!/usr/bin/env python3
from __future__ import annotations

import probe_stage3_s3g1j_v15_true_ties as probe
import extract_stage3_financial_pdf_values_v10 as v15

# Keep the exact frozen 41 true same-moment ties and issuer gate. Replace only
# candidate parsing with accepted V14.1 and the final tie resolver with V15.
probe.ext.parse_pdf_bytes = v15.v14.parse_pdf_bytes
probe.ext.v9.base.resolve_candidates = v15.resolve_candidates

if __name__ == "__main__":
    raise SystemExit(probe.main())
