#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import fitz

import stage3_financial_pdf_parser as parser_base
import stage3_financial_pdf_parser_v8 as v13
import stage3_financial_coordinate_fallback_v14 as v14

IDENTITY_TOLERANCE = Decimal("0.005")
MAX_PAGE_SPAN = 9
MAX_ANCHOR_SPAN = 9


def _compact_word_map(row: dict) -> tuple[str, list[int]]:
    """Concatenate normalized PDF words and map each compact char to word index."""
    chars: list[str] = []
    word_for_char: list[int] = []
    for idx, word in enumerate(row["words"]):
        text = v14._norm(str(word["text"]))
        for ch in text:
            chars.append(ch)
            word_for_char.append(idx)
    return "".join(chars), word_for_char


def _alias_geometries(row: dict, alias: str, concept: str) -> list[dict]:
    compact, char_map = _compact_word_map(row)
    needle = v14._norm(alias)
    if not needle:
        return []
    out = []
    start = 0
    while True:
        pos = compact.find(needle, start)
        if pos < 0:
            break
        end_pos = pos + len(needle) - 1
        first_word = char_map[pos]
        last_word = char_map[end_pos]
        words = row["words"]

        # Concept-specific semantic exclusions must be local to this alias, not
        # based on its absolute string position in a two-panel visual row.
        left_context = compact[max(0, pos - 12):pos]
        full_context = compact[max(0, pos - 16):pos + len(needle) + 16]
        if concept == "TOTAL_LIABILITIES" and (
            "流动负债合计" in full_context or "非流动负债合计" in full_context
        ):
            start = pos + 1
            continue
        if concept == "TOTAL_ASSETS" and any(
            token in full_context for token in ("平均总资产收益率", "总资产收益率")
        ):
            start = pos + 1
            continue
        if concept == "TOTAL_EQUITY" and "归属于" in left_context:
            start = pos + 1
            continue

        local_prefix_words = words[max(0, first_word - 4):first_word]
        local_prefix = v14._norm("".join(str(x["text"]) for x in local_prefix_words))
        if any(v14._norm(token) in local_prefix for token in v14.SPECIAL_SCOPE_PREFIXES):
            start = pos + 1
            continue

        out.append({
            "alias": alias,
            "x0": Decimal(str(words[first_word]["x0"])),
            "x1": Decimal(str(words[last_word]["x1"])),
            "first_word": first_word,
            "last_word": last_word,
            "compact_pos": pos,
        })
        start = pos + 1
    return out


def _first_amount_after_alias(row: dict, geometry: dict) -> dict | None:
    nums = [
        item for item in v14._numeric_word_candidates(row)
        if item["x0"] >= geometry["x1"] - Decimal("1")
    ]
    nums.sort(key=lambda item: item["x0"])
    if not nums:
        return None

    # Drop a statement note / row-number column when it is a small plain integer.
    if len(nums) >= 2:
        first = nums[0]
        raw = str(first.get("raw") or "")
        val = first["value"]
        if (
            "," not in raw
            and "." not in raw
            and not raw.startswith("(")
            and Decimal("0") <= val <= Decimal("300")
        ):
            nums = nums[1:]
    return nums[0] if nums else None


def _collect_spatial_candidates(
    doc: fitz.Document,
    pages: list[int],
    events: list[dict],
) -> dict[str, list[dict]]:
    concepts = {
        "TOTAL_ASSETS": parser_base.TIER1_ALIASES.get("TOTAL_ASSETS") or [],
        "TOTAL_LIABILITIES": parser_base.TIER2_ALIASES.get("TOTAL_LIABILITIES") or [],
        "TOTAL_EQUITY": parser_base.TIER2_ALIASES.get("TOTAL_EQUITY") or [],
    }
    out: dict[str, list[dict]] = defaultdict(list)

    for pno in pages:
        unit, mult = parser_base.page_unit_context(doc, pno)
        if unit is None or mult is None:
            continue
        role_event = v14._nearest_statement_event(events, pno + 1)
        if role_event is None or role_event["role"] not in ("GROUP", "DUAL_GROUP_PARENT"):
            continue

        for row in v14._rows_from_words(doc[pno]):
            for concept, aliases in concepts.items():
                geometries = []
                for alias in aliases:
                    for geom in _alias_geometries(row, alias, concept):
                        geometries.append((alias, geom))
                if not geometries:
                    continue

                # Stronger/longer aliases win when multiple aliases cover the same
                # visual row. Each alias independently chooses the first monetary
                # amount to its right, which is the current-period amount in both
                # vertical and side-by-side statement layouts.
                geometries.sort(
                    key=lambda item: (
                        -v13._alias_strength(concept, item[0]),
                        -len(v14._norm(item[0])),
                        item[1]["x0"],
                    )
                )
                for alias, geom in geometries:
                    amount = _first_amount_after_alias(row, geom)
                    if amount is None:
                        continue
                    value_cny = amount["value"] * mult
                    if abs(value_cny) < Decimal("10000"):
                        continue
                    out[concept].append({
                        "concept": concept,
                        "value": value_cny,
                        "raw_value": str(amount["value"]),
                        "unit": unit,
                        "unit_multiplier": mult,
                        "page": pno + 1,
                        "alias": alias,
                        "alias_strength": v13._alias_strength(concept, alias),
                        "alias_x0": geom["x0"],
                        "alias_x1": geom["x1"],
                        "value_x": amount["x0"],
                        "statement_anchor_page": role_event["page"],
                        "statement_role": role_event["role"],
                        "statement_title": role_event["line"],
                        "row_text": row["text"][:800],
                    })

    # Deduplicate aliases/windows that resolve to the same page/value/role anchor.
    for concept in list(out):
        best = {}
        for c in out[concept]:
            key = (str(c["value"]), c["page"], c["statement_anchor_page"])
            current = best.get(key)
            rank = (int(c["alias_strength"]), len(v14._norm(c["alias"])), -float(c["alias_x0"]))
            if current is None:
                best[key] = c
                continue
            current_rank = (
                int(current["alias_strength"]),
                len(v14._norm(current["alias"])),
                -float(current["alias_x0"]),
            )
            if rank > current_rank:
                best[key] = c
        out[concept] = list(best.values())
    return out


def _choose_spatial_identity(candidates: dict[str, list[dict]]) -> tuple[dict | None, dict | None]:
    valid = []
    for assets in candidates.get("TOTAL_ASSETS", []):
        for liabilities in candidates.get("TOTAL_LIABILITIES", []):
            for equity in candidates.get("TOTAL_EQUITY", []):
                trio = (assets, liabilities, equity)
                roles = {x["statement_role"] for x in trio}
                if not roles.issubset({"GROUP", "DUAL_GROUP_PARENT"}):
                    continue
                page_span = max(x["page"] for x in trio) - min(x["page"] for x in trio)
                if page_span > MAX_PAGE_SPAN:
                    continue
                anchors = [int(x["statement_anchor_page"]) for x in trio]
                anchor_span = max(anchors) - min(anchors)
                if anchor_span > MAX_ANCHOR_SPAN:
                    continue
                rel = abs(assets["value"] - (liabilities["value"] + equity["value"])) / max(
                    abs(assets["value"]),
                    abs(liabilities["value"] + equity["value"]),
                    Decimal("1"),
                )
                if rel > IDENTITY_TOLERANCE:
                    continue
                strength = sum(int(x["alias_strength"]) for x in trio)
                score = (rel, page_span, anchor_span, min(anchors), -strength)
                valid.append((score, {
                    "TOTAL_ASSETS": assets,
                    "TOTAL_LIABILITIES": liabilities,
                    "TOTAL_EQUITY": equity,
                }, {
                    "identity_relative_error": str(rel),
                    "identity_residual_cny": str(abs(assets["value"] - (liabilities["value"] + equity["value"]))),
                    "page_span": page_span,
                    "anchor_span": anchor_span,
                    "statement_anchor_pages": anchors,
                }))
    if not valid:
        return None, None
    valid.sort(key=lambda item: item[0])
    _, chosen, meta = valid[0]
    return chosen, meta


def diagnose_spatial_balance_sheet(doc: fitz.Document) -> dict:
    events = v14._statement_events(doc)
    pages = v14._candidate_pages(doc)
    candidates = _collect_spatial_candidates(doc, pages, events)
    chosen, identity = _choose_spatial_identity(candidates)
    return {
        "statement_event_count": len(events),
        "candidate_page_count": len(pages),
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
                "page": candidate["page"],
                "alias": candidate["alias"],
                "alias_x0": str(candidate["alias_x0"]),
                "alias_x1": str(candidate["alias_x1"]),
                "value_x": str(candidate["value_x"]),
                "statement_anchor_page": candidate["statement_anchor_page"],
                "statement_role": candidate["statement_role"],
                "statement_title": candidate["statement_title"],
                "row_text": candidate["row_text"],
            }
            for concept, candidate in (chosen or {}).items()
        },
    }
