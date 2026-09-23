#!/usr/bin/env python3
from __future__ import annotations

import fitz

import stage3_financial_pdf_parser_v10 as v10
import stage3_financial_pdf_parser_v13 as v13
import stage3_financial_pdf_parser_v14 as candidate

METHOD = "V17_24_EXACT_CORRUPTED_GROUP_EQUITY_ALIAS_FINAL_FALLBACK"


def _v17_24_production_balance_block(
    doc: fitz.Document,
    economic_date: str,
):
    block, meta = candidate._v17_24_balance_block(doc, economic_date)
    if block is None:
        return None, None
    promoted = dict(meta or {})
    promoted["candidate_only"] = False
    promoted["production_runtime_generation"] = "V17.24"
    return block, promoted


def _validated_balance_sheet_contextual(
    doc: fitz.Document,
    economic_date: str,
):
    # Preserve every accepted V17.21 and earlier production path exactly.
    block, meta = v13._validated_balance_sheet_contextual(doc, economic_date)
    if block is not None:
        return block, meta
    return _v17_24_production_balance_block(doc, economic_date)


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    original = v10.v2._validated_balance_sheet

    def contextual(doc: fitz.Document):
        return _validated_balance_sheet_contextual(doc, economic_date)

    v10.v2._validated_balance_sheet = contextual
    try:
        with v10._mupdf_diagnostic_guard():
            parsed = dict(v10.v13.parse_pdf_bytes(raw))
    finally:
        v10.v2._validated_balance_sheet = original
    parsed["parser_version"] = METHOD
    return parsed
