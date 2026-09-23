#!/usr/bin/env python3
from __future__ import annotations

import fitz

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v2 as v2
import stage3_financial_pdf_parser_v3 as v3
import stage3_financial_pdf_parser_v6 as v11


def _find_metric_in_block_with_parent_context(
    doc: fitz.Document,
    pages: list[int],
    aliases: list[str],
    concept: str,
    block_unit,
) -> base.Observation:
    """V11.1: include preceding lines when rejecting parent-attributable equity.

    Some official statements split a parent subtotal across physical PDF lines::

        归属于本公司股东
        权益合计
        69,198,218,504

    The old row-local guard saw only ``权益合计`` and accepted the parent subtotal
    as group TOTAL_EQUITY.  We keep numeric extraction row-local, but give the
    parent-equity exclusion gate up to two preceding lines of semantic context.
    """
    unit, mult = block_unit
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
                semantic_context = " ".join(lines[max(0, i - 2) : i + width])
                for alias in aliases:
                    if v11._is_parent_equity_alias_hit(semantic_context, alias, concept):
                        continue
                    if not base.semantic_row_match(combined, alias, concept):
                        continue
                    nums = v3._numeric_tokens_after_alias_preserve_columns(combined, alias)
                    if not nums:
                        continue
                    _, val = nums[0]
                    return base.Observation(
                        concept=concept,
                        status="FOUND",
                        raw_value=str(val),
                        normalized_cny_value=str(val * mult),
                        unit=unit,
                        unit_multiplier=str(mult),
                        page=pno + 1,
                        matched_alias=alias,
                        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V11_1",
                        confidence="HIGH" if width <= 2 else "MEDIUM",
                    )
    return base.Observation(
        concept=concept,
        status="NOT_FOUND",
        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V11_1",
        confidence="NONE",
    )


v2._find_metric_in_block = _find_metric_in_block_with_parent_context


def parse_pdf_bytes(raw: bytes) -> dict:
    # V11's parser resolves v2 module globals at runtime, so the context-aware
    # finder above is used without weakening any other V11/V8 gate.
    return v11.parse_pdf_bytes(raw)
