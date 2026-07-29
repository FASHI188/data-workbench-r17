#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

import fitz

import stage3_financial_pdf_parser as parser_base
import stage3_financial_pdf_parser_v8 as v13
import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16 as spatial
import stage3_financial_statement_blocks_v16_3 as blocks


def _collect_candidates_v16_3(doc: fitz.Document) -> tuple[dict[str, list[dict]], dict]:
    concepts = {
        "TOTAL_ASSETS": parser_base.TIER1_ALIASES.get("TOTAL_ASSETS") or [],
        "TOTAL_LIABILITIES": parser_base.TIER2_ALIASES.get("TOTAL_LIABILITIES") or [],
        "TOTAL_EQUITY": parser_base.TIER2_ALIASES.get("TOTAL_EQUITY") or [],
    }
    events = blocks.formal_statement_events(doc)
    pages = v14._candidate_pages(doc)
    out: dict[str, list[dict]] = defaultdict(list)
    funnel = Counter()

    for pno in pages:
        funnel["candidate_pages"] += 1
        rows = v14._rows_from_words(doc[pno])
        for row in rows:
            for concept, aliases in concepts.items():
                geometries = []
                for alias in aliases:
                    for geom in spatial._alias_geometries(row, alias, concept):
                        geometries.append((alias, geom))
                if not geometries:
                    continue
                funnel[f"{concept}_alias_rows"] += 1
                geometries.sort(
                    key=lambda item: (
                        -v13._alias_strength(concept, item[0]),
                        -len(v14._norm(item[0])),
                        item[1]["x0"],
                    )
                )
                for alias, geom in geometries:
                    role_event = blocks.bind_alias_to_preceding_statement_event(
                        events,
                        pno + 1,
                        float(row["y"]),
                        float(geom["x0"]),
                    )
                    if role_event is None:
                        funnel[f"{concept}_alias_without_formal_role"] += 1
                        continue
                    if role_event["role"] not in ("GROUP", "DUAL_GROUP_PARENT"):
                        funnel[f"{concept}_alias_bound_parent"] += 1
                        continue
                    funnel[f"{concept}_alias_group_role"] += 1

                    unit, mult, unit_evidence = blocks.role_local_unit_context(
                        doc,
                        events,
                        role_event,
                        pno + 1,
                        float(row["y"]),
                    )
                    if unit is None or mult is None:
                        funnel[f"{concept}_group_alias_without_unit"] += 1
                        continue
                    funnel[f"{concept}_group_alias_with_unit"] += 1

                    amount = spatial._first_amount_after_alias(row, geom)
                    if amount is None:
                        funnel[f"{concept}_group_alias_without_right_amount"] += 1
                        continue
                    funnel[f"{concept}_group_alias_with_right_amount"] += 1
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
                    })

    for concept in list(out):
        best = {}
        for candidate in out[concept]:
            key = (
                str(candidate["value"]),
                candidate["page"],
                candidate["statement_anchor_page"],
                str(candidate["value_x"]),
            )
            current = best.get(key)
            rank = (
                int(candidate["alias_strength"]),
                len(v14._norm(candidate["alias"])),
                -float(candidate["alias_x0"]),
            )
            if current is None:
                best[key] = candidate
                continue
            current_rank = (
                int(current["alias_strength"]),
                len(v14._norm(current["alias"])),
                -float(current["alias_x0"]),
            )
            if rank > current_rank:
                best[key] = candidate
        out[concept] = list(best.values())

    funnel["formal_statement_events"] = len(events)
    funnel["formal_group_events"] = sum(e["role"] in ("GROUP", "DUAL_GROUP_PARENT") for e in events)
    funnel["formal_parent_events"] = sum(e["role"] == "PARENT" for e in events)
    return out, dict(sorted(funnel.items()))


def diagnose_spatial_balance_sheet_v16_3(doc: fitz.Document) -> dict:
    candidates, funnel = _collect_candidates_v16_3(doc)
    chosen, identity = spatial._choose_spatial_identity(candidates)
    return {
        "funnel": funnel,
        "candidate_counts": {
            concept: len(candidates.get(concept, []))
            for concept in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
        },
        "recovered": chosen is not None,
        "identity": identity,
        "selected": {
            concept: {
                "value": str(candidate["value"]),
                "raw_value": candidate["raw_value"],
                "unit": candidate["unit"],
                "unit_evidence": candidate["unit_evidence"],
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
            }
            for concept, candidate in (chosen or {}).items()
        },
    }
