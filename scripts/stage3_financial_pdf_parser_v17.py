#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
from decimal import Decimal

import fitz

import stage3_financial_pdf_parser_v15 as accepted
import stage3_financial_pdf_parser_v16 as candidate
import stage3_financial_statement_blocks_v17_25 as candidate_blocks

METHOD = "V17_25_EXACT_SOURCE_GENERIC_GROUP_WITNESS_PRODUCTION"
TARGET_SOURCE_SHA256 = "320e3a950a4768e73766d57a09bcf34d893d4da949b8ed5a1b2f887852e76229"
TARGET_ECONOMIC_DATE = "2019-09-30"
TARGET_GENERIC_TITLE = "1、资产负债表"
TARGET_WITNESS_AMOUNTS = ["584008978.27", "526240949.34"]
TARGET_SELECTED_PAGES = {
    "TOTAL_ASSETS": 8,
    "TOTAL_LIABILITIES": 9,
    "TOTAL_EQUITY": 9,
}
TARGET_SELECTED_ALIASES = {
    "TOTAL_ASSETS": "资产总计",
    "TOTAL_LIABILITIES": "负债合计",
    "TOTAL_EQUITY": "所有者权益合计",
}
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")


def _recovered(parsed: dict) -> bool:
    observations = parsed.get("observations") or {}
    return (
        all(
            (observations.get(concept) or {}).get("status") == "FOUND"
            for concept in CONCEPTS
        )
        and isinstance(parsed.get("balance_sheet_block"), dict)
        and not list(parsed.get("validation_errors") or [])
    )


def _exact_witness(raw: bytes) -> dict:
    with fitz.open(stream=raw, filetype="pdf") as doc:
        diagnostic = candidate_blocks.diagnose_generic_group_witness(doc)
    if int(diagnostic.get("promoted_generic_group_count", -1)) != 1:
        raise ValueError("exact V17.25 production source did not expose one GROUP witness")
    events = diagnostic.get("promoted_events") or []
    if len(events) != 1:
        raise ValueError("exact V17.25 production witness event count changed")
    event = events[0]
    witness = event.get("witness") or {}
    if event.get("line") != TARGET_GENERIC_TITLE or event.get("role") != "GROUP":
        raise ValueError("exact V17.25 generic title/role changed")
    if witness.get("witness_alias") != candidate_blocks.GROUP_WITNESS_ALIAS:
        raise ValueError("exact V17.25 group witness alias changed")
    if witness.get("total_equity_alias") != candidate_blocks.TOTAL_EQUITY_ALIAS:
        raise ValueError("exact V17.25 total equity alias changed")
    if list(witness.get("witness_amounts") or []) != TARGET_WITNESS_AMOUNTS:
        raise ValueError("exact V17.25 witness amounts changed")
    if list(witness.get("total_equity_amounts") or []) != TARGET_WITNESS_AMOUNTS:
        raise ValueError("exact V17.25 total equity amounts changed")
    if witness.get("same_page") is not True or witness.get("amounts_equal") is not True:
        raise ValueError("exact V17.25 witness equality gate changed")
    if int(witness.get("amount_column_count", -1)) != 2:
        raise ValueError("exact V17.25 witness amount-column count changed")
    return copy.deepcopy(witness)


def _validate_candidate_block(block: dict) -> None:
    if block.get("identity_tolerance") != "0.005":
        raise ValueError("V17.25 accounting tolerance changed")
    if Decimal(str(block.get("identity_relative_error"))) != Decimal("0"):
        raise ValueError("V17.25 exact-source identity error is not zero")
    if Decimal(str(block.get("identity_residual_cny"))) != Decimal("0"):
        raise ValueError("V17.25 exact-source identity residual is not zero")
    if block.get("column_role_gate_pass") is not True:
        raise ValueError("V17.25 exact-source column-role gate did not pass")
    if block.get("selected_pages") != TARGET_SELECTED_PAGES:
        raise ValueError("V17.25 exact-source selected pages changed")
    if block.get("selected_aliases") != TARGET_SELECTED_ALIASES:
        raise ValueError("V17.25 exact-source selected aliases changed")
    period = block.get("selected_period_evidence") or {}
    if set(period) != set(CONCEPTS):
        raise ValueError("V17.25 exact-source period evidence incomplete")
    for concept in CONCEPTS:
        evidence = period[concept]
        if evidence.get("expected_economic_date") != TARGET_ECONOMIC_DATE:
            raise ValueError(f"V17.25 period target changed {concept}")
        if evidence.get("matched") is not True:
            raise ValueError(f"V17.25 period evidence failed {concept}")


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    """Promote one source-locked V17.25 recovery and preserve V17.24 elsewhere.

    The production extension is intentionally exact-source bounded. Every PDF
    outside the accepted source SHA returns the V17.24 result object unchanged.
    This prevents a generic title rule from expanding production authority to
    unreviewed documents during the later 64-shard replay.
    """
    current = dict(accepted.parse_pdf_bytes(raw, economic_date))
    digest = hashlib.sha256(raw).hexdigest()
    if digest != TARGET_SOURCE_SHA256 or economic_date != TARGET_ECONOMIC_DATE:
        return current
    if _recovered(current):
        raise ValueError("V17.24 unexpectedly recovered the V17.25 exact source")

    proposed = dict(candidate.parse_pdf_bytes(raw, economic_date))
    if not _recovered(proposed):
        raise ValueError("V17.25 exact-source candidate did not recover")
    witness = _exact_witness(raw)
    block = copy.deepcopy(proposed.get("balance_sheet_block") or {})
    _validate_candidate_block(block)

    block["arbitration"] = (
        "V17_25_EXACT_SOURCE_GENERIC_GROUP_WITNESS_A_EQUALS_L_PLUS_E"
    )
    block["candidate_only"] = False
    block["production_runtime_generation"] = "V17.25"
    block["exact_source_sha256"] = TARGET_SOURCE_SHA256
    block["generic_group_witness"] = witness
    block["global_row_tolerance_changed"] = False
    block["e_equals_a_minus_l_inference"] = False

    out = copy.deepcopy(proposed)
    out["parser_version"] = METHOD
    out["balance_sheet_block"] = block
    out["validation_errors"] = []
    return out
