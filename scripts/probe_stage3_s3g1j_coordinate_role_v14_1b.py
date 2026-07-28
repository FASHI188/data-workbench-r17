#!/usr/bin/env python3
from __future__ import annotations

import probe_stage3_s3g1j_coordinate_role_v14_1 as probe

# Bare `公司` is too broad for a column-role marker because issuer names and
# narrative headers can contain that token.  Only explicit parent/bank role
# headers are allowed to define the right-hand non-group column block.
probe.PARENT_HEADERS = ("本公司", "本行", "母公司")

if __name__ == "__main__":
    raise SystemExit(probe.main())
