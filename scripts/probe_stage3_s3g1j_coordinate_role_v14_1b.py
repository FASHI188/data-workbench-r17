#!/usr/bin/env python3
from __future__ import annotations

import probe_stage3_s3g1j_coordinate_role_v14_1 as _base

# Bare `公司` / `集团` are too broad for numeric-column role markers because
# issuer names and narrative headers can contain those tokens. Only explicit
# role labels are allowed to split a dual group-parent/bank statement.
_base.GROUP_HEADERS = ("本集团",)
_base.PARENT_HEADERS = ("本公司", "本行", "母公司")

# Re-export the role-gate contract explicitly. V14.1c decorates this layer, so
# downstream code must not depend on the private name of the wrapped module.
GROUP_HEADERS = _base.GROUP_HEADERS
PARENT_HEADERS = _base.PARENT_HEADERS
SPECIAL_SCOPE_PREFIXES = _base.SPECIAL_SCOPE_PREFIXES
_row_scope_ok = _base._row_scope_ok
_column_role = _base._column_role
_qualify = _base._qualify
main = _base.main

if __name__ == "__main__":
    raise SystemExit(main())
