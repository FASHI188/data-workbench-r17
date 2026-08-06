#!/usr/bin/env python3
from __future__ import annotations

import fitz

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v10 as v10
import stage3_financial_pdf_parser_v11 as v11
from stage3_financial_spatial_alias_v17_17 import diagnose_spatial_balance_sheet_v17_17

METHOD = "V17_17_STRICT_TOTAL_EQUITY_PAIRED_HEADER_FINAL_FALLBACK"
EXPECTED_HEADER_SOURCE = "V17_17_STRICT_THREE_COLUMN_TWO_ROW_YEAR_MONTH_DAY_HEADER"
EXPECTED_EQUITY_ALIAS = "股东权益总计"


def _v17_17_balance_block(doc: fitz.Document, economic_date: str):
    diagnostic = diagnose_spatial_balance_sheet_v17_17(doc, economic_date)
    if not diagnostic.get("recovered"):
        return None, None

    selected = diagnostic.get("selected") or {}
    column_gate = diagnostic.get("column_role_gate") or {}
    if not column_gate.get("pass"):
        return None, None
    evidence = column_gate.get("concepts") or {}

    strict_selected = sorted(
        concept for concept, candidate in selected.items()
        if candidate.get("strict_same_row_equity_total")
    )
    if strict_selected != ["TOTAL_EQUITY"]:
        return None, None
    if str((selected.get("TOTAL_EQUITY") or {}).get("alias") or "") != EXPECTED_EQUITY_ALIAS:
        return None, None

    for concept in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"):
        concept_evidence = evidence.get(concept) or {}
        if not concept_evidence.get("pass"):
            return None, None
        if concept_evidence.get("evidence_source") != EXPECTED_HEADER_SOURCE:
            return None, None
        header = concept_evidence.get("header") or {}
        if header.get("structural_source") != EXPECTED_HEADER_SOURCE:
            return None, None
        dates = header.get("dates") or []
        if len(dates) != 3 or int(header.get("expected_column_index", -1)) != 0:
            return None, None
        if str(header.get("expected_date") or "") != str(economic_date):
            return None, None

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
            extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V17_17_STRICT_TOTAL_EQUITY_PAIRED_HEADER_COLUMN_GATE",
            confidence="HIGH",
        )

    block["EQUITY_ATTRIBUTABLE_TO_PARENT"] = base.Observation(
        concept="EQUITY_ATTRIBUTABLE_TO_PARENT",
        status="NOT_FOUND",
        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V17_17_STRICT_TOTAL_EQUITY_PAIRED_HEADER_COLUMN_GATE",
        confidence="NONE",
    )

    identity = diagnostic.get("identity") or {}
    bridge_selected = sorted(
        concept for concept, candidate in selected.items()
        if candidate.get("adjacent_row_bridge")
    )
    if bridge_selected != ["TOTAL_ASSETS", "TOTAL_LIABILITIES"]:
        return None, None

    meta = {
        "start_page": min(int(selected[key]["statement_anchor_page"]) for key in selected),
        "unit": str(selected["TOTAL_ASSETS"].get("unit") or ""),
        "arbitration": "V17_17_GROUP_PERIOD_STRICT_PAIRED_HEADER_A_EQUALS_L_PLUS_E_EXPLICIT_TOTAL_EQUITY",
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
        "adjacent_row_bridge_selected_concepts": bridge_selected,
        "strict_total_equity_selected_concepts": strict_selected,
        "strict_total_equity_alias": EXPECTED_EQUITY_ALIAS,
        "paired_header_evidence_source": EXPECTED_HEADER_SOURCE,
        "paired_header_expected_column_index": 0,
        "paired_header_column_count": 3,
        "e_equals_a_minus_l_inference": False,
        "global_row_tolerance_changed": False,
    }
    return block, meta


def _validated_balance_sheet_contextual(doc: fitz.Document, economic_date: str):
    # Preserve all accepted V14.1/V16.7/V17.15 paths exactly. V17.17 is last.
    block, meta = v11._validated_balance_sheet_contextual(doc, economic_date)
    if block is not None:
        return block, meta
    return _v17_17_balance_block(doc, economic_date)


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
