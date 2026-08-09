#!/usr/bin/env python3
from __future__ import annotations

import build_stage3_s3g1j_v17_29_candidate_full as builder
import stage3_financial_pdf_parser_v21_candidate_v2 as candidate

# Preserve the accepted builder/non-regression implementation and replace only
# the candidate parser revision. The target population is identical in V1/V2.
# Expose read-only geometry helpers so the V1 builder's failure diagnostics
# remain available if any exact source still fails.
for _name in ("_rows_by_page", "_amount_pair", "_normalize", "_bind"):
    setattr(candidate, _name, getattr(candidate.base, _name))

builder.candidate = candidate

if __name__ == "__main__":
    raise SystemExit(builder.main())
