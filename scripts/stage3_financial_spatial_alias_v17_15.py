#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

import fitz

import stage3_financial_pdf_parser as parser_base
import stage3_financial_pdf_parser_v8 as v13
import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16 as spatial
import stage3_financial_spatial_alias_v16_3 as v166
import stage3_financial_spatial_alias_v16_7 as v167
import stage3_financial_statement_blocks_v16_5 as blocks

CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
BRIDGE_MIN_Y_DELTA = Decimal(str(v14.Y_TOLERANCE))
BRIDGE_MAX_Y_DELTA = Decimal("3.25")
MIN_AMOUNT_COLUMNS = 2
BRIDGE_ALIASES = {
    "TOTAL_ASSETS": ("资产总计", "总资产", "Total assets", "Total of assets"),
    "TOTAL_LIABILITIES": ("负债合计", "负债总计", "总负债", "Total liabilities", "Total of liabilities"),
    "TOTAL_EQUITY": (
        "所有者权益合计", "股东权益合计", "权益合计",
        "Total equity", "Total of owner's equity", "Total shareholders' equity",
    ),
}
_ALLOWED_NON_NUMERIC_TOKENS = {"(", ")", "（", "）", "-", "—", "–"}


def _exact_terminal_alias(row_text: str, alias: str, concept: str) -> bool:
    if alias not in BRIDGE_ALIASES.get(concept, ()):
        return False
    return v14._norm(row_text) == v14._norm(alias)


def _strict_numeric_only_row(row: dict) -> bool:
    if not row.get("words"):
        return False
    for word in row["words"]:
        token = str(word.get("text") or "").strip()
        if not token:
            continue
        if token in _ALLOWED_NON_NUMERIC_TOKENS:
            continue
        variants = [token]
        if token.startswith("（") and token.endswith("）"):
            variants.append("(" + token[1:-1] + ")")
        parsed = False
        for candidate in variants:
            if parser_base.NUMBER_RE.fullmatch(candidate) and parser_base.parse_num(candidate) is not None:
                parsed = True
                break
        if not parsed:
            return False
    return True


def _adjacent_numeric_row(rows: list[dict], index: int, alias_x1: float) -> tuple[dict, list[dict], Decimal] | None:
    if index + 1 >= len(rows):
        return None
    current = rows[index]
    nxt = rows[index + 1]
    delta = Decimal(str(float(nxt["y"]) - float(current["y"])))
    if not (BRIDGE_MIN_Y_DELTA < delta <= BRIDGE_MAX_Y_DELTA):
        return None
    if not _strict_numeric_only_row(nxt):
        return None
    amounts = v167._amounts_after_alias(nxt, alias_x1)
    if len(amounts) < MIN_AMOUNT_COLUMNS:
        return None
    return nxt, amounts, delta


def _dedupe_candidates(candidates: dict[str, list[dict]]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for concept in CONCEPTS:
        best: dict[tuple, dict] = {}
        for candidate in candidates.get(concept, []):
            key = (
                str(candidate["value"]),
                int(candidate["page"]),
                int(candidate["statement_anchor_page"]),
                str(candidate["value_x"]),
            )
            rank = (
                0 if candidate.get("adjacent_row_bridge") else 1,
                int(candidate.get("alias_strength") or 0),
                len(v14._norm(str(candidate.get("alias") or ""))),
                -float(candidate.get("alias_x0") or 0),
            )
            current = best.get(key)
            if current is None:
                best[key] = candidate
                continue
            current_rank = (
                0 if current.get("adjacent_row_bridge") else 1,
                int(current.get("alias_strength") or 0),
                len(v14._norm(str(current.get("alias") or ""))),
                -float(current.get("alias_x0") or 0),
            )
            if rank > current_rank:
                best[key] = candidate
        out[concept] = list(best.values())
    return out


def _collect_adjacent_bridge_candidates(
    doc: fitz.Document,
    expected_economic_date: str,
) -> tuple[dict[str, list[dict]], dict]:
    concepts = v166._v16_concept_aliases()
    events = blocks.formal_statement_events(doc)
    pages = v14._candidate_pages(doc)
    out: dict[str, list[dict]] = defaultdict(list)
    funnel = Counter()

    for pno in pages:
        rows = sorted(v14._rows_from_words(doc[pno]), key=lambda row: float(row["y"]))
        for row_index, row in enumerate(rows):
            for concept, aliases in concepts.items():
                geometries = []
                for alias in aliases:
                    if not _exact_terminal_alias(row["text"], alias, concept):
                        continue
                    for geom in spatial._alias_geometries(row, alias, concept):
                        geometries.append((alias, geom))
                if not geometries:
                    continue
                funnel[f"{concept}_exact_terminal_alias_rows"] += 1
                geometries.sort(
                    key=lambda item: (
                        -v13._alias_strength(concept, item[0]),
                        -len(v14._norm(item[0])),
                        item[1]["x0"],
                    )
                )
                for alias, geom in geometries:
                    if spatial._first_amount_after_alias(row, geom) is not None:
                        funnel[f"{concept}_same_row_amount_present"] += 1
                        continue
                    role_event = blocks.bind_alias_to_preceding_statement_event(
                        events, pno + 1, float(row["y"]), float(geom["x0"])
                    )
                    if role_event is None:
                        funnel[f"{concept}_without_formal_role"] += 1
                        continue
                    if role_event["role"] not in ("GROUP", "DUAL_GROUP_PARENT"):
                        funnel[f"{concept}_bound_parent"] += 1
                        continue
                    unit, mult, unit_evidence = blocks.role_local_unit_context(
                        doc, events, role_event, pno + 1, float(row["y"])
                    )
                    if unit is None or mult is None:
                        funnel[f"{concept}_without_unit"] += 1
                        continue
                    period_evidence = v166._statement_period_evidence(
                        doc, role_event, unit_evidence, pno + 1, expected_economic_date
                    )
                    if not period_evidence["matched"]:
                        funnel[f"{concept}_wrong_or_missing_period"] += 1
                        continue
                    bridged = _adjacent_numeric_row(rows, row_index, float(geom["x1"]))
                    if bridged is None:
                        funnel[f"{concept}_no_strict_adjacent_numeric_row"] += 1
                        continue
                    numeric_row, amounts, delta = bridged
                    amount = amounts[0]
                    value_cny = amount["value"] * mult
                    if abs(value_cny) < Decimal("10000"):
                        funnel[f"{concept}_economically_tiny_amount"] += 1
                        continue
                    out[concept].append({
                        "concept": concept,
                        "value": value_cny,
                        "raw_value": str(amount["value"]),
                        "unit": unit,
                        "unit_multiplier": mult,
                        "unit_evidence": unit_evidence,
                        "period_evidence": period_evidence,
                        "page": pno + 1,
                        "alias": alias,
                        "alias_strength": v13._alias_strength(concept, alias),
                        "alias_x0": geom["x0"],
                        "alias_x1": geom["x1"],
                        "value_x": amount["x0"],
                        "statement_anchor_page": role_event["page"],
                        "statement_anchor_y": role_event["y"],
                        "statement_anchor_x": role_event["x_center"],
                        "statement_role": role_event["role"],
                        "statement_title": role_event["matched_title"],
                        "statement_title_line": role_event["line"],
                        "row_text": row["text"][:800],
                        "adjacent_row_bridge": True,
                        "bridge_y_delta": str(delta),
                        "bridge_numeric_row_text": numeric_row["text"][:800],
                        "bridge_amount_columns": [
                            {
                                "raw": str(item["raw"]),
                                "value": item["value"],
                                "x0": item["x0"],
                            }
                            for item in amounts
                        ],
                    })
                    funnel[f"{concept}_strict_adjacent_candidates"] += 1

    return out, dict(sorted(funnel.items()))


def _selected_raw_decimal(candidate: dict) -> Decimal | None:
    try:
        return Decimal(str(candidate.get("raw_value")))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _bridge_column_evidence_with_header(candidate: dict, header: dict, source: str) -> dict:
    amounts = candidate.get("bridge_amount_columns") or []
    idx = int(header.get("expected_column_index") or 0)
    if idx >= len(amounts):
        return {
            "pass": False,
            "reason": "expected date column index exceeds adjacent amount columns",
            "header": header,
            "evidence_source": source,
            "amounts": [
                {"raw": str(a["raw"]), "value": str(a["value"]), "x0": float(a["x0"])}
                for a in amounts
            ],
        }
    expected_amount = amounts[idx]
    selected_raw = _selected_raw_decimal(candidate)
    value_match = selected_raw is not None and expected_amount["value"] == selected_raw
    return {
        "pass": value_match,
        "reason": None if value_match else "adjacent selected value is not the frozen-date ordinal amount",
        "header": header,
        "evidence_source": source,
        "adjacent_row_bridge": True,
        "bridge_y_delta": candidate.get("bridge_y_delta"),
        "bridge_numeric_row_text": candidate.get("bridge_numeric_row_text"),
        "amounts": [
            {"raw": str(a["raw"]), "value": str(a["value"]), "x0": float(a["x0"])}
            for a in amounts
        ],
        "expected_amount": {
            "raw": str(expected_amount["raw"]),
            "value": str(expected_amount["value"]),
            "x0": float(expected_amount["x0"]),
        },
        "selected_raw_value": str(candidate.get("raw_value")),
        "selected_value_x": float(candidate.get("value_x") or 0),
    }


def _column_evidence_with_header(doc: fitz.Document, candidate: dict, header: dict, source: str) -> dict:
    if candidate.get("adjacent_row_bridge"):
        return _bridge_column_evidence_with_header(candidate, header, source)
    return v167._column_role_evidence_with_header(doc, candidate, header, source)


def _direct_column_evidence(doc: fitz.Document, candidate: dict, economic_date: str) -> dict:
    header = v167._find_header_column_evidence(doc, candidate, economic_date)
    if header is None:
        return {"pass": False, "reason": "no qualified expected-date header row"}
    return _column_evidence_with_header(doc, candidate, header, "DIRECT_EXPECTED_DATE_HEADER")


def _trusted_sibling_evidence(
    doc: fitz.Document,
    concept: str,
    candidate: dict,
    selected: dict[str, dict],
    direct: dict[str, dict],
) -> dict | None:
    page = int(candidate["page"])
    anchor = int(candidate["statement_anchor_page"])
    role = candidate.get("statement_role")
    unit = candidate.get("unit")
    for sibling in CONCEPTS:
        if sibling == concept:
            continue
        sibling_evidence = direct.get(sibling) or {}
        if not sibling_evidence.get("pass"):
            continue
        sibling_candidate = selected.get(sibling) or {}
        header = sibling_evidence.get("header") or {}
        if int(header.get("page") or -1) != page:
            continue
        if int(sibling_candidate.get("page") or -1) != page:
            continue
        if int(sibling_candidate.get("statement_anchor_page") or -1) != anchor:
            continue
        if sibling_candidate.get("statement_role") != role:
            continue
        if sibling_candidate.get("unit") != unit:
            continue
        evidence = _column_evidence_with_header(
            doc, candidate, header, "SAME_PAGE_SAME_ANCHOR_DIRECT_SIBLING_HEADER"
        )
        if not evidence.get("pass"):
            continue
        evidence["trusted_sibling_concept"] = sibling
        evidence["trusted_sibling_evidence_source"] = sibling_evidence.get("evidence_source")
        return evidence
    return None


def _serialize_candidate(candidate: dict) -> dict:
    out = {
        "value": str(candidate["value"]),
        "raw_value": candidate["raw_value"],
        "unit": candidate["unit"],
        "unit_evidence": candidate["unit_evidence"],
        "period_evidence": candidate["period_evidence"],
        "page": candidate["page"],
        "alias": candidate["alias"],
        "alias_x0": str(candidate["alias_x0"]),
        "alias_x1": str(candidate["alias_x1"]),
        "value_x": str(candidate["value_x"]),
        "statement_anchor_page": candidate["statement_anchor_page"],
        "statement_anchor_y": candidate["statement_anchor_y"],
        "statement_anchor_x": candidate["statement_anchor_x"],
        "statement_role": candidate["statement_role"],
        "statement_title": candidate["statement_title"],
        "statement_title_line": candidate["statement_title_line"],
        "row_text": candidate["row_text"],
        "adjacent_row_bridge": bool(candidate.get("adjacent_row_bridge")),
    }
    if candidate.get("adjacent_row_bridge"):
        out.update({
            "bridge_y_delta": candidate.get("bridge_y_delta"),
            "bridge_numeric_row_text": candidate.get("bridge_numeric_row_text"),
            "bridge_amount_columns": [
                {"raw": str(a["raw"]), "value": str(a["value"]), "x0": str(a["x0"])}
                for a in candidate.get("bridge_amount_columns") or []
            ],
        })
    return out


def diagnose_spatial_balance_sheet_v17_15(
    doc: fitz.Document,
    expected_economic_date: str,
) -> dict:
    existing, base_funnel = v166._collect_candidates_v16_6(doc, expected_economic_date)
    bridge, bridge_funnel = _collect_adjacent_bridge_candidates(doc, expected_economic_date)
    merged: dict[str, list[dict]] = defaultdict(list)
    for concept in CONCEPTS:
        merged[concept].extend(existing.get(concept, []))
        merged[concept].extend(bridge.get(concept, []))
    candidates = _dedupe_candidates(merged)
    chosen, identity = spatial._choose_spatial_identity(candidates)
    base_counts = {concept: len(existing.get(concept, [])) for concept in CONCEPTS}
    bridge_counts = {concept: len(bridge.get(concept, [])) for concept in CONCEPTS}
    counts = {concept: len(candidates.get(concept, [])) for concept in CONCEPTS}
    if chosen is None:
        return {
            "expected_economic_date": v166._canonical_economic_date(expected_economic_date),
            "base_funnel": base_funnel,
            "bridge_funnel": bridge_funnel,
            "base_candidate_counts": base_counts,
            "bridge_candidate_counts": bridge_counts,
            "candidate_counts": counts,
            "identity_recovered_before_column_gate": False,
            "recovered": False,
            "identity": None,
            "column_role_gate": {"pass": False, "reason": "no A=L+E identity after strict adjacent-row bridge"},
            "selected": {},
        }

    direct = {concept: _direct_column_evidence(doc, candidate, expected_economic_date) for concept, candidate in chosen.items()}
    evidence = dict(direct)
    for concept, candidate in chosen.items():
        if direct[concept].get("pass"):
            continue
        sibling = _trusted_sibling_evidence(doc, concept, candidate, chosen, direct)
        if sibling is not None:
            evidence[concept] = sibling
    all_pass = all(bool((evidence.get(concept) or {}).get("pass")) for concept in CONCEPTS)
    return {
        "expected_economic_date": v166._canonical_economic_date(expected_economic_date),
        "base_funnel": base_funnel,
        "bridge_funnel": bridge_funnel,
        "base_candidate_counts": base_counts,
        "bridge_candidate_counts": bridge_counts,
        "candidate_counts": counts,
        "identity_recovered_before_column_gate": True,
        "recovered": bool(all_pass),
        "identity": identity if all_pass else None,
        "column_role_gate": {
            "pass": all_pass,
            "concepts": evidence,
            "policy": (
                "exact terminal alias only; nearest following numeric-only row; "
                "2.8 < y delta <= 3.25; frozen economic-date ordinal; "
                "same-page/same-anchor direct sibling reuse remains non-transitive"
            ),
        },
        "selected": {
            concept: _serialize_candidate(candidate)
            for concept, candidate in (chosen.items() if all_pass else [])
        },
    }
