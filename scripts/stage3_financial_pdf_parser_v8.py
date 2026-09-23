#!/usr/bin/env python3
from __future__ import annotations

from decimal import Decimal

import fitz

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v2 as v2
import stage3_financial_pdf_parser_v3 as v3
import stage3_financial_pdf_parser_v7 as v11_1

IDENTITY_TOLERANCE = Decimal("0.005")
MAX_CANDIDATES_PER_CONCEPT = 24

EXPLICIT_GROUP_EQUITY_ALIASES = {
    base.norm("所有者权益（或股东权益）合计"),
    base.norm("所有者权益合计"),
    base.norm("股东权益合计"),
    base.norm("Total of owner's equity"),
    base.norm("Total owner's equity"),
    base.norm("Total owners' equity"),
    base.norm("Total shareholders' equity"),
    base.norm("Total stockholders' equity"),
    base.norm("Total equity"),
}
PARENT_CONTEXT_TOKENS = tuple(base.norm(x) for x in (
    "归属于母公司",
    "归属于上市公司",
    "归属于本公司",
    "归属于本行",
    "归属于普通股",
))
CONTEXT_BARRIERS = tuple(base.norm(x) for x in (
    "少数股东权益",
    "非控制性权益",
    "股东权益合计",
    "所有者权益合计",
    "负债及股东权益总计",
    "负债和股东权益总计",
    "负债和所有者权益总计",
))


def _relative_identity_error(a: Decimal, l: Decimal, e: Decimal) -> Decimal:
    return abs(a - (l + e)) / max(abs(a), abs(l + e), Decimal("1"))


def _alias_strength(concept: str, alias: str) -> int:
    n = base.norm(alias)
    if concept == "TOTAL_EQUITY":
        if n in EXPLICIT_GROUP_EQUITY_ALIASES:
            return 3
        if n == base.norm("权益合计"):
            return 1
    if concept == "TOTAL_ASSETS" and n in {base.norm("资产总计"), base.norm("资产合计"), base.norm("Total of assets"), base.norm("Total assets")}:
        return 3
    if concept == "TOTAL_LIABILITIES" and n in {base.norm("负债合计"), base.norm("Total of liabilities"), base.norm("Total liabilities")}:
        return 3
    return 2


def _parent_context_penalty(lines: list[str], i: int, width: int, alias: str, concept: str) -> int:
    """Return a tie-break penalty; never hard-exclude a candidate.

    V11.1 looked two physical lines backwards and could let a prior
    `归属于本公司股东` label contaminate the later true group `股东权益合计`.
    V13 uses two protections:
      1) explicit group-total aliases are never penalized by earlier parent text;
      2) generic `权益合计` looks backwards only until a structural barrier.
    The accounting identity remains the final arbiter.
    """
    if concept != "TOTAL_EQUITY":
        return 0
    alias_norm = base.norm(alias)
    if alias_norm in EXPLICIT_GROUP_EQUITY_ALIASES:
        return 0

    context_parts: list[str] = []
    for q in range(i - 1, max(-1, i - 4), -1):
        if q < 0:
            break
        line_norm = base.norm(lines[q])
        if any(token in line_norm for token in CONTEXT_BARRIERS):
            break
        context_parts.append(line_norm)
    context_parts.reverse()
    context_parts.extend(base.norm(x) for x in lines[i : i + width])
    context = "".join(context_parts)
    return 1 if any(token in context for token in PARENT_CONTEXT_TOKENS) else 0


def _collect_metric_candidates(
    doc: fitz.Document,
    pages: list[int],
    aliases: list[str],
    concept: str,
    block_unit: tuple[str, Decimal],
) -> list[dict]:
    unit, mult = block_unit
    raw: list[dict] = []
    for pno in pages:
        if pno < 0 or pno >= doc.page_count:
            continue
        lines = base.page_lines(doc[pno])
        if not lines:
            continue
        for i in range(len(lines)):
            for width in (1, 2, 3, 4):
                if i + width > len(lines):
                    continue
                combined = " ".join(lines[i : i + width])
                for alias in aliases:
                    if not base.semantic_row_match(combined, alias, concept):
                        continue
                    nums = v3._numeric_tokens_after_alias_preserve_columns(combined, alias)
                    if not nums:
                        continue
                    raw_token, val = nums[0]
                    obs = base.Observation(
                        concept=concept,
                        status="FOUND",
                        raw_value=str(val),
                        normalized_cny_value=str(val * mult),
                        unit=unit,
                        unit_multiplier=str(mult),
                        page=pno + 1,
                        matched_alias=alias,
                        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V13_IDENTITY_ARBITRATION",
                        confidence="HIGH" if width <= 2 else "MEDIUM",
                    )
                    raw.append(
                        {
                            "observation": obs,
                            "value": val * mult,
                            "page": pno + 1,
                            "line_index": i,
                            "width": width,
                            "alias": alias,
                            "alias_strength": _alias_strength(concept, alias),
                            "parent_context_penalty": _parent_context_penalty(lines, i, width, alias, concept),
                            "raw_token": raw_token,
                        }
                    )

    # Deduplicate wider windows / overlapping aliases that point to the same
    # statement value. Keep the strongest, narrowest representation.
    best_by_value: dict[tuple[str, int], dict] = {}
    for c in raw:
        key = (str(c["value"]), int(c["page"]))
        rank = (
            -int(c["parent_context_penalty"]),
            int(c["alias_strength"]),
            -int(c["width"]),
            -int(c["line_index"]),
        )
        current = best_by_value.get(key)
        if current is None:
            best_by_value[key] = c
            continue
        current_rank = (
            -int(current["parent_context_penalty"]),
            int(current["alias_strength"]),
            -int(current["width"]),
            -int(current["line_index"]),
        )
        if rank > current_rank:
            best_by_value[key] = c

    out = list(best_by_value.values())
    out.sort(
        key=lambda c: (
            int(c["parent_context_penalty"]),
            -int(c["alias_strength"]),
            int(c["width"]),
            int(c["page"]),
            int(c["line_index"]),
        )
    )
    return out[:MAX_CANDIDATES_PER_CONCEPT]


def _choose_identity_triplet(candidates: dict[str, list[dict]]) -> tuple[dict | None, dict | None]:
    assets = candidates.get("TOTAL_ASSETS") or []
    liabilities = candidates.get("TOTAL_LIABILITIES") or []
    equities = candidates.get("TOTAL_EQUITY") or []
    valid: list[tuple[tuple, dict, dict]] = []

    for a in assets:
        for l in liabilities:
            for e in equities:
                rel = _relative_identity_error(a["value"], l["value"], e["value"])
                if rel > IDENTITY_TOLERANCE:
                    continue
                page_span = max(a["page"], l["page"], e["page"]) - min(a["page"], l["page"], e["page"])
                penalty = a["parent_context_penalty"] + l["parent_context_penalty"] + e["parent_context_penalty"]
                alias_strength = a["alias_strength"] + l["alias_strength"] + e["alias_strength"]
                total_width = a["width"] + l["width"] + e["width"]
                score = (
                    rel,
                    penalty,
                    page_span,
                    -alias_strength,
                    total_width,
                    a["page"] + l["page"] + e["page"],
                )
                chosen = {"TOTAL_ASSETS": a, "TOTAL_LIABILITIES": l, "TOTAL_EQUITY": e}
                meta = {
                    "identity_relative_error": str(rel),
                    "identity_residual_cny": str(abs(a["value"] - (l["value"] + e["value"]))),
                    "page_span": page_span,
                    "parent_context_penalty": penalty,
                    "alias_strength": alias_strength,
                }
                valid.append((score, chosen, meta))

    if not valid:
        return None, None
    valid.sort(key=lambda x: x[0])
    _, chosen, meta = valid[0]
    return chosen, meta


def _validated_balance_sheet_v13(doc: fitz.Document) -> tuple[dict[str, base.Observation] | None, dict | None]:
    block_candidates = []
    for start, priority in v2._balance_sheet_start_pages(doc):
        pages = list(range(start, min(doc.page_count, start + 5)))
        unit = v2._block_unit(doc, start, pages)
        if unit is None:
            continue

        candidates: dict[str, list[dict]] = {}
        for concept in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"):
            aliases = base.TIER1_ALIASES.get(concept) or base.TIER2_ALIASES.get(concept) or []
            candidates[concept] = _collect_metric_candidates(doc, pages, aliases, concept, unit)

        chosen, identity_meta = _choose_identity_triplet(candidates)
        if chosen is None or identity_meta is None:
            continue

        block: dict[str, base.Observation] = {
            concept: chosen[concept]["observation"]
            for concept in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
        }
        parent_aliases = base.TIER1_ALIASES.get("EQUITY_ATTRIBUTABLE_TO_PARENT") or []
        block["EQUITY_ATTRIBUTABLE_TO_PARENT"] = v2._find_metric_in_block(
            doc,
            pages,
            parent_aliases,
            "EQUITY_ATTRIBUTABLE_TO_PARENT",
            unit,
        )

        found = sum(x.status == "FOUND" for x in block.values())
        candidate_counts = {k: len(v) for k, v in candidates.items()}
        meta = {
            "start_page": start + 1,
            "unit": unit[0],
            "arbitration": "MULTI_CANDIDATE_A_EQUALS_L_PLUS_E",
            "identity_tolerance": str(IDENTITY_TOLERANCE),
            "identity_relative_error": identity_meta["identity_relative_error"],
            "identity_residual_cny": identity_meta["identity_residual_cny"],
            "candidate_counts": candidate_counts,
            "selected_aliases": {
                k: chosen[k]["alias"] for k in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
            },
            "selected_pages": {
                k: chosen[k]["page"] for k in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
            },
        }
        score = (
            -priority,
            Decimal(identity_meta["identity_relative_error"]),
            -found,
            identity_meta["parent_context_penalty"],
            identity_meta["page_span"],
            start,
        )
        block_candidates.append((score, block, meta))

    if not block_candidates:
        return None, None
    block_candidates.sort(key=lambda x: x[0])
    _, block, meta = block_candidates[0]
    return block, meta


# V2 resolves this module global at runtime. Keep every V11/V11.1 grammar,
# unit, issuer and fail-closed rule, replacing only joint balance resolution.
v2._validated_balance_sheet = _validated_balance_sheet_v13


def parse_pdf_bytes(raw: bytes) -> dict:
    return v11_1.parse_pdf_bytes(raw)
