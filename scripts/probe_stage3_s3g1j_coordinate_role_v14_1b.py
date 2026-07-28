#!/usr/bin/env python3
from __future__ import annotations

import probe_stage3_s3g1j_coordinate_role_v14_1 as probe

# Bare `公司` / `集团` are too broad for numeric-column role markers because
# issuer names and narrative headers can contain those tokens.  Only explicit
# role labels are allowed to split a dual group-parent/bank statement.
probe.GROUP_HEADERS = ("本集团",)
probe.PARENT_HEADERS = ("本公司", "本行", "母公司")

if __name__ == "__main__":
    raise SystemExit(probe.main())
