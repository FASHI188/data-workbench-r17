#!/usr/bin/env python3
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import fitz

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v10 as v10
import stage3_financial_pdf_parser_v12 as v12
from stage3_financial_spatial_alias_v17_21 import diagnose_spatial_balance_sheet_v17_21

METHOD = "V17_21_EXACT_REVERSE_ADJACENT_ASSET_TOTAL_FINAL_FALLBACK"
EXPECTED_ASSET_ALIAS = "资产总计"
REVERSE_MIN_Y_DELTA = Decimal("5.50")
REVERSE_MAX_Y_DELTA = Decimal("6.25")
EXPECTED_AMOUNT_COLUMNS = 2
IDENTITY_TOLERANCE = Decimal("0.005")
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")


def _v17_21_balance_block(doc: fitz.Document, economic_date: str):
    diagnostic = diagnose_spatial_balance_sheet_v17_21(doc, economic_date)
    if not diagnostic.get("recovered"):
        return None, None

    selected = diagnostic.get("selected") or {}
    if set(selected) != set(CONCEPTS):
        return None, None

    assets = selected.get("TOTAL_ASSETS") or {}
    if str(assets.get("alias") or "") != EXPECTED_ASSET_ALIAS:
        return None, None
    if assets.get("reverse_adjacent_asset_total") is not True:
        return None, None
    try:
        reverse_delta = Decimal(str(assets.get("reverse_bridge_y_delta")))
    except (InvalidOperation, TypeError, ValueError):
        return None, None
    if not (REVERSE_MIN_Y_DELTA <= reverse_delta <= REVERSE_MAX_Y_DELTA):
        return None, None
    bridge_amounts = assets.get("bridge_amount_columns") or []
    if len(bridge_amounts) != EXPECTED_AMOUNT_COLUMNS:
        return None, None

    identity = diagnostic.get("identity") or {}
    try:
        identity_relative_error = Decimal(str(identity.get("identity_relative_error")))
    except (InvalidOperation, TypeError, ValueError):
        return None, None
    if identity_relative_error > IDENTITY_TOLERANCE:
        return None, None

    column_gate = diagnostic.get("column_role_gate") or {}
    if not column_gate.get("pass"):
        return None, None
    evidence = column_gate.get("concepts") or {}
    if not all(bool((evidence.get(concept) or {}).get("pass")) for concept in CONCEPTS):
        return None, None

    reverse_selected = sorted(
        concept
        for concept, candidate in selected.items()
        if candidate.get("reverse_adjacent_asset_total")
    )
    if reverse_selected != ["TOTAL_ASSETS"]:
        return None, None

    block: dict[str, base.Observation] = {}
    for concept in CONCEPTS:
        candidate = selected.get(concept)
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
            extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V17_21_EXACT_REVERSE_ADJACENT_ASSET_TOTAL",
            confidence="HIGH",
        )

    block["EQUITY_ATTRIBUTABLE_TO_PARENT"] = base.Observation(
        concept="EQUITY_ATTRIBUTABLE_TO_PARENT",
        status="NOT_FOUND",
        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V17_21_EXACT_REVERSE_ADJACENT_ASSET_TOTAL",
        confidence="NONE",
    )

    meta = {
        "start_page": min(int(selected[key]["statement_anchor_page"]) for key in selected),
        "unit": str(selected["TOTAL_ASSETS"].get("unit") or ""),
        "arbitration": "V17_21_GROUP_PERIOD_FROZEN_DATE_A_EQUALS_L_PLUS_E_EXACT_REVERSE_ASSET_TOTAL",
        "expected_economic_date": str(economic_date),
        "identity_tolerance": "0.005",
        "identity_relative_error": identity.get("identity_relative_error"),
        "identity_residual_cny": identity.get("identity_residual_cny"),
        "page_span": identity.get("page_span"),
        "anchor_span": identity.get("anchor_span"),
        "column_role_gate_pass": True,
        "selected_pages": {key: selected[key].get("page") for key in selected},
        "selected_aliases": {key: selected[key].get("alias") for key in selected},
        "selected_period_evidence": {key: selected[key].get("period_evidence") for key in selected},
        "column_role_evidence": evidence,
        "reverse_asset_total_selected_concepts": reverse_selected,
        "reverse_asset_total_alias": EXPECTED_ASSET_ALIAS,
        "reverse_asset_total_y_delta": str(reverse_delta),
        "reverse_asset_total_y_window": "5.50 <= delta <= 6.25",
        "reverse_asset_total_amount_column_count": len(bridge_amounts),
        "reverse_asset_total_numeric_row_text": str(assets.get("reverse_bridge_numeric_row_text") or ""),
        "e_equals_a_minus_l_inference": False,
        "global_row_tolerance_changed": False,
    }
    return block, meta


def _validated_balance_sheet_contextual(doc: fitz.Document, economic_date: str):
    # Preserve all accepted V14.1/V16.7/V17.15/V17.17 paths exactly. V17.21 is last.
    block, meta = v12._validated_balance_sheet_contextual(doc, economic_date)
    if block is not None:
        return block, meta
    return _v17_21_balance_block(doc, economic_date)


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
