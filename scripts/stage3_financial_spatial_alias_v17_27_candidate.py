#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation

import fitz

import stage3_financial_spatial_alias_v17_24 as accepted
import stage3_financial_statement_blocks_v17_25 as generic_blocks

CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
TARGET_ALIASES = {
    "TOTAL_ASSETS": "资产总计",
    "TOTAL_LIABILITIES": "负债合计",
    "TOTAL_EQUITY": "所有者权益合计",
}
IDENTITY_TOLERANCE = accepted.v21.spatial.IDENTITY_TOLERANCE
MAX_COLUMN_X_SPREAD = Decimal("2.0")
MIN_COLUMN_SEPARATION = Decimal("40.0")
EXACT_AMOUNT_COLUMNS = 2
DUAL_COLUMN_SOURCE = "V17_27_EXACT_SOURCE_DUAL_COLUMN_BALANCE_IDENTITIES"


def _collect_candidates(
    doc: fitz.Document, expected_economic_date: str
) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    existing, base_funnel = accepted.v21.v17.v166._collect_candidates_v16_6(
        doc, expected_economic_date
    )
    bridge, bridge_funnel = accepted.v21.v17.v1715._collect_adjacent_bridge_candidates(
        doc, expected_economic_date
    )
    strict_equity, strict_funnel = (
        accepted.v21.v17._collect_strict_same_row_equity_candidates(
            doc, expected_economic_date
        )
    )
    reverse_assets, reverse_funnel = (
        accepted.v21._collect_reverse_asset_total_candidates(
            doc, expected_economic_date
        )
    )
    corrupted_equity, corrupted_funnel = (
        accepted._collect_exact_corrupted_equity_candidates(
            doc, expected_economic_date
        )
    )

    merged: dict[str, list[dict]] = defaultdict(list)
    for concept in CONCEPTS:
        merged[concept].extend(existing.get(concept, []))
        merged[concept].extend(bridge.get(concept, []))
    merged["TOTAL_EQUITY"].extend(strict_equity)
    merged["TOTAL_EQUITY"].extend(corrupted_equity)
    merged["TOTAL_ASSETS"].extend(reverse_assets)
    candidates = accepted.v21.v17.v1715._dedupe_candidates(merged)

    filtered: dict[str, list[dict]] = {concept: [] for concept in CONCEPTS}
    for concept in CONCEPTS:
        for row in candidates.get(concept, []):
            if str(row.get("alias") or "") != TARGET_ALIASES[concept]:
                continue
            if concept == "TOTAL_EQUITY" and row.get(
                "strict_corrupted_equity_alias_v17_24"
            ):
                continue
            filtered[concept].append(row)

    return filtered, {
        "base_funnel": base_funnel,
        "bridge_funnel": bridge_funnel,
        "strict_equity_funnel": strict_funnel,
        "reverse_asset_funnel": reverse_funnel,
        "corrupted_equity_funnel": corrupted_funnel,
    }


def _candidate_row_amounts(doc: fitz.Document, candidate: dict) -> dict:
    page_1b = int(candidate["page"])
    rows = accepted.v21.v14._rows_from_words(doc[page_1b - 1])
    expected_text = accepted.v21.v14._norm(str(candidate.get("row_text") or ""))
    matches = [
        row
        for row in rows
        if accepted.v21.v14._norm(str(row.get("text") or "")) == expected_text
    ]
    if len(matches) != 1:
        return {
            "pass": False,
            "reason": "candidate source row is not unique on its page",
            "page": page_1b,
            "row_match_count": len(matches),
        }
    row = matches[0]
    amounts = accepted.v21.v17.v167._amounts_after_alias(
        row, float(candidate["alias_x1"])
    )
    if len(amounts) != EXACT_AMOUNT_COLUMNS:
        return {
            "pass": False,
            "reason": "candidate row does not contain exactly two amount columns",
            "page": page_1b,
            "row_text": str(row.get("text") or "")[:800],
            "amount_column_count": len(amounts),
        }
    try:
        selected_raw = Decimal(str(candidate.get("raw_value")))
    except (InvalidOperation, TypeError, ValueError):
        return {"pass": False, "reason": "candidate raw value is not decimal"}
    if amounts[0]["value"] != selected_raw:
        return {
            "pass": False,
            "reason": "selected value is not the first amount column",
            "selected_raw_value": str(selected_raw),
            "first_amount_value": str(amounts[0]["value"]),
        }
    return {
        "pass": True,
        "page": page_1b,
        "row_y": float(row["y"]),
        "row_text": str(row.get("text") or "")[:800],
        "amounts": [
            {
                "raw": str(amount["raw"]),
                "value": str(amount["value"]),
                "x0": str(amount["x0"]),
            }
            for amount in amounts
        ],
        "first_amount_selected": True,
    }


def _relative_error(assets: Decimal, liabilities: Decimal, equity: Decimal) -> Decimal:
    return abs(assets - (liabilities + equity)) / max(
        abs(assets), abs(liabilities + equity), Decimal("1")
    )


def _dual_column_identity_evidence(
    doc: fitz.Document,
    selected: dict[str, dict],
    expected_economic_date: str,
) -> dict:
    if set(selected) != set(CONCEPTS):
        return {"pass": False, "reason": "selected A/L/E concept set changed"}
    units = {str(selected[concept].get("unit") or "") for concept in CONCEPTS}
    multipliers = {
        str(selected[concept].get("unit_multiplier") or "") for concept in CONCEPTS
    }
    roles = {str(selected[concept].get("statement_role") or "") for concept in CONCEPTS}
    anchors = {int(selected[concept].get("statement_anchor_page") or 0) for concept in CONCEPTS}
    if len(units) != 1 or "" in units:
        return {"pass": False, "reason": "selected candidates do not share one explicit unit"}
    if len(multipliers) != 1 or "" in multipliers:
        return {"pass": False, "reason": "selected candidates do not share one unit multiplier"}
    if not roles.issubset({"GROUP", "DUAL_GROUP_PARENT"}) or not roles:
        return {"pass": False, "reason": "selected candidates are not GROUP role"}
    if len(anchors) != 1:
        return {"pass": False, "reason": "selected candidates do not share one statement anchor"}
    for concept in CONCEPTS:
        period = selected[concept].get("period_evidence") or {}
        if period.get("matched") is not True:
            return {"pass": False, "reason": f"period evidence failed for {concept}"}
        if period.get("expected_economic_date") != expected_economic_date:
            return {"pass": False, "reason": f"period target changed for {concept}"}

    columns = {
        concept: _candidate_row_amounts(doc, selected[concept]) for concept in CONCEPTS
    }
    if not all(columns[concept].get("pass") is True for concept in CONCEPTS):
        return {
            "pass": False,
            "reason": "one or more candidate rows failed exact two-column extraction",
            "concepts": columns,
        }

    first_values = {
        concept: Decimal(columns[concept]["amounts"][0]["value"])
        for concept in CONCEPTS
    }
    second_values = {
        concept: Decimal(columns[concept]["amounts"][1]["value"])
        for concept in CONCEPTS
    }
    first_x = {
        concept: Decimal(columns[concept]["amounts"][0]["x0"])
        for concept in CONCEPTS
    }
    second_x = {
        concept: Decimal(columns[concept]["amounts"][1]["x0"])
        for concept in CONCEPTS
    }
    first_spread = max(first_x.values()) - min(first_x.values())
    second_spread = max(second_x.values()) - min(second_x.values())
    separations = {
        concept: second_x[concept] - first_x[concept] for concept in CONCEPTS
    }
    current_residual = first_values["TOTAL_ASSETS"] - (
        first_values["TOTAL_LIABILITIES"] + first_values["TOTAL_EQUITY"]
    )
    prior_residual = second_values["TOTAL_ASSETS"] - (
        second_values["TOTAL_LIABILITIES"] + second_values["TOTAL_EQUITY"]
    )
    current_relative = _relative_error(
        first_values["TOTAL_ASSETS"],
        first_values["TOTAL_LIABILITIES"],
        first_values["TOTAL_EQUITY"],
    )
    prior_relative = _relative_error(
        second_values["TOTAL_ASSETS"],
        second_values["TOTAL_LIABILITIES"],
        second_values["TOTAL_EQUITY"],
    )
    pass_gate = (
        first_spread <= MAX_COLUMN_X_SPREAD
        and second_spread <= MAX_COLUMN_X_SPREAD
        and all(value >= MIN_COLUMN_SEPARATION for value in separations.values())
        and current_relative <= IDENTITY_TOLERANCE
        and prior_relative <= IDENTITY_TOLERANCE
    )
    return {
        "pass": bool(pass_gate),
        "reason": None if pass_gate else "dual-column structural identity gate failed",
        "evidence_source": DUAL_COLUMN_SOURCE,
        "expected_economic_date": expected_economic_date,
        "statement_role": sorted(roles),
        "statement_anchor_pages": sorted(anchors),
        "unit": sorted(units)[0],
        "unit_multiplier": sorted(multipliers)[0],
        "exact_amount_columns": EXACT_AMOUNT_COLUMNS,
        "first_column_selected": True,
        "first_column_values": {key: str(value) for key, value in first_values.items()},
        "second_column_values": {key: str(value) for key, value in second_values.items()},
        "first_column_x": {key: str(value) for key, value in first_x.items()},
        "second_column_x": {key: str(value) for key, value in second_x.items()},
        "first_column_x_spread": str(first_spread),
        "second_column_x_spread": str(second_spread),
        "max_column_x_spread": str(MAX_COLUMN_X_SPREAD),
        "column_separations": {key: str(value) for key, value in separations.items()},
        "minimum_column_separation": str(MIN_COLUMN_SEPARATION),
        "current_identity_residual": str(current_residual),
        "current_identity_relative_error": str(current_relative),
        "prior_identity_residual": str(prior_residual),
        "prior_identity_relative_error": str(prior_relative),
        "identity_tolerance": str(IDENTITY_TOLERANCE),
        "concepts": columns,
    }


def diagnose_normal_equity_identity_candidate(
    doc: fitz.Document, expected_economic_date: str
) -> dict:
    original = accepted.v21.v17.blocks.formal_statement_events
    accepted.v21.v17.blocks.formal_statement_events = (
        generic_blocks.formal_statement_events
    )
    try:
        witness = generic_blocks.diagnose_generic_group_witness(doc)
        candidates, funnels = _collect_candidates(doc, expected_economic_date)
        chosen, identity = accepted.v21.spatial._choose_spatial_identity(candidates)
        counts = {
            concept: len(candidates.get(concept, [])) for concept in CONCEPTS
        }
        if chosen is None:
            return {
                "expected_economic_date": (
                    accepted.v21.v17.v166._canonical_economic_date(
                        expected_economic_date
                    )
                ),
                **funnels,
                "candidate_counts": counts,
                "generic_group_witness": witness,
                "identity_recovered_before_column_gate": False,
                "recovered": False,
                "identity": None,
                "column_role_gate": {
                    "pass": False,
                    "reason": "no exact normal-equity A=L+E identity",
                },
                "selected": {},
            }

        direct = {
            concept: accepted.v21.v17._direct_column_evidence(
                doc, candidate, expected_economic_date
            )
            for concept, candidate in chosen.items()
        }
        evidence = dict(direct)
        for concept, candidate in chosen.items():
            if direct[concept].get("pass"):
                continue
            sibling = accepted.v21.v17.v1715._trusted_sibling_evidence(
                doc, concept, candidate, chosen, direct
            )
            if sibling is not None:
                evidence[concept] = sibling
        direct_all_pass = all(
            bool((evidence.get(concept) or {}).get("pass"))
            for concept in CONCEPTS
        )
        dual = _dual_column_identity_evidence(
            doc, chosen, expected_economic_date
        )
        all_pass = bool(direct_all_pass or dual.get("pass"))
        if dual.get("pass"):
            evidence = {
                concept: {
                    "pass": True,
                    "evidence_source": DUAL_COLUMN_SOURCE,
                    "concept_column": dual["concepts"][concept],
                    "prior_direct_failure": direct[concept],
                }
                for concept in CONCEPTS
            }
        return {
            "expected_economic_date": (
                accepted.v21.v17.v166._canonical_economic_date(
                    expected_economic_date
                )
            ),
            **funnels,
            "candidate_counts": counts,
            "generic_group_witness": witness,
            "identity_recovered_before_column_gate": True,
            "recovered": all_pass,
            "identity": identity,
            "column_role_gate": {
                "pass": all_pass,
                "concepts": evidence,
                "direct_or_sibling_pass": direct_all_pass,
                "dual_column_identity_evidence": dual,
                "policy": (
                    "exact source allowlist outside this module; exact GROUP generic "
                    "witness; aliases 资产总计/负债合计/所有者权益合计; either existing "
                    "direct/sibling frozen-date header evidence or exact two aligned "
                    "amount columns whose current and prior columns independently satisfy "
                    "A=L+E within tolerance 0.005"
                ),
            },
            "selected": {
                concept: accepted._serialize(candidate)
                for concept, candidate in chosen.items()
            },
        }
    finally:
        accepted.v21.v17.blocks.formal_statement_events = original
