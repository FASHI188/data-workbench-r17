#!/usr/bin/env python3
from __future__ import annotations

import re

import fitz

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v2 as v2
import stage3_financial_pdf_parser_v3 as v3
import stage3_financial_pdf_parser_v4 as v4

# Exact statement-title discovery.  V6 only inspected the first 40 extracted
# lines and only recognized the literal substring “合并资产负债表”.  Real filings
# place the title later on a page and use variants such as
# “合并及母公司资产负债表”.  Scan all short-ish lines, but reject narrative/note
# phrases that merely mention a balance sheet.
TITLE_REJECT_TOKENS = (
    "项目分析",
    "日后事项",
    "表内敞口",
    "表外敞口",
    "平均总资产",
    "主要项目如下",
    "附注",
    "目录",
)


def _balance_title_kind(line: str) -> str | None:
    c = base.norm(line)
    if "资产负债表" not in c or "续" in c:
        return None
    if any(token in c for token in TITLE_REJECT_TOKENS):
        return None
    # Long prose mentioning the statement is not a title.  Genuine titles can
    # include issuer/date/audit qualifiers, so keep a generous ceiling.
    if len(c) > 64:
        return None
    # Any explicit consolidated wording wins, including “合并及母公司”.
    if "合并" in c:
        return "CONSOLIDATED"
    # Parent-only statements must never seed the consolidated training block.
    if "母公司资产负债表" in c or ("公司资产负债表" in c and "合并" not in c):
        return "PARENT_ONLY"
    return "GENERIC"


def _balance_sheet_start_pages(doc: fitz.Document) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for pno in range(doc.page_count):
        lines = base.page_lines(doc[pno])
        if not lines:
            continue
        kinds = [_balance_title_kind(line) for line in lines]
        if "CONSOLIDATED" in kinds:
            out.append((pno, 2))
            continue
        if "GENERIC" in kinds:
            out.append((pno, 1))
            continue
        # A parent-only title on a page with no consolidated/generic statement
        # is deliberately ignored.

    # Structural fallback remains fail-closed: require an explicit unit and at
    # least two terminal balance-sheet labels on a statement-candidate page.
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

    # Nearby TOC/title/continuation hits may refer to the same statement block.
    # Keep the earliest page at the highest priority; a five-page block window
    # is large enough for the validated A/L/E terminal rows used below.
    dedup: list[tuple[int, int]] = []
    for pno, pri in sorted(out, key=lambda x: (x[0], -x[1])):
        if dedup and pno - dedup[-1][0] <= 2:
            if pri > dedup[-1][1]:
                dedup[-1] = (pno, pri)
            continue
        dedup.append((pno, pri))
    return dedup


# Keep all V5/V6 hardening: lone-note-index rejection, explicit no-block error,
# total-equity isolation from parent equity, block-local unit and A=L+E gate.
v2._balance_sheet_start_pages = _balance_sheet_start_pages
v2._find_metric_in_block = v4._find_metric_in_block


def parse_pdf_bytes(raw: bytes) -> dict:
    return v3._enforce_validated_balance_block(v2.parse_pdf_bytes(raw))
