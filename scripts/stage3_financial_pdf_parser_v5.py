#!/usr/bin/env python3
from __future__ import annotations

import re

import fitz

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v2 as v2
import stage3_financial_pdf_parser_v3 as v3
import stage3_financial_pdf_parser_v4 as v4

# V8 only accepts whole-line statement titles.  Scanning every extracted line is
# necessary because compact quarterly/half-year reports can place the statement
# title well after line 40, but matching arbitrary lines that merely *mention*
# “资产负债表” would recreate the false-start problem in accounting notes.
#
# Supported real-world forms include:
#   1、合并资产负债表
#   2024年6月30日合并及母公司资产负债表
#   国海证券股份有限公司合并及母公司资产负债表（未经审计）
#   资产负债表
# Parent-only titles are classified but never seed consolidated training truth.
TITLE_RE = re.compile(
    r"^(?:[一二三四五六七八九十\d]+[、.．])?"
    r"(?:[\u4e00-\u9fffA-Za-z0-9*ＳＴST（）()·]+有限公司)?"
    r"(?:\d{4}年\d{1,2}月\d{1,2}日)?"
    r"(?P<title>合并及母公司资产负债表|合并资产负债表|母公司资产负债表|公司资产负债表|资产负债表)"
    r"(?:（未经审计）|\(未经审计\))?$"
)


def _balance_title_kind(line: str) -> str | None:
    c = base.norm(line)
    if "续" in c:
        return None
    m = TITLE_RE.fullmatch(c)
    if not m:
        return None
    title = m.group("title")
    if title in ("合并及母公司资产负债表", "合并资产负债表"):
        return "CONSOLIDATED"
    if title in ("母公司资产负债表", "公司资产负债表"):
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

    # Nearby duplicate title hits belong to one statement block.  Retain the
    # earliest page at the highest priority; the validated parser still requires
    # block-local unit plus A/L/E accounting identity before accepting values.
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
