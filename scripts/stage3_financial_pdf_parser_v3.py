#!/usr/bin/env python3
from __future__ import annotations

from decimal import Decimal

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v2 as v2

NO_VALIDATED_BALANCE_BLOCK = "NO_VALIDATED_BALANCE_SHEET_BLOCK"


def _looks_like_note_index(raw: str, value: Decimal) -> bool:
    return (
        "," not in raw
        and "." not in raw
        and not raw.startswith("(")
        and Decimal("0") <= value <= Decimal("300")
    )


def _numeric_tokens_after_alias_preserve_columns(combined: str, alias: str) -> list[tuple[str, Decimal]]:
    """V5 row parser: preserve year columns and never accept a lone note index.

    PyMuPDF frequently emits a statement row as separate text lines:
    label -> note index -> current-period amount -> prior-period amount.
    V4 could inspect the width-2 window first and return the note index as the
    amount before a wider window exposed the real numeric columns.  When the
    only token looks like a note index we deliberately return no value so the
    caller continues widening the row window.
    """
    m = v2._alias_regex(alias)
    match = m.search(combined)
    if not match:
        return []
    tail = combined[match.end():]
    out: list[tuple[str, Decimal]] = []
    for nm in base.NUMBER_RE.finditer(tail):
        value = base.parse_num(nm.group(0))
        if value is not None:
            out.append((nm.group(0), value))
    if not out:
        return []
    raw0, value0 = out[0]
    if _looks_like_note_index(raw0, value0):
        if len(out) == 1:
            return []
        out = out[1:]
    return out


# V2 resolves balance metrics through this module-global function at runtime.
# Patch only that row-token primitive; all V4 block discovery, unit locking and
# A=L+E validation remain unchanged.
v2._numeric_tokens_after_alias_preserve_columns = _numeric_tokens_after_alias_preserve_columns


def _enforce_validated_balance_block(result: dict) -> dict:
    out = dict(result)
    errors = list(out.get("validation_errors") or [])
    if not out.get("balance_sheet_block") and NO_VALIDATED_BALANCE_BLOCK not in errors:
        errors.insert(0, NO_VALIDATED_BALANCE_BLOCK)
    out["validation_errors"] = errors
    return out


def parse_pdf_bytes(raw: bytes) -> dict:
    # The V5 contract is stronger than V4: fallback observations remain useful
    # diagnostics, but a document can never become training truth unless the
    # joint balance-sheet block itself was found and passed the accounting gate.
    return _enforce_validated_balance_block(v2.parse_pdf_bytes(raw))
