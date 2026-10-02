#!/usr/bin/env python3
from __future__ import annotations

import fitz

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v10 as v10
from stage3_financial_spatial_alias_v17_15 import diagnose_spatial_balance_sheet_v17_15

METHOD = "V17_15_STRICT_ADJACENT_ROW_FINAL_FALLBACK"


def _v17_15_balance_block(doc: fitz.Document, economic_date: str):
    diagnostic = diagnose_spatial_balance_sheet_v17_15(doc, economic_date)
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
            extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V17_15_STRICT_ADJACENT_ROW_COLUMN_GATE",
            confidence="HIGH",
        )

    block["EQUITY_ATTRIBUTABLE_TO_PARENT"] = base.Observation(
        concept="EQUITY_ATTRIBUTABLE_TO_PARENT",
        status="NOT_FOUND",
        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V17_15_STRICT_ADJACENT_ROW_COLUMN_GATE",
        confidence="NONE",
    )

    identity = diagnostic.get("identity") or {}
    column_gate = diagnostic.get("column_role_gate") or {}
    bridge_selected = sorted(
        concept for concept, candidate in selected.items()
        if candidate.get("adjacent_row_bridge")
    )
    if not bridge_selected:
        return None, None
    meta = {
        "start_page": min(int(selected[key]["statement_anchor_page"]) for key in selected),
        "unit": str(selected["TOTAL_ASSETS"].get("unit") or ""),
        "arbitration": "V17_15_GROUP_PERIOD_FROZEN_DATE_COLUMN_A_EQUALS_L_PLUS_E_STRICT_ADJACENT_ROW",
        "expected_economic_date": str(economic_date),
        "identity_tolerance": "0.005",
        "identity_relative_error": identity.get("identity_relative_error"),
        "identity_residual_cny": identity.get("identity_residual_cny"),
        "page_span": identity.get("page_span"),
        "anchor_span": identity.get("anchor_span"),
        "column_role_gate_pass": bool(column_gate.get("pass")),
        "selected_pages": {key: selected[key].get("page") for key in selected},
        "selected_aliases": {key: selected[key].get("alias") for key in selected},
        "selected_period_evidence": {key: selected[key].get("period_evidence") for key in selected},
        "column_role_evidence": column_gate.get("concepts") or {},
        "adjacent_row_bridge_selected_concepts": bridge_selected,
        "adjacent_row_bridge_y_window": "2.8 < delta <= 3.25",
        "global_row_tolerance_changed": False,
    }
    return block, meta


def _validated_balance_sheet_contextual(doc: fitz.Document, economic_date: str):
    # Preserve V14.1 and V16.7 exactly. V17.15 runs only after both fail closed.
    block, meta = v10._validated_balance_sheet_contextual(doc, economic_date)
    if block is not None:
        return block, meta
    return _v17_15_balance_block(doc, economic_date)


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
    return parsed
