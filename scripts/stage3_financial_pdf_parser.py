#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
from typing import Iterable

import fitz  # PyMuPDF

UNIT_MULTIPLIERS = {
    "元": Decimal("1"),
    "千元": Decimal("1000"),
    "万元": Decimal("10000"),
    "百万元": Decimal("1000000"),
    "亿元": Decimal("100000000"),
}

TIER1_ALIASES = {
    "OPERATING_REVENUE": ["营业收入"],
    "NET_PROFIT_ATTRIBUTABLE_TO_PARENT": [
        "归属于上市公司股东的净利润",
        "归属于母公司股东的净利润",
        "归属于母公司所有者的净利润",
        "归属于本行股东的净利润",
        "归属于本公司股东的净利润",
    ],
    "NET_PROFIT_EX_NONRECURRING_ATTRIBUTABLE_TO_PARENT": [
        "归属于上市公司股东的扣除非经常性损益的净利润",
        "扣除非经常性损益后归属于上市公司股东的净利润",
        "归属于母公司股东的扣除非经常性损益的净利润",
        "扣除非经常性损益后归属于母公司股东的净利润",
        "扣除非经常性损益后归属于本行股东的净利润",
        "归属于本行股东的扣除非经常性损益的净利润",
    ],
    "NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES": ["经营活动产生的现金流量净额"],
    "TOTAL_ASSETS": ["总资产", "资产总额", "资产总计"],
    "EQUITY_ATTRIBUTABLE_TO_PARENT": [
        "归属于上市公司股东的净资产",
        "归属于母公司所有者权益合计",
        "归属于母公司股东权益合计",
        "归属于母公司所有者权益（或股东权益）合计",
        "归属于本行普通股股东的股东权益",
        "归属于本公司股东的权益",
    ],
}

TIER2_ALIASES = {
    "OPERATING_COST": ["营业成本"],
    "TOTAL_LIABILITIES": ["负债合计"],
    "TOTAL_EQUITY": [
        "所有者权益（或股东权益）合计",
        "所有者权益合计",
        "股东权益合计",
        "权益合计",
    ],
}

NUMBER_RE = re.compile(r"(?<![\d.])\(?-?\d[\d,]*(?:\.\d+)?\)?")
UNIT_RE = re.compile(r"(?:货币)?单位\s*[：:]\s*(?:人民币)?\s*(百万元|亿元|万元|千元|元)")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").replace("／", "/")


def parse_num(token: str) -> Decimal | None:
    t = token.strip().replace(",", "")
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    try:
        x = Decimal(t)
    except InvalidOperation:
        return None
    return -x if neg else x


def detect_unit(text: str) -> tuple[str, Decimal]:
    m = UNIT_RE.search(text or "")
    if not m:
        return "元", Decimal("1")
    unit = m.group(1)
    return unit, UNIT_MULTIPLIERS[unit]


def semantic_row_match(combined: str, alias: str, concept: str) -> bool:
    c = norm(combined)
    a = norm(alias)
    pos = c.find(a)
    if pos < 0:
        return False
    # A metric label should begin near the left side of its row.  This rejects
    # narrative references and most percentage/change columns.
    if pos > 10:
        return False
    if concept == "TOTAL_LIABILITIES" and ("流动负债合计" in c or "非流动负债合计" in c):
        return False
    if concept == "TOTAL_ASSETS" and any(x in c for x in ("平均总资产收益率", "总资产收益率")):
        return False
    if concept == "TOTAL_EQUITY" and c.startswith("归属于"):
        return False
    if concept == "OPERATING_COST" and any(x in c for x in ("营业成本比", "营业成本率", "营业成本变动")):
        return False
    if concept == "OPERATING_REVENUE" and any(x in c for x in ("营业收入比", "营业收入增长", "营业收入变动原因")):
        return False
    return True


def numeric_tokens_after_alias(combined: str, alias: str) -> list[tuple[str, Decimal]]:
    compact = norm(combined)
    a = norm(alias)
    pos = compact.find(a)
    if pos < 0:
        return []
    tail = compact[pos + len(a):]
    out = []
    for m in NUMBER_RE.finditer(tail):
        val = parse_num(m.group(0))
        if val is not None:
            out.append((m.group(0), val))
    # Statement rows often have a note index before the two monetary columns.
    if len(out) >= 3:
        raw0, v0 = out[0]
        if "," not in raw0 and "." not in raw0 and not raw0.startswith("(") and Decimal("0") <= v0 <= Decimal("300"):
            out = out[1:]
    return out


@dataclass
class Observation:
    concept: str
    status: str
    raw_value: str | None = None
    normalized_cny_value: str | None = None
    unit: str | None = None
    unit_multiplier: str | None = None
    page: int | None = None
    matched_alias: str | None = None
    extraction_scope: str | None = None
    confidence: str | None = None


def page_lines(page: fitz.Page) -> list[str]:
    txt = page.get_text("text") or ""
    return [x.strip() for x in txt.splitlines() if x.strip()]


def find_metric_in_pages(
    doc: fitz.Document,
    page_indexes: Iterable[int],
    aliases: list[str],
    concept: str,
    scope: str,
) -> Observation:
    seen_pages = set()
    for pno in page_indexes:
        if pno < 0 or pno >= doc.page_count or pno in seen_pages:
            continue
        seen_pages.add(pno)
        page = doc[pno]
        lines = page_lines(page)
        if not lines:
            continue
        page_text = "\n".join(lines)
        unit, mult = detect_unit(page_text)
        # Use up to four adjacent lines to survive wrapped Chinese labels.
        for i in range(len(lines)):
            for width in (1, 2, 3, 4):
                if i + width > len(lines):
                    continue
                combined = " ".join(lines[i:i+width])
                for alias in aliases:
                    if not semantic_row_match(combined, alias, concept):
                        continue
                    nums = numeric_tokens_after_alias(combined, alias)
                    if not nums:
                        continue
                    raw_token, val = nums[0]
                    value_cny = val * mult
                    return Observation(
                        concept=concept,
                        status="FOUND",
                        raw_value=str(val),
                        normalized_cny_value=str(value_cny),
                        unit=unit,
                        unit_multiplier=str(mult),
                        page=pno + 1,
                        matched_alias=alias,
                        extraction_scope=scope,
                        confidence="HIGH" if width <= 2 else "MEDIUM",
                    )
    return Observation(concept=concept, status="NOT_FOUND", extraction_scope=scope, confidence="NONE")


def candidate_statement_pages(doc: fitz.Document) -> list[int]:
    pages: list[int] = []
    try:
        toc = doc.get_toc(simple=True) or []
    except Exception:
        toc = []
    for level, title, pno in toc:
        t = norm(title)
        if "财务报告" in t or "财务报表" in t:
            base = max(0, int(pno) - 1)
            pages.extend(range(max(0, base - 3), min(doc.page_count, base + 18)))
    # Quarterly/interim reports usually place statements near the front.
    pages.extend(range(0, min(doc.page_count, 28)))
    out = []
    seen = set()
    for p in pages:
        if p not in seen:
            seen.add(p); out.append(p)
    return out


def parse_pdf_bytes(raw: bytes) -> dict:
    doc = fitz.open(stream=raw, filetype="pdf")
    first_pages = list(range(0, min(doc.page_count, 18)))
    obs: dict[str, Observation] = {}
    for concept, aliases in TIER1_ALIASES.items():
        obs[concept] = find_metric_in_pages(doc, first_pages, aliases, concept, "EARLY_REPORT_SUMMARY")

    statement_pages = candidate_statement_pages(doc)
    for concept, aliases in TIER2_ALIASES.items():
        obs[concept] = find_metric_in_pages(doc, statement_pages, aliases, concept, "STATEMENT_OR_EARLY_DISCLOSURE")

    if obs["EQUITY_ATTRIBUTABLE_TO_PARENT"].status != "FOUND":
        obs["EQUITY_ATTRIBUTABLE_TO_PARENT"] = find_metric_in_pages(
            doc, statement_pages, TIER1_ALIASES["EQUITY_ATTRIBUTABLE_TO_PARENT"],
            "EQUITY_ATTRIBUTABLE_TO_PARENT", "STATEMENT_FALLBACK"
        )
    if obs["TOTAL_ASSETS"].status != "FOUND":
        obs["TOTAL_ASSETS"] = find_metric_in_pages(
            doc, statement_pages, TIER1_ALIASES["TOTAL_ASSETS"], "TOTAL_ASSETS", "STATEMENT_FALLBACK"
        )

    tier1_found = sum(obs[k].status == "FOUND" for k in TIER1_ALIASES)
    tier2_found = sum(obs[k].status == "FOUND" for k in TIER2_ALIASES)
    return {
        "page_count": doc.page_count,
        "tier1_found": tier1_found,
        "tier1_total": len(TIER1_ALIASES),
        "tier2_found": tier2_found,
        "tier2_total": len(TIER2_ALIASES),
        "observations": {k: asdict(v) for k, v in obs.items()},
    }
