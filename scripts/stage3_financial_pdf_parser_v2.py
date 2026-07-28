#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation

import fitz

import stage3_financial_pdf_parser as base

# Concepts whose primary-statement rows are robustly distinguishable from
# summary/narrative rows across the locked sample set.  OPERATING_REVENUE is
# intentionally NOT forced through this path: older bank filings can expose
# other rows containing “营业收入” in the statement-search window while the
# early key-financial-data table contains the correct consolidated top line.
# The original guarded summary parser already resolves the bank/non-bank locked
# samples correctly.  Non-recurring profit likewise remains summary-only.
STATEMENT_PRIORITY = (
    "NET_PROFIT_ATTRIBUTABLE_TO_PARENT",
    "NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES",
    "TOTAL_ASSETS",
    "EQUITY_ATTRIBUTABLE_TO_PARENT",
)


def _d(v: str | None) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _balance_sheet_identity_error(obs: dict[str, base.Observation]) -> str | None:
    a = _d(obs.get("TOTAL_ASSETS").normalized_cny_value if obs.get("TOTAL_ASSETS") else None)
    l = _d(obs.get("TOTAL_LIABILITIES").normalized_cny_value if obs.get("TOTAL_LIABILITIES") else None)
    e = _d(obs.get("TOTAL_EQUITY").normalized_cny_value if obs.get("TOTAL_EQUITY") else None)
    if a is None or l is None or e is None:
        return None
    denom = max(abs(a), abs(l + e), Decimal("1"))
    rel = abs(a - (l + e)) / denom
    # Allow ordinary report-unit rounding, but not 1,000x/10,000x unit mistakes.
    if rel > Decimal("0.005"):
        return f"BALANCE_SHEET_IDENTITY_MISMATCH assets={a} liabilities={l} equity={e} rel={rel}"
    return None


def parse_pdf_bytes(raw: bytes) -> dict:
    doc = fitz.open(stream=raw, filetype="pdf")
    first_pages = list(range(0, min(doc.page_count, 20)))
    obs: dict[str, base.Observation] = {}

    # First collect early-summary observations.  This remains authoritative for
    # OPERATING_REVENUE and non-recurring profit unless a future separately
    # validated top-line statement detector is introduced.
    for concept, aliases in base.TIER1_ALIASES.items():
        obs[concept] = base.find_metric_in_pages(
            doc, first_pages, aliases, concept, "EARLY_REPORT_SUMMARY"
        )

    statement_pages = base.candidate_statement_pages(doc)

    # Re-read only the concepts whose statement-level semantics are locked by
    # the official sample set and accounting controls.
    for concept in STATEMENT_PRIORITY:
        stmt = base.find_metric_in_pages(
            doc,
            statement_pages,
            base.TIER1_ALIASES[concept],
            concept,
            "PRIMARY_FINANCIAL_STATEMENT",
        )
        if stmt.status == "FOUND":
            obs[concept] = stmt

    for concept, aliases in base.TIER2_ALIASES.items():
        obs[concept] = base.find_metric_in_pages(
            doc, statement_pages, aliases, concept, "PRIMARY_FINANCIAL_STATEMENT"
        )

    # Keep the old guarded fallback for rare filings whose parent-equity/asset
    # line is outside the first statement search window.
    if obs["EQUITY_ATTRIBUTABLE_TO_PARENT"].status != "FOUND":
        obs["EQUITY_ATTRIBUTABLE_TO_PARENT"] = base.find_metric_in_pages(
            doc,
            statement_pages,
            base.TIER1_ALIASES["EQUITY_ATTRIBUTABLE_TO_PARENT"],
            "EQUITY_ATTRIBUTABLE_TO_PARENT",
            "STATEMENT_FALLBACK",
        )
    if obs["TOTAL_ASSETS"].status != "FOUND":
        obs["TOTAL_ASSETS"] = base.find_metric_in_pages(
            doc,
            statement_pages,
            base.TIER1_ALIASES["TOTAL_ASSETS"],
            "TOTAL_ASSETS",
            "STATEMENT_FALLBACK",
        )

    validation_errors: list[str] = []
    identity_error = _balance_sheet_identity_error(obs)
    if identity_error:
        validation_errors.append(identity_error)

    tier1_found = sum(obs[k].status == "FOUND" for k in base.TIER1_ALIASES)
    tier2_found = sum(obs[k].status == "FOUND" for k in base.TIER2_ALIASES)
    return {
        "page_count": doc.page_count,
        "tier1_found": tier1_found,
        "tier1_total": len(base.TIER1_ALIASES),
        "tier2_found": tier2_found,
        "tier2_total": len(base.TIER2_ALIASES),
        "validation_errors": validation_errors,
        "observations": {k: asdict(v) for k, v in obs.items()},
    }
