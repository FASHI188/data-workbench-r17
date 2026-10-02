#!/usr/bin/env python3
from __future__ import annotations

import fitz

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v2 as v2
import stage3_financial_pdf_parser_v3 as v3

PARENT_EQUITY_PREFIXES = (
    "归属于母公司",
    "归属于上市公司",
    "归属于本公司",
    "归属于本行",
    "归属于普通股",
)


def _balance_sheet_start_pages(doc: fitz.Document) -> list[tuple[int, int]]:
    """V6: consolidated-title precedence over parent-company exclusion.

    Compact/quarterly filings can expose both consolidated and parent-company
    balance-sheet titles in the first extracted text window of one PDF page.
    V4 checked the parent title first and dropped the page wholesale.  A page
    containing an explicit consolidated title must remain a priority-2 start.
    """
    out: list[tuple[int, int]] = []
    for pno in range(doc.page_count):
        lines = base.page_lines(doc[pno])
        if not lines:
            continue
        short = [base.norm(x) for x in lines[:40] if len(base.norm(x)) <= 36]
        joined = "\n".join(short)
        if "合并资产负债表" in joined:
            out.append((pno, 2))
            continue
        if "母公司资产负债表" in joined or ("公司资产负债表" in joined and "合并" not in joined):
            continue
        if any("资产负债表" in x and "续" not in x and "目录" not in x for x in short):
            out.append((pno, 1))

    if not out:
        for pno in base.candidate_statement_pages(doc):
            text = doc[pno].get_text("text") or ""
            compact = base.norm(text)
            unit, _ = base.detect_unit(text)
            hits = sum(
                x in compact
                for x in ("资产总计", "总资产", "负债合计", "所有者权益合计", "股东权益合计")
            )
            if unit and hits >= 2:
                out.append((pno, 0))

    dedup: list[tuple[int, int]] = []
    for pno, pri in sorted(out, key=lambda x: (x[0], -x[1])):
        if dedup and pno - dedup[-1][0] <= 2:
            if pri > dedup[-1][1]:
                dedup[-1] = (pno, pri)
            continue
        dedup.append((pno, pri))
    return dedup


def _is_parent_equity_alias_hit(combined: str, alias: str, concept: str) -> bool:
    if concept != "TOTAL_EQUITY":
        return False
    m = v2._alias_regex(alias).search(combined)
    if not m:
        return False
    prefix = base.norm(combined[: m.start()])
    return any(token in prefix for token in PARENT_EQUITY_PREFIXES)


def _find_metric_in_block(
    doc: fitz.Document,
    pages: list[int],
    aliases: list[str],
    concept: str,
    block_unit,
) -> base.Observation:
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
                for alias in aliases:
                    if _is_parent_equity_alias_hit(combined, alias, concept):
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
                        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V6",
                        confidence="HIGH" if width <= 2 else "MEDIUM",
                    )
    return base.Observation(
        concept=concept,
        status="NOT_FOUND",
        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V6",
        confidence="NONE",
    )


v2._balance_sheet_start_pages = _balance_sheet_start_pages
v2._find_metric_in_block = _find_metric_in_block


def parse_pdf_bytes(raw: bytes) -> dict:
    return v3._enforce_validated_balance_block(v2.parse_pdf_bytes(raw))
