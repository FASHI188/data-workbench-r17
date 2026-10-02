#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

import fitz

import stage3_financial_spatial_alias_v17_21 as v21

CONCEPTS = v21.CONCEPTS
CORRUPTED_EQUITY_ALIAS = "所有者权益（或d股东权益）合计"
CANONICAL_EQUITY_ALIAS = "所有者权益（或股东权益）合计"
EXACT_AMOUNT_COLUMNS = 2


def _is_exact_corrupted_equity_row(row_text: str) -> bool:
    normalized = v21.v14._norm(row_text or "")
    alias = v21.v14._norm(CORRUPTED_EQUITY_ALIAS)
    if not normalized.startswith(alias):
        return False
    if any(
        token in normalized
        for token in (
            v21.v14._norm("负债和"),
            v21.v14._norm("负债及"),
            v21.v14._norm("归属于"),
            v21.v14._norm("少数股东"),
        )
    ):
        return False
    return True


def _serialize(candidate: dict) -> dict:
    out = v21._serialize(candidate)
    out["strict_corrupted_equity_alias_v17_24"] = bool(
        candidate.get("strict_corrupted_equity_alias_v17_24")
    )
    if candidate.get("strict_corrupted_equity_alias_v17_24"):
        out["corrupted_equity_alias_normalized"] = str(
            candidate.get("corrupted_equity_alias_normalized") or ""
        )
        out["corrupted_equity_amount_columns"] = [
            {
                "raw": str(item["raw"]),
                "value": str(item["value"]),
                "x0": str(item["x0"]),
            }
            for item in candidate.get("corrupted_equity_amount_columns") or []
        ]
    return out


def _collect_exact_corrupted_equity_candidates(
    doc: fitz.Document,
    expected_economic_date: str,
) -> tuple[list[dict], dict]:
    events = v21.v17.blocks.formal_statement_events(doc)
    pages = v21.v14._candidate_pages(doc)
    candidates: list[dict] = []
    funnel = Counter()

    for pno in pages:
        rows = sorted(
            v21.v14._rows_from_words(doc[pno]),
            key=lambda row: float(row["y"]),
        )
        for row in rows:
            row_text = str(row.get("text") or "")
            if not _is_exact_corrupted_equity_row(row_text):
                continue
            funnel["exact_corrupted_equity_rows"] += 1
            geometries = v21.spatial._alias_geometries(
                row,
                CORRUPTED_EQUITY_ALIAS,
                "TOTAL_EQUITY",
            )
            if len(geometries) != 1:
                funnel["corrupted_alias_geometry_not_unique"] += 1
                continue
            geom = geometries[0]

            role_event = v21.v17.blocks.bind_alias_to_preceding_statement_event(
                events,
                pno + 1,
                float(row["y"]),
                float(geom["x0"]),
            )
            if role_event is None:
                funnel["without_formal_role"] += 1
                continue
            if role_event["role"] not in ("GROUP", "DUAL_GROUP_PARENT"):
                funnel["bound_parent"] += 1
                continue

            unit, multiplier, unit_evidence = v21.v17.blocks.role_local_unit_context(
                doc,
                events,
                role_event,
                pno + 1,
                float(row["y"]),
            )
            if unit is None or multiplier is None:
                funnel["without_unit"] += 1
                continue
            period_evidence = v21.v17.v166._statement_period_evidence(
                doc,
                role_event,
                unit_evidence,
                pno + 1,
                expected_economic_date,
            )
            if not period_evidence["matched"]:
                funnel["wrong_or_missing_period"] += 1
                continue

            amounts = v21.v17.v167._amounts_after_alias(
                row,
                float(geom["x1"]),
            )
            if len(amounts) != EXACT_AMOUNT_COLUMNS:
                funnel["amount_column_count_not_two"] += 1
                continue
            amount = amounts[0]
            value_cny = amount["value"] * multiplier
            if abs(value_cny) < Decimal("10000"):
                funnel["economically_tiny_amount"] += 1
                continue

            candidates.append(
                {
                    "concept": "TOTAL_EQUITY",
                    "value": value_cny,
                    "raw_value": str(amount["value"]),
                    "unit": unit,
                    "unit_multiplier": multiplier,
                    "unit_evidence": unit_evidence,
                    "period_evidence": period_evidence,
                    "page": pno + 1,
                    "alias": CORRUPTED_EQUITY_ALIAS,
                    "alias_strength": (
                        v21.v13._alias_strength(
                            "TOTAL_EQUITY",
                            CANONICAL_EQUITY_ALIAS,
                        )
                        + 3
                    ),
                    "alias_x0": geom["x0"],
                    "alias_x1": geom["x1"],
                    "value_x": amount["x0"],
                    "statement_anchor_page": role_event["page"],
                    "statement_anchor_y": role_event["y"],
                    "statement_anchor_x": role_event["x_center"],
                    "statement_role": role_event["role"],
                    "statement_title": role_event["matched_title"],
                    "statement_title_line": role_event["line"],
                    "row_text": row_text[:800],
                    "strict_corrupted_equity_alias_v17_24": True,
                    "corrupted_equity_alias_normalized": (
                        v21.v14._norm(CORRUPTED_EQUITY_ALIAS)
                    ),
                    "corrupted_equity_amount_columns": [
                        {
                            "raw": str(item["raw"]),
                            "value": item["value"],
                            "x0": item["x0"],
                        }
                        for item in amounts
                    ],
                }
            )
            funnel["strict_corrupted_equity_candidates"] += 1

    return candidates, dict(sorted(funnel.items()))


def diagnose_spatial_balance_sheet_v17_24(
    doc: fitz.Document,
    expected_economic_date: str,
) -> dict:
    existing, base_funnel = v21.v17.v166._collect_candidates_v16_6(
        doc, expected_economic_date
    )
    bridge, bridge_funnel = v21.v17.v1715._collect_adjacent_bridge_candidates(
        doc, expected_economic_date
    )
    strict_equity, strict_funnel = v21.v17._collect_strict_same_row_equity_candidates(
        doc, expected_economic_date
    )
    reverse_assets, reverse_funnel = v21._collect_reverse_asset_total_candidates(
        doc, expected_economic_date
    )
    corrupted_equity, corrupted_funnel = _collect_exact_corrupted_equity_candidates(
        doc, expected_economic_date
    )

    merged: dict[str, list[dict]] = defaultdict(list)
    for concept in CONCEPTS:
        merged[concept].extend(existing.get(concept, []))
        merged[concept].extend(bridge.get(concept, []))
    merged["TOTAL_EQUITY"].extend(strict_equity)
    merged["TOTAL_EQUITY"].extend(corrupted_equity)
    merged["TOTAL_ASSETS"].extend(reverse_assets)
    candidates = v21.v17.v1715._dedupe_candidates(merged)
    chosen, identity = v21.spatial._choose_spatial_identity(candidates)

    counts = {concept: len(candidates.get(concept, [])) for concept in CONCEPTS}
    corrupted_count = sum(
        bool(row.get("strict_corrupted_equity_alias_v17_24"))
        for row in candidates.get("TOTAL_EQUITY", [])
    )
    if chosen is None or not chosen.get("TOTAL_EQUITY", {}).get(
        "strict_corrupted_equity_alias_v17_24"
    ):
        return {
            "expected_economic_date": v21.v17.v166._canonical_economic_date(
                expected_economic_date
            ),
            "base_funnel": base_funnel,
            "bridge_funnel": bridge_funnel,
            "strict_equity_funnel": strict_funnel,
            "reverse_asset_funnel": reverse_funnel,
            "corrupted_equity_funnel": corrupted_funnel,
            "candidate_counts": counts,
            "corrupted_equity_candidate_count": corrupted_count,
            "identity_recovered_before_column_gate": False,
            "recovered": False,
            "identity": None,
            "column_role_gate": {
                "pass": False,
                "reason": (
                    "no A=L+E identity requiring the exact V17.24 corrupted "
                    "group-equity alias"
                ),
            },
            "selected": {},
        }

    direct = {
        concept: v21.v17._direct_column_evidence(
            doc,
            candidate,
            expected_economic_date,
        )
        for concept, candidate in chosen.items()
    }
    evidence = dict(direct)
    for concept, candidate in chosen.items():
        if direct[concept].get("pass"):
            continue
        sibling = v21.v17.v1715._trusted_sibling_evidence(
            doc,
            concept,
            candidate,
            chosen,
            direct,
        )
        if sibling is not None:
            evidence[concept] = sibling
    all_pass = all(
        bool((evidence.get(concept) or {}).get("pass"))
        for concept in CONCEPTS
    )

    return {
        "expected_economic_date": v21.v17.v166._canonical_economic_date(
            expected_economic_date
        ),
        "base_funnel": base_funnel,
        "bridge_funnel": bridge_funnel,
        "strict_equity_funnel": strict_funnel,
        "reverse_asset_funnel": reverse_funnel,
        "corrupted_equity_funnel": corrupted_funnel,
        "candidate_counts": counts,
        "corrupted_equity_candidate_count": corrupted_count,
        "identity_recovered_before_column_gate": True,
        "recovered": bool(all_pass),
        "identity": identity if all_pass else None,
        "column_role_gate": {
            "pass": all_pass,
            "concepts": evidence,
            "policy": (
                "exact normalized GROUP alias 所有者权益（或d股东权益）合计 only; "
                "same-row direct values; exactly two amount columns; direct or "
                "trusted frozen-date column evidence; A=L+E tolerance 0.005"
            ),
        },
        "selected": {
            concept: _serialize(candidate)
            for concept, candidate in (chosen.items() if all_pass else [])
        },
    }
