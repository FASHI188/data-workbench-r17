#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict

import fitz

import stage3_financial_spatial_alias_v17_24 as accepted
import stage3_financial_statement_blocks_v17_25 as generic_blocks

CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
TARGET_ALIASES = {
    "TOTAL_ASSETS": "资产总计",
    "TOTAL_LIABILITIES": "负债合计",
    "TOTAL_EQUITY": "所有者权益合计",
}


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
        all_pass = all(
            bool((evidence.get(concept) or {}).get("pass"))
            for concept in CONCEPTS
        )
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
            "recovered": bool(all_pass),
            "identity": identity,
            "column_role_gate": {
                "pass": bool(all_pass),
                "concepts": evidence,
                "policy": (
                    "exact source allowlist outside this module; exact GROUP generic "
                    "witness; aliases 资产总计/负债合计/所有者权益合计; direct or "
                    "trusted frozen-date column evidence; A=L+E tolerance 0.005"
                ),
            },
            "selected": {
                concept: accepted._serialize(candidate)
                for concept, candidate in chosen.items()
            },
        }
    finally:
        accepted.v21.v17.blocks.formal_statement_events = original
