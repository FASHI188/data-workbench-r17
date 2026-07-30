#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

import fitz

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_pdf_parser_v8 as v13
import stage3_financial_spatial_alias_v16 as spatial
import stage3_financial_spatial_alias_v16_3 as v166
import stage3_financial_spatial_alias_v16_7 as v167
import stage3_financial_spatial_alias_v17_15 as v1715
import stage3_financial_statement_blocks_v16_5 as blocks

CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
STRICT_EQUITY_LABEL = "股东权益总计"


def _norm(value: str) -> str:
    return v14._norm(value or "")


def _is_exact_strict_equity_row(row_text: str) -> bool:
    normalized = _norm(row_text)
    label = _norm(STRICT_EQUITY_LABEL)
    if not normalized.startswith(label):
        return False
    if any(token in normalized for token in (_norm("归属于"), _norm("少数股东"), _norm("负债和"), _norm("负债及"))):
        return False
    return True


def _collect_strict_same_row_equity_candidates(
    doc: fitz.Document,
    expected_economic_date: str,
) -> tuple[list[dict], dict]:
    events = blocks.formal_statement_events(doc)
    pages = v14._candidate_pages(doc)
    candidates: list[dict] = []
    funnel = Counter()

    for pno in pages:
        rows = sorted(v14._rows_from_words(doc[pno]), key=lambda row: float(row["y"]))
        for row in rows:
            if not _is_exact_strict_equity_row(str(row.get("text") or "")):
                continue
            funnel["exact_equity_total_rows"] += 1
            geometries = spatial._alias_geometries(row, STRICT_EQUITY_LABEL, "TOTAL_EQUITY")
            if not geometries:
                funnel["rows_without_alias_geometry"] += 1
                continue
            for geom in geometries:
                role_event = blocks.bind_alias_to_preceding_statement_event(
                    events, pno + 1, float(row["y"]), float(geom["x0"])
                )
                if role_event is None:
                    funnel["rows_without_formal_role"] += 1
                    continue
                if role_event.get("role") not in ("GROUP", "DUAL_GROUP_PARENT"):
                    funnel["rows_bound_parent"] += 1
                    continue
                unit, mult, unit_evidence = blocks.role_local_unit_context(
                    doc, events, role_event, pno + 1, float(row["y"])
                )
                if unit is None or mult is None:
                    funnel["rows_without_unit"] += 1
                    continue
                period_evidence = v166._statement_period_evidence(
                    doc, role_event, unit_evidence, pno + 1, expected_economic_date
                )
                if not period_evidence.get("matched"):
                    funnel["rows_without_frozen_period"] += 1
                    continue
                amounts = v167._amounts_after_alias(row, float(geom["x1"]))
                if len(amounts) < 2:
                    funnel["rows_without_two_amount_columns"] += 1
                    continue
                amount = amounts[0]
                value_cny = amount["value"] * mult
                if abs(value_cny) < Decimal("10000"):
                    funnel["economically_tiny_amount"] += 1
                    continue
                candidates.append({
                    "concept": "TOTAL_EQUITY",
                    "value": value_cny,
                    "raw_value": str(amount["value"]),
                    "unit": unit,
                    "unit_multiplier": mult,
                    "unit_evidence": unit_evidence,
                    "period_evidence": period_evidence,
                    "page": pno + 1,
                    "alias": STRICT_EQUITY_LABEL,
                    "alias_strength": v13._alias_strength("TOTAL_EQUITY", "股东权益合计") + 1,
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
                    "strict_same_row_equity_total": True,
                    "strict_amount_columns": [
                        {"raw": str(item["raw"]), "value": item["value"], "x0": item["x0"]}
                        for item in amounts
                    ],
                })
                funnel["strict_same_row_candidates"] += 1
    return candidates, dict(sorted(funnel.items()))


def _serialize(candidate: dict) -> dict:
    out = v1715._serialize_candidate(candidate)
    out["strict_same_row_equity_total"] = bool(candidate.get("strict_same_row_equity_total"))
    if candidate.get("strict_same_row_equity_total"):
        out["strict_amount_columns"] = [
            {"raw": str(item["raw"]), "value": str(item["value"]), "x0": str(item["x0"])}
            for item in candidate.get("strict_amount_columns") or []
        ]
    return out


def diagnose_spatial_balance_sheet_v17_17(
    doc: fitz.Document,
    expected_economic_date: str,
) -> dict:
    existing, base_funnel = v166._collect_candidates_v16_6(doc, expected_economic_date)
    bridge, bridge_funnel = v1715._collect_adjacent_bridge_candidates(doc, expected_economic_date)
    strict_equity, strict_funnel = _collect_strict_same_row_equity_candidates(doc, expected_economic_date)

    merged: dict[str, list[dict]] = defaultdict(list)
    for concept in CONCEPTS:
        merged[concept].extend(existing.get(concept, []))
        merged[concept].extend(bridge.get(concept, []))
    merged["TOTAL_EQUITY"].extend(strict_equity)
    candidates = v1715._dedupe_candidates(merged)
    chosen, identity = spatial._choose_spatial_identity(candidates)

    counts = {concept: len(candidates.get(concept, [])) for concept in CONCEPTS}
    strict_counts = {
        concept: sum(bool(row.get("strict_same_row_equity_total")) for row in candidates.get(concept, []))
        for concept in CONCEPTS
    }
    if chosen is None:
        return {
            "expected_economic_date": v166._canonical_economic_date(expected_economic_date),
            "base_funnel": base_funnel,
            "bridge_funnel": bridge_funnel,
            "strict_equity_funnel": strict_funnel,
            "candidate_counts": counts,
            "strict_candidate_counts": strict_counts,
            "identity_recovered_before_column_gate": False,
            "recovered": False,
            "identity": None,
            "column_role_gate": {"pass": False, "reason": "no A=L+E identity after strict total-equity extension"},
            "selected": {},
        }

    direct = {
        concept: v1715._direct_column_evidence(doc, candidate, expected_economic_date)
        for concept, candidate in chosen.items()
    }
    evidence = dict(direct)
    for concept, candidate in chosen.items():
        if direct[concept].get("pass"):
            continue
        sibling = v1715._trusted_sibling_evidence(doc, concept, candidate, chosen, direct)
        if sibling is not None:
            evidence[concept] = sibling
    all_pass = all(bool((evidence.get(concept) or {}).get("pass")) for concept in CONCEPTS)
    return {
        "expected_economic_date": v166._canonical_economic_date(expected_economic_date),
        "base_funnel": base_funnel,
        "bridge_funnel": bridge_funnel,
        "strict_equity_funnel": strict_funnel,
        "candidate_counts": counts,
        "strict_candidate_counts": strict_counts,
        "identity_recovered_before_column_gate": True,
        "recovered": bool(all_pass),
        "identity": identity if all_pass else None,
        "column_role_gate": {
            "pass": all_pass,
            "concepts": evidence,
            "policy": (
                "V17.15 preserved; exact GROUP row label 股东权益总计 only; "
                "same-row amount; frozen economic-date column; A=L+E tolerance 0.005"
            ),
        },
        "selected": {
            concept: _serialize(candidate)
            for concept, candidate in (chosen.items() if all_pass else [])
        },
    }
