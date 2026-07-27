#!/usr/bin/env python3
from __future__ import annotations

import build_stage3_capco_industry_ledger as base
from stage3_capco_discovery import discover_publications

base.discover_publications = discover_publications

if __name__ == "__main__":
    raise SystemExit(base.main())
