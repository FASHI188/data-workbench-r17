#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import accept_stage3_s3g1j_v17_24_production as prior

# Preserve the accepted V17.21 row objects loaded by the production replay.  The
# original V17.24 validator correctly hardens new recoveries, but it also
# required a metadata key that older accepted blocks never emitted.  Previous
# recoveries are therefore validated by exact equality with their authoritative
# V17.21 blocks, not by retroactively requiring new metadata.
_BASELINE_ROWS: dict[str, dict] = {}
_ORIGINAL_LOAD = prior._load_v17_21
_ORIGINAL_VALIDATE = prior._validate_recovery


def _load_v17_21(root: Path) -> tuple[dict[str, dict], set[str]]:
    rows, recovered = _ORIGINAL_LOAD(root)
    _BASELINE_ROWS.clear()
    _BASELINE_ROWS.update(rows)
    return rows, recovered


def _validate_recovery(aid: str, parsed: dict) -> None:
    if aid not in prior.PREVIOUS_RECOVERIES:
        # New V17.24 recoveries must continue to satisfy every explicit V17.24
        # hard gate, including direct equity evidence and the explicit no-
        # inference marker.
        _ORIGINAL_VALIDATE(aid, parsed)
        return

    if not prior._validated(parsed):
        raise ValueError(f"previous accepted recovery did not validate {aid}")

    current_block = parsed.get("balance_sheet_block")
    baseline_row = _BASELINE_ROWS.get(aid)
    baseline_block = (
        baseline_row.get("balance_sheet_block")
        if isinstance(baseline_row, dict)
        else None
    )
    if not isinstance(current_block, dict) or not isinstance(baseline_block, dict):
        raise ValueError(f"missing authoritative V17.21 baseline block {aid}")
    if current_block != baseline_block:
        raise ValueError(f"previous accepted balance-sheet block changed {aid}")

    # A legacy block may omit this later-added provenance field.  If the field
    # is present, however, it must still explicitly prohibit E=A-L inference.
    if (
        "e_equals_a_minus_l_inference" in current_block
        and current_block["e_equals_a_minus_l_inference"] is not False
    ):
        raise ValueError(f"E=A-L inference enabled {aid}")


def main() -> int:
    original_load = prior._load_v17_21
    original_validate = prior._validate_recovery
    prior._load_v17_21 = _load_v17_21
    prior._validate_recovery = _validate_recovery
    try:
        return prior.main()
    finally:
        prior._load_v17_21 = original_load
        prior._validate_recovery = original_validate


if __name__ == "__main__":
    raise SystemExit(main())
