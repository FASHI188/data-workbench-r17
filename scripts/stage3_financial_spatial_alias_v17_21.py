#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

import fitz

import stage3_financial_pdf_parser_v8 as v13
import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16 as spatial
import stage3_financial_spatial_alias_v17_17 as v17

CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
EXACT_ASSET_LABEL = "资产总计"
REVERSE_MIN_Y_DELTA = Decimal("5.50")
REVERSE_MAX_Y_DELTA = Decimal("6.25")
EXACT_AMOUNT_COLUMNS = 2


def _serialize(candidate: dict) -> dict:
    out = v17._serialize(candidate)
    out["reverse_adjacent_asset_total"] = bool(candidate.get("reverse_adjacent_asset_total"))
    if candidate.get("reverse_adjacent_asset_total"):
        out["reverse_bridge_y_delta"] = str(candidate.get("reverse_bridge_y_delta"))
        out["reverse_bridge_numeric_row_text"] = str(candidate.get("bridge_numeric_row_text") or "")
    return out


def _collect_reverse_asset_total_candidates(
    doc: fitz.Document,
    expected_economic_date: str,
) -> tuple[list[dict], dict]:
    events = v17.blocks.formal_statement_events(doc)
    pages = v14._candidate_pages(doc)
    candidates: list[dict] = []
    funnel = Counter()

    for pno in pages:
        rows = sorted(v14._rows_from_words(doc[pno]), key=lambda row: float(row["y"]))
        for row_index, row in enumerate(rows):
            if v14._norm(str(row.get("text") or "")) != v14._norm(EXACT_ASSET_LABEL):
                continue
            funnel["exact_asset_total_rows"] += 1
            geometries = spatial._alias_geometries(row, EXACT_ASSET_LABEL, "TOTAL_ASSETS")
            if len(geometries) != 1:
                funnel["asset_total_alias_geometry_not_unique"] += 1
                continue
            geom = geometries[0]
            if spatial._first_amount_after_alias(row, geom) is not None:
                funnel["same_row_amount_present"] += 1
                continue
            if row_index == 0:
                funnel["no_preceding_row"] += 1
                continue

            role_event = v17.blocks.bind_alias_to_preceding_statement_event(
                events, pno + 1, float(row["y"]), float(geom["x0"])
            )
            if role_event is None:
                funnel["without_formal_role"] += 1
                continue
            if role_event["role"] not in ("GROUP", "DUAL_GROUP_PARENT"):
                funnel["bound_parent"] += 1
                continue

            unit, multiplier, unit_evidence = v17.blocks.role_local_unit_context(
                doc, events, role_event, pno + 1, float(row["y"])
            )
            if unit is None or multiplier is None:
                funnel["without_unit"] += 1
                continue
            period_evidence = v17.v166._statement_period_evidence(
                doc, role_event, unit_evidence, pno + 1, expected_economic_date
            )
            if not period_evidence["matched"]:
                funnel["wrong_or_missing_period"] += 1
                continue

            numeric_row = rows[row_index - 1]
            delta = Decimal(str(float(row["y"]) - float(numeric_row["y"])))
            if not (REVERSE_MIN_Y_DELTA <= delta <= REVERSE_MAX_Y_DELTA):
                funnel["reverse_y_delta_outside_window"] += 1
                continue
            if not v17.v1715._strict_numeric_only_row(numeric_row):
                funnel["preceding_row_not_numeric_only"] += 1
                continue
            amounts = v17.v167._amounts_after_alias(numeric_row, float(geom["x1"]))
            if len(amounts) != EXACT_AMOUNT_COLUMNS:
                funnel["preceding_amount_column_count_not_two"] += 1
                continue

            amount = amounts[0]
            value_cny = amount["value"] * multiplier
            if abs(value_cny) < Decimal("10000"):
                funnel["economically_tiny_amount"] += 1
                continue
            candidates.append(
                {
                    "concept": "TOTAL_ASSETS",
                    "value": value_cny,
                    "raw_value": str(amount["value"]),
                    "unit": unit,
                    "unit_multiplier": multiplier,
                    "unit_evidence": unit_evidence,
                    "period_evidence": period_evidence,
                    "page": pno + 1,
                    "alias": EXACT_ASSET_LABEL,
                    "alias_strength": v13._alias_strength("TOTAL_ASSETS", EXACT_ASSET_LABEL) + 2,
                    "alias_x0": geom["x0"],
                    "alias_x1": geom["x1"],
                    "value_x": amount["x0"],
                    "statement_anchor_page": role_event["page"],
                    "statement_anchor_y": role_event["y"],
                    "statement_anchor_x": role_event["x_center"],
                    "statement_role": role_event["role"],
                    "statement_title": role_event["matched_title"],
                    "statement_title_line": role_event["line"],
                    "row_text": str(row.get("text") or "")[:800],
                    "adjacent_row_bridge": True,
                    "reverse_adjacent_asset_total": True,
                    "bridge_y_delta": str(delta),
                    "reverse_bridge_y_delta": str(delta),
                    "bridge_numeric_row_text": str(numeric_row.get("text") or "")[:800],
                    "bridge_amount_columns": [
                        {
                            "raw": str(item["raw"]),
                            "value": item["value"],
                            "x0": item["x0"],
                        }
                        for item in amounts
                    ],
                }
            )
            funnel["strict_reverse_asset_total_candidates"] += 1

    return candidates, dict(sorted(funnel.items()))


def diagnose_spatial_balance_sheet_v17_21(
    doc: fitz.Document,
    expected_economic_date: str,
) -> dict:
    existing, base_funnel = v17.v166._collect_candidates_v16_6(doc, expected_economic_date)
    bridge, bridge_funnel = v17.v1715._collect_adjacent_bridge_candidates(doc, expected_economic_date)
    strict_equity, strict_funnel = v17._collect_strict_same_row_equity_candidates(doc, expected_economic_date)
    reverse_assets, reverse_funnel = _collect_reverse_asset_total_candidates(doc, expected_economic_date)

    merged: dict[str, list[dict]] = defaultdict(list)
    for concept in CONCEPTS:
        merged[concept].extend(existing.get(concept, []))
        merged[concept].extend(bridge.get(concept, []))
    merged["TOTAL_EQUITY"].extend(strict_equity)
    merged["TOTAL_ASSETS"].extend(reverse_assets)
    candidates = v17.v1715._dedupe_candidates(merged)
    chosen, identity = spatial._choose_spatial_identity(candidates)

    counts = {concept: len(candidates.get(concept, [])) for concept in CONCEPTS}
    reverse_count = sum(
        bool(row.get("reverse_adjacent_asset_total"))
        for row in candidates.get("TOTAL_ASSETS", [])
    )
    if chosen is None or not chosen.get("TOTAL_ASSETS", {}).get("reverse_adjacent_asset_total"):
        return {
            "expected_economic_date": v17.v166._canonical_economic_date(expected_economic_date),
            "base_funnel": base_funnel,
            "bridge_funnel": bridge_funnel,
            "strict_equity_funnel": strict_funnel,
            "reverse_asset_funnel": reverse_funnel,
            "candidate_counts": counts,
            "reverse_asset_candidate_count": reverse_count,
            "identity_recovered_before_column_gate": False,
            "recovered": False,
            "identity": None,
            "column_role_gate": {"pass": False, "reason": "no A=L+E identity requiring exact reverse asset-total candidate"},
            "selected": {},
        }

    direct = {
        concept: v17._direct_column_evidence(doc, candidate, expected_economic_date)
        for concept, candidate in chosen.items()
    }
    evidence = dict(direct)
    for concept, candidate in chosen.items():
        if direct[concept].get("pass"):
            continue
        sibling = v17.v1715._trusted_sibling_evidence(doc, concept, candidate, chosen, direct)
        if sibling is not None:
            evidence[concept] = sibling
    all_pass = all(bool((evidence.get(concept) or {}).get("pass")) for concept in CONCEPTS)

    return {
        "expected_economic_date": v17.v166._canonical_economic_date(expected_economic_date),
        "base_funnel": base_funnel,
        "bridge_funnel": bridge_funnel,
        "strict_equity_funnel": strict_funnel,
        "reverse_asset_funnel": reverse_funnel,
        "candidate_counts": counts,
        "reverse_asset_candidate_count": reverse_count,
        "identity_recovered_before_column_gate": True,
        "recovered": bool(all_pass),
        "identity": identity if all_pass else None,
        "column_role_gate": {
            "pass": all_pass,
            "concepts": evidence,
            "policy": (
                "exact GROUP label 资产总计; immediately preceding numeric-only row; "
                "5.50 <= reverse delta <= 6.25; exactly two amount columns; "
                "direct or trusted frozen-date column evidence; A=L+E tolerance 0.005"
            ),
        },
        "selected": {
            concept: _serialize(candidate)
            for concept, candidate in (chosen.items() if all_pass else [])
        },
    }
