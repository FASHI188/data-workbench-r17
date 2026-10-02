#!/usr/bin/env python3
from __future__ import annotations

from contextlib import contextmanager

import fitz

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v2 as v2
import stage3_financial_pdf_parser_v8 as v13
import stage3_financial_pdf_parser_v9 as v14
from stage3_financial_spatial_alias_v16_7 import diagnose_spatial_balance_sheet_v16_7

METHOD = "V16_7_CONTEXTUAL_PERIOD_COLUMN_FALLBACK"


@contextmanager
def _mupdf_diagnostic_guard():
    """Bound MuPDF diagnostic growth without changing extraction semantics.

    Some official PDFs contain recoverable broken xref references. MuPDF can still
    extract their text, but every access may append megabytes of repeated errors to
    its process-global diagnostics store. V14/V16 intentionally revisit pages from
    several independent evidence paths, so an unbounded store can turn a valid
    fail-closed parse into a multi-minute resource failure.

    The guard changes diagnostics only: text/search calls are identical, and the
    prior PyMuPDF display settings and Page methods are restored even on exception.
    The parser already installs a process-global V2 hook for the duration of one
    parse, so this remains within the same single-parse critical section.
    """
    tools = fitz.TOOLS
    prior_errors = tools.mupdf_display_errors()
    prior_warnings = tools.mupdf_display_warnings()
    original_get_text = fitz.Page.get_text
    original_search_for = fitz.Page.search_for

    def guarded_get_text(page, *args, **kwargs):
        try:
            return original_get_text(page, *args, **kwargs)
        finally:
            tools.reset_mupdf_warnings()

    def guarded_search_for(page, *args, **kwargs):
        try:
            return original_search_for(page, *args, **kwargs)
        finally:
            tools.reset_mupdf_warnings()

    tools.mupdf_display_errors(False)
    tools.mupdf_display_warnings(False)
    tools.reset_mupdf_warnings()
    fitz.Page.get_text = guarded_get_text
    fitz.Page.search_for = guarded_search_for
    try:
        yield
    finally:
        fitz.Page.get_text = original_get_text
        fitz.Page.search_for = original_search_for
        tools.reset_mupdf_warnings()
        tools.mupdf_display_errors(prior_errors)
        tools.mupdf_display_warnings(prior_warnings)


def _v16_7_balance_block(doc: fitz.Document, economic_date: str):
    diagnostic = diagnose_spatial_balance_sheet_v16_7(doc, economic_date)
    if not diagnostic.get("recovered"):
        return None, None

    selected = diagnostic.get("selected") or {}
    block: dict[str, base.Observation] = {}
    for concept in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"):
        candidate = selected.get(concept)
        if not candidate:
            return None, None
        unit = str(candidate.get("unit") or "")
        multiplier = base.UNIT_MULTIPLIERS.get(unit)
        if multiplier is None:
            return None, None
        block[concept] = base.Observation(
            concept=concept,
            status="FOUND",
            raw_value=str(candidate.get("raw_value") or ""),
            normalized_cny_value=str(candidate.get("value") or ""),
            unit=unit,
            unit_multiplier=str(multiplier),
            page=int(candidate.get("page") or 0) or None,
            matched_alias=str(candidate.get("alias") or ""),
            extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V16_7_PERIOD_COLUMN_GATE",
            confidence="HIGH",
        )

    block["EQUITY_ATTRIBUTABLE_TO_PARENT"] = base.Observation(
        concept="EQUITY_ATTRIBUTABLE_TO_PARENT",
        status="NOT_FOUND",
        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V16_7_PERIOD_COLUMN_GATE",
        confidence="NONE",
    )

    identity = diagnostic.get("identity") or {}
    column_gate = diagnostic.get("column_role_gate") or {}
    meta = {
        "start_page": min(int(selected[k]["statement_anchor_page"]) for k in selected),
        "unit": str(selected["TOTAL_ASSETS"].get("unit") or ""),
        "arbitration": "V16_7_GROUP_PERIOD_FROZEN_DATE_COLUMN_A_EQUALS_L_PLUS_E",
        "expected_economic_date": str(economic_date),
        "identity_tolerance": "0.005",
        "identity_relative_error": identity.get("identity_relative_error"),
        "identity_residual_cny": identity.get("identity_residual_cny"),
        "page_span": identity.get("page_span"),
        "anchor_span": identity.get("anchor_span"),
        "column_role_gate_pass": bool(column_gate.get("pass")),
        "selected_pages": {k: selected[k].get("page") for k in selected},
        "selected_aliases": {k: selected[k].get("alias") for k in selected},
        "selected_period_evidence": {k: selected[k].get("period_evidence") for k in selected},
        "column_role_evidence": column_gate.get("concepts") or {},
    }
    return block, meta


def _validated_balance_sheet_contextual(doc: fitz.Document, economic_date: str):
    # Preserve V14.1 exactly when it already succeeds. V16.7 is a strict fallback.
    block, meta = v14._validated_balance_sheet_v14(doc)
    if block is not None:
        return block, meta
    return _v16_7_balance_block(doc, economic_date)


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    """Parse one PDF with a frozen report economic date supplied by the version ledger.

    V11/V13 resolve ``v2._validated_balance_sheet`` dynamically. Install a local
    contextual hook for this single parse, then restore the previous hook in a
    ``finally`` block. This preserves the audited parser chain while preventing
    date context from leaking into another document.
    """
    original = v2._validated_balance_sheet

    def contextual(doc: fitz.Document):
        return _validated_balance_sheet_contextual(doc, economic_date)

    v2._validated_balance_sheet = contextual
    try:
        with _mupdf_diagnostic_guard():
            parsed = dict(v13.parse_pdf_bytes(raw))
    finally:
        v2._validated_balance_sheet = original
    return parsed
