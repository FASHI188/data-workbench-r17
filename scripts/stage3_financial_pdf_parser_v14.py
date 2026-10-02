#!/usr/bin/env python3
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import fitz

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v10 as v10
import stage3_financial_pdf_parser_v13 as v13
from stage3_financial_spatial_alias_v17_24 import (
    CORRUPTED_EQUITY_ALIAS,
    diagnose_spatial_balance_sheet_v17_24,
)

METHOD = "V17_24_EXACT_CORRUPTED_GROUP_EQUITY_ALIAS_CANDIDATE"
IDENTITY_TOLERANCE = Decimal("0.005")
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
EXPECTED_AMOUNT_COLUMNS = 2


def _v17_24_balance_block(doc: fitz.Document, economic_date: str):
    diagnostic = diagnose_spatial_balance_sheet_v17_24(doc, economic_date)
    if not diagnostic.get("recovered"):
        return None, None

    selected = diagnostic.get("selected") or {}
    if set(selected) != set(CONCEPTS):
        return None, None
    equity = selected.get("TOTAL_EQUITY") or {}
    if equity.get("strict_corrupted_equity_alias_v17_24") is not True:
        return None, None
    if str(equity.get("alias") or "") != CORRUPTED_EQUITY_ALIAS:
        return None, None
    if str(equity.get("corrupted_equity_alias_normalized") or "") != (
        CORRUPTED_EQUITY_ALIAS
    ):
        return None, None
    amount_columns = equity.get("corrupted_equity_amount_columns") or []
    if len(amount_columns) != EXPECTED_AMOUNT_COLUMNS:
        return None, None

    identity = diagnostic.get("identity") or {}
    try:
        relative = Decimal(str(identity.get("identity_relative_error")))
    except (InvalidOperation, TypeError, ValueError):
        return None, None
    if relative > IDENTITY_TOLERANCE:
        return None, None

    column_gate = diagnostic.get("column_role_gate") or {}
    evidence = column_gate.get("concepts") or {}
    if not column_gate.get("pass"):
        return None, None
    if not all(
        bool((evidence.get(concept) or {}).get("pass"))
        for concept in CONCEPTS
    ):
        return None, None

    corrupted_selected = sorted(
        concept
        for concept, candidate in selected.items()
        if candidate.get("strict_corrupted_equity_alias_v17_24")
    )
    if corrupted_selected != ["TOTAL_EQUITY"]:
        return None, None

    block: dict[str, base.Observation] = {}
    for concept in CONCEPTS:
        candidate = selected.get(concept) or {}
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
            extraction_scope=(
                "VALIDATED_BALANCE_SHEET_BLOCK_V17_24_"
                "EXACT_CORRUPTED_GROUP_EQUITY_ALIAS_CANDIDATE"
            ),
            confidence="HIGH",
        )

    block["EQUITY_ATTRIBUTABLE_TO_PARENT"] = base.Observation(
        concept="EQUITY_ATTRIBUTABLE_TO_PARENT",
        status="NOT_FOUND",
        extraction_scope=(
            "VALIDATED_BALANCE_SHEET_BLOCK_V17_24_"
            "EXACT_CORRUPTED_GROUP_EQUITY_ALIAS_CANDIDATE"
        ),
        confidence="NONE",
    )

    meta = {
        "start_page": min(
            int(selected[key]["statement_anchor_page"])
            for key in selected
        ),
        "unit": str(selected["TOTAL_ASSETS"].get("unit") or ""),
        "arbitration": (
            "V17_24_GROUP_PERIOD_FROZEN_DATE_A_EQUALS_L_PLUS_E_"
            "EXACT_CORRUPTED_EQUITY_ALIAS"
        ),
        "expected_economic_date": str(economic_date),
        "identity_tolerance": "0.005",
        "identity_relative_error": identity.get("identity_relative_error"),
        "identity_residual_cny": identity.get("identity_residual_cny"),
        "page_span": identity.get("page_span"),
        "anchor_span": identity.get("anchor_span"),
        "column_role_gate_pass": True,
        "selected_pages": {
            key: selected[key].get("page") for key in selected
        },
        "selected_aliases": {
            key: selected[key].get("alias") for key in selected
        },
        "selected_period_evidence": {
            key: selected[key].get("period_evidence") for key in selected
        },
        "column_role_evidence": evidence,
        "corrupted_equity_selected_concepts": corrupted_selected,
        "corrupted_equity_alias": CORRUPTED_EQUITY_ALIAS,
        "corrupted_equity_amount_column_count": len(amount_columns),
        "corrupted_equity_row_text": str(equity.get("row_text") or ""),
        "candidate_only": True,
        "e_equals_a_minus_l_inference": False,
        "global_row_tolerance_changed": False,
    }
    return block, meta


def _validated_balance_sheet_contextual(
    doc: fitz.Document,
    economic_date: str,
):
    # Preserve all accepted production paths exactly. V17.24 is candidate-only
    # and runs only when V17.21 and every earlier path remain fail-closed.
    block, meta = v13._validated_balance_sheet_contextual(doc, economic_date)
    if block is not None:
        return block, meta
    return _v17_24_balance_block(doc, economic_date)


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
