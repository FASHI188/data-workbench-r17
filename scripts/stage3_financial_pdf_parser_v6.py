#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import asdict
from decimal import Decimal

import fitz

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v2 as v2
import stage3_financial_pdf_parser_v3 as v3
import stage3_financial_pdf_parser_v4 as v4
import stage3_financial_pdf_parser_v5 as v5  # noqa: F401 - retain all V8 hardening

# V11 is a grammar/alias coverage repair only.  It does not change the
# A=L+E tolerance, provenance, tie policy, or fail-closed requirement.

# Real official filings use all of these explicit unit phrasings:
#   金额单位为人民币元
#   单位：人民币千元
#   货币单位均以人民币百万元列示
CN_UNIT_RE = re.compile(
    r"(?:货币|金额)?单位\s*(?:[：:]|为|均为|均以)?\s*(?:人民币)?\s*(百万元|亿元|万元|千元|元)"
)
EN_UNIT_RE = re.compile(
    r"\b(?:unit|currency)\s*[:：]?\s*"
    r"(RMB\s*million|RMB\s*thousand|thousand\s*RMB|million\s*RMB|RMB|CNY|yuan)\b",
    re.I,
)
EN_UNIT_MULTIPLIERS = {
    "rmb": Decimal("1"),
    "cny": Decimal("1"),
    "yuan": Decimal("1"),
    "rmb thousand": Decimal("1000"),
    "thousand rmb": Decimal("1000"),
    "rmb million": Decimal("1000000"),
    "million rmb": Decimal("1000000"),
}


def detect_unit(text: str) -> tuple[str | None, Decimal | None]:
    m = CN_UNIT_RE.search(text or "")
    if m:
        unit = m.group(1)
        return unit, base.UNIT_MULTIPLIERS[unit]
    m = EN_UNIT_RE.search(text or "")
    if not m:
        return None, None
    raw = re.sub(r"\s+", " ", m.group(1).strip()).lower()
    mult = EN_UNIT_MULTIPLIERS.get(raw)
    if mult is None:
        return None, None
    return m.group(1), mult


def _append_alias(concept: str, alias: str, tier: dict[str, list[str]]) -> None:
    values = tier.setdefault(concept, [])
    if alias not in values:
        values.append(alias)


for _alias in ("资产合计", "Total of assets", "Total assets"):
    _append_alias("TOTAL_ASSETS", _alias, base.TIER1_ALIASES)
for _alias in (
    "Subtotal of owner's equity attributable to parent company",
    "Equity attributable to owners of parent company",
    "Equity attributable to shareholders of parent company",
):
    _append_alias("EQUITY_ATTRIBUTABLE_TO_PARENT", _alias, base.TIER1_ALIASES)
for _alias in ("Operating income", "Operating revenue"):
    _append_alias("OPERATING_REVENUE", _alias, base.TIER1_ALIASES)
for _alias in (
    "Net profit attributable to owners of parent company",
    "Net profit attributable to shareholders of parent company",
):
    _append_alias("NET_PROFIT_ATTRIBUTABLE_TO_PARENT", _alias, base.TIER1_ALIASES)
for _alias in ("Net cash flow from operating activities", "Net cash flows from operating activities"):
    _append_alias("NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES", _alias, base.TIER1_ALIASES)
for _alias in ("Operating cost", "Operating costs"):
    _append_alias("OPERATING_COST", _alias, base.TIER2_ALIASES)
for _alias in ("Total of liabilities", "Total liabilities"):
    _append_alias("TOTAL_LIABILITIES", _alias, base.TIER2_ALIASES)
for _alias in (
    "Total of owner's equity",
    "Total owner's equity",
    "Total owners' equity",
    "Total shareholders' equity",
    "Total stockholders' equity",
    "Total equity",
):
    _append_alias("TOTAL_EQUITY", _alias, base.TIER2_ALIASES)


def _alias_regex(alias: str) -> re.Pattern[str]:
    flags = re.I if re.search(r"[A-Za-z]", alias) else 0
    return re.compile(r"\s*".join(re.escape(ch) for ch in alias), flags)


_ORIGINAL_SEMANTIC_ROW_MATCH = base.semantic_row_match


def semantic_row_match(combined: str, alias: str, concept: str) -> bool:
    if not re.search(r"[A-Za-z]", alias):
        return _ORIGINAL_SEMANTIC_ROW_MATCH(combined, alias, concept)
    c = base.norm(combined).lower()
    a = base.norm(alias).lower()
    pos = c.find(a)
    if pos < 0 or pos > 14:
        return False
    if concept == "TOTAL_EQUITY" and "attributableto" in c:
        return False
    if concept == "TOTAL_ASSETS" and any(x in c for x in ("returnontotalassets", "averagetotalassets")):
        return False
    if concept == "OPERATING_REVENUE" and c.startswith("grossoperatingincome"):
        return False
    if concept == "OPERATING_COST" and c.startswith("grossoperatingcost"):
        return False
    return True


base.detect_unit = detect_unit
base.semantic_row_match = semantic_row_match
v2._alias_regex = _alias_regex


CN_TITLE_RE = re.compile(
    r"^(?:[一二三四五六七八九十\d]+[、.．])?"
    r"(?:未经审计)?"
    r"(?:[\u4e00-\u9fffA-Za-z0-9*ＳＴST（）()·]+有限公司)?"
    r"(?:\d{4}年\d{1,2}月\d{1,2}日)?"
    r"(?P<title>"
    r"合并及母公司资产负债表|合并及公司资产负债表|合并及银行资产负债表|"
    r"合并资产负债表|母公司资产负债表|公司资产负债表|银行资产负债表|资产负债表"
    r")"
    r"(?:（未经审计）|\(未经审计\))?$"
)
EN_CONSOLIDATED_TITLE_RE = re.compile(
    r"^(?:unaudited\s+)?(?:consolidated\s+balance\s+sheet|consolidated\s+statement\s+of\s+financial\s+position)$",
    re.I,
)
EN_PARENT_TITLE_RE = re.compile(
    r"^(?:unaudited\s+)?(?:balance\s+sheet|statement\s+of\s+financial\s+position)\s+of\s+(?:the\s+)?parent\s+company$",
    re.I,
)
EN_GENERIC_TITLE_RE = re.compile(
    r"^(?:unaudited\s+)?(?:balance\s+sheet|statement\s+of\s+financial\s+position)$",
    re.I,
)


def _balance_title_kind(line: str) -> str | None:
    raw = re.sub(r"\s+", " ", (line or "").strip())
    compact = base.norm(line)
    if "续" in compact or "目录" in compact:
        return None
    if EN_CONSOLIDATED_TITLE_RE.fullmatch(raw):
        return "CONSOLIDATED"
    if EN_PARENT_TITLE_RE.fullmatch(raw):
        return "PARENT_ONLY"
    if EN_GENERIC_TITLE_RE.fullmatch(raw):
        return "GENERIC"
    m = CN_TITLE_RE.fullmatch(compact)
    if not m:
        return None
    title = m.group("title")
    if title in (
        "合并及母公司资产负债表",
        "合并及公司资产负债表",
        "合并及银行资产负债表",
        "合并资产负债表",
    ):
        return "CONSOLIDATED"
    if title in ("母公司资产负债表", "公司资产负债表", "银行资产负债表"):
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

    if not out:
        for pno in base.candidate_statement_pages(doc):
            text = doc[pno].get_text("text") or ""
            compact = base.norm(text)
            unit, _ = base.detect_unit(text)
            hits = sum(
                x in compact
                for x in (
                    "资产总计",
                    "总资产",
                    "资产合计",
                    "负债合计",
                    "所有者权益合计",
                    "股东权益合计",
                )
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
    if v4._is_parent_equity_alias_hit(combined, alias, concept):
        return True
    if concept != "TOTAL_EQUITY":
        return False
    c = base.norm(combined).lower()
    return "attributableto" in c and any(
        x in c for x in ("parentcompany", "ownersofparentcompany", "shareholdersofparentcompany")
    )


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
                        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V11",
                        confidence="HIGH" if width <= 2 else "MEDIUM",
                    )
    return base.Observation(
        concept=concept,
        status="NOT_FOUND",
        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V11",
        confidence="NONE",
    )


_ORIGINAL_CANDIDATE_STATEMENT_PAGES = base.candidate_statement_pages
EN_STATEMENT_TITLE_RE = re.compile(
    r"^(?:unaudited\s+)?(?:consolidated\s+)?(?:balance\s+sheet|income\s+statement|cash\s+flow\s+statement|statement\s+of\s+financial\s+position)$",
    re.I,
)


def candidate_statement_pages(doc: fitz.Document) -> list[int]:
    pages = list(_ORIGINAL_CANDIDATE_STATEMENT_PAGES(doc))
    for pno in range(doc.page_count):
        lines = base.page_lines(doc[pno])
        if any(EN_STATEMENT_TITLE_RE.fullmatch(re.sub(r"\s+", " ", line.strip())) for line in lines):
            pages.extend(range(max(0, pno - 1), min(doc.page_count, pno + 4)))
    out: list[int] = []
    seen: set[int] = set()
    for pno in pages:
        if pno not in seen:
            seen.add(pno)
            out.append(pno)
    return out


base.candidate_statement_pages = candidate_statement_pages
v2._balance_sheet_start_pages = _balance_sheet_start_pages
v2._find_metric_in_block = _find_metric_in_block


def parse_pdf_bytes(raw: bytes) -> dict:
    out = v3._enforce_validated_balance_block(v2.parse_pdf_bytes(raw))
    observations = dict(out.get("observations") or {})
    current = observations.get("OPERATING_REVENUE") or {}
    if current.get("status") != "FOUND":
        doc = fitz.open(stream=raw, filetype="pdf")
        stmt_pages = base.candidate_statement_pages(doc)
        obs = base.find_metric_in_pages(
            doc,
            stmt_pages,
            base.TIER1_ALIASES["OPERATING_REVENUE"],
            "OPERATING_REVENUE",
            "PRIMARY_FINANCIAL_STATEMENT_V11",
        )
        if obs.status == "FOUND":
            observations["OPERATING_REVENUE"] = asdict(obs)
            out["observations"] = observations
            out["tier1_found"] = sum(
                (observations.get(k) or {}).get("status") == "FOUND" for k in base.TIER1_ALIASES
            )
    return out
