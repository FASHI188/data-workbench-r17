#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import asdict
from decimal import Decimal, InvalidOperation

import fitz

import stage3_financial_pdf_parser as base

# Do not independently scan balance-sheet concepts across the whole report.
# They are now resolved together from one accounting-identity-valid balance-
# sheet block. This prevents an asset value from an early summary page being
# combined with liabilities/equity from the formal statements.
STATEMENT_PRIORITY = (
    "NET_PROFIT_ATTRIBUTABLE_TO_PARENT",
    "NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES",
)
BALANCE_CONCEPTS = (
    "TOTAL_ASSETS",
    "TOTAL_LIABILITIES",
    "TOTAL_EQUITY",
    "EQUITY_ATTRIBUTABLE_TO_PARENT",
)


def _d(v: str | None) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _balance_sheet_identity_error(obs: dict[str, base.Observation]) -> str | None:
    a = _d(obs.get("TOTAL_ASSETS").normalized_cny_value if obs.get("TOTAL_ASSETS") else None)
    l = _d(obs.get("TOTAL_LIABILITIES").normalized_cny_value if obs.get("TOTAL_LIABILITIES") else None)
    e = _d(obs.get("TOTAL_EQUITY").normalized_cny_value if obs.get("TOTAL_EQUITY") else None)
    if a is None or l is None or e is None:
        return None
    denom = max(abs(a), abs(l + e), Decimal("1"))
    rel = abs(a - (l + e)) / denom
    # Allow ordinary report-unit rounding, but not 1,000x/10,000x unit mistakes.
    if rel > Decimal("0.005"):
        return f"BALANCE_SHEET_IDENTITY_MISMATCH assets={a} liabilities={l} equity={e} rel={rel}"
    return None


def _alias_regex(alias: str) -> re.Pattern[str]:
    # PDF text extraction often inserts arbitrary whitespace between Chinese
    # characters. Preserve numeric-column whitespace instead of globally
    # deleting it, otherwise two year columns can concatenate into one number.
    return re.compile(r"\s*".join(re.escape(ch) for ch in alias))


def _numeric_tokens_after_alias_preserve_columns(combined: str, alias: str) -> list[tuple[str, Decimal]]:
    m = _alias_regex(alias).search(combined)
    if not m:
        return []
    tail = combined[m.end():]
    out: list[tuple[str, Decimal]] = []
    for nm in base.NUMBER_RE.finditer(tail):
        val = base.parse_num(nm.group(0))
        if val is not None:
            out.append((nm.group(0), val))
    # Drop a common statement note/index column before current-period value.
    if len(out) >= 2:
        raw0, v0 = out[0]
        if "," not in raw0 and "." not in raw0 and not raw0.startswith("(") and Decimal("0") <= v0 <= Decimal("300"):
            out = out[1:]
    return out


def _find_metric_in_block(
    doc: fitz.Document,
    pages: list[int],
    aliases: list[str],
    concept: str,
    block_unit: tuple[str, Decimal],
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
                combined = " ".join(lines[i:i + width])
                for alias in aliases:
                    if not base.semantic_row_match(combined, alias, concept):
                        continue
                    nums = _numeric_tokens_after_alias_preserve_columns(combined, alias)
                    if not nums:
                        continue
                    raw_token, val = nums[0]
                    return base.Observation(
                        concept=concept,
                        status="FOUND",
                        raw_value=str(val),
                        normalized_cny_value=str(val * mult),
                        unit=unit,
                        unit_multiplier=str(mult),
                        page=pno + 1,
                        matched_alias=alias,
                        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK",
                        confidence="HIGH" if width <= 2 else "MEDIUM",
                    )
    return base.Observation(
        concept=concept,
        status="NOT_FOUND",
        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK",
        confidence="NONE",
    )


def _balance_sheet_start_pages(doc: fitz.Document) -> list[tuple[int, int]]:
    """Return (page, priority) candidates for consolidated/ordinary balance sheets.

    priority 2 = explicitly consolidated, 1 = ordinary/generic, 0 = weak fallback.
    Explicit parent-company balance sheets are excluded from the consolidated
    training-value path.
    """
    out: list[tuple[int, int]] = []
    for pno in range(doc.page_count):
        lines = base.page_lines(doc[pno])
        if not lines:
            continue
        short = [base.norm(x) for x in lines[:40] if len(base.norm(x)) <= 36]
        joined = "\n".join(short)
        if "母公司资产负债表" in joined or "公司资产负债表" in joined and "合并" not in joined:
            continue
        if "合并资产负债表" in joined:
            out.append((pno, 2))
            continue
        if any("资产负债表" in x and "续" not in x and "目录" not in x for x in short):
            out.append((pno, 1))
    # Fallback for old PDFs whose title extraction is broken: require multiple
    # terminal balance-sheet labels plus an explicit monetary unit on the page.
    if not out:
        for pno in base.candidate_statement_pages(doc):
            text = doc[pno].get_text("text") or ""
            compact = base.norm(text)
            unit, _ = base.detect_unit(text)
            hits = sum(x in compact for x in ("资产总计", "总资产", "负债合计", "所有者权益合计", "股东权益合计"))
            if unit and hits >= 2:
                out.append((pno, 0))
    # Deduplicate nearby title hits: continuation/title pages within two pages
    # belong to one block; retain the highest-priority earliest start.
    dedup: list[tuple[int, int]] = []
    for pno, pri in sorted(out, key=lambda x: (x[0], -x[1])):
        if dedup and pno - dedup[-1][0] <= 2:
            if pri > dedup[-1][1]:
                dedup[-1] = (pno, pri)
            continue
        dedup.append((pno, pri))
    return dedup


def _block_unit(doc: fitz.Document, start: int, pages: list[int]) -> tuple[str, Decimal] | None:
    # Unit must be stated inside this balance-sheet block. Never inherit a unit
    # from arbitrary preceding summary/narrative pages.
    ordered = [start] + [p for p in pages if p != start]
    for pno in ordered:
        if pno < 0 or pno >= doc.page_count:
            continue
        unit, mult = base.detect_unit(doc[pno].get_text("text") or "")
        if unit is not None and mult is not None:
            return unit, mult
    return None


def _validated_balance_sheet(doc: fitz.Document) -> tuple[dict[str, base.Observation] | None, dict | None]:
    candidates = []
    for start, priority in _balance_sheet_start_pages(doc):
        pages = list(range(start, min(doc.page_count, start + 5)))
        unit = _block_unit(doc, start, pages)
        if unit is None:
            continue
        block: dict[str, base.Observation] = {}
        for concept in BALANCE_CONCEPTS:
            aliases = base.TIER1_ALIASES.get(concept) or base.TIER2_ALIASES.get(concept) or []
            block[concept] = _find_metric_in_block(doc, pages, aliases, concept, unit)
        if any(block[k].status != "FOUND" for k in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")):
            continue
        err = _balance_sheet_identity_error(block)
        if err:
            continue
        found = sum(x.status == "FOUND" for x in block.values())
        candidates.append((priority, found, -start, block, {"start_page": start + 1, "unit": unit[0]}))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    _, _, _, block, meta = candidates[-1]
    return block, meta


def parse_pdf_bytes(raw: bytes) -> dict:
    doc = fitz.open(stream=raw, filetype="pdf")
    first_pages = list(range(0, min(doc.page_count, 20)))
    obs: dict[str, base.Observation] = {}

    # First collect early-summary observations. OPERATING_REVENUE and
    # non-recurring profit stay on the already locked summary path.
    for concept, aliases in base.TIER1_ALIASES.items():
        obs[concept] = base.find_metric_in_pages(
            doc, first_pages, aliases, concept, "EARLY_REPORT_SUMMARY"
        )

    statement_pages = base.candidate_statement_pages(doc)

    # Re-read only statement metrics that are not part of the balance-sheet
    # accounting identity. The balance-sheet family is resolved jointly below.
    for concept in STATEMENT_PRIORITY:
        stmt = base.find_metric_in_pages(
            doc,
            statement_pages,
            base.TIER1_ALIASES[concept],
            concept,
            "PRIMARY_FINANCIAL_STATEMENT",
        )
        if stmt.status == "FOUND":
            obs[concept] = stmt

    obs["OPERATING_COST"] = base.find_metric_in_pages(
        doc,
        statement_pages,
        base.TIER2_ALIASES["OPERATING_COST"],
        "OPERATING_COST",
        "PRIMARY_FINANCIAL_STATEMENT",
    )

    balance, balance_meta = _validated_balance_sheet(doc)
    if balance is not None:
        for concept, value in balance.items():
            if value.status == "FOUND":
                obs[concept] = value
    else:
        # Fail closed later through the identity gate, but retain the old
        # extraction evidence for diagnostics instead of fabricating a value.
        for concept in ("TOTAL_ASSETS", "EQUITY_ATTRIBUTABLE_TO_PARENT"):
            stmt = base.find_metric_in_pages(
                doc,
                statement_pages,
                base.TIER1_ALIASES[concept],
                concept,
                "STATEMENT_FALLBACK_NO_VALID_BALANCE_BLOCK",
            )
            if stmt.status == "FOUND":
                obs[concept] = stmt
        for concept in ("TOTAL_LIABILITIES", "TOTAL_EQUITY"):
            obs[concept] = base.find_metric_in_pages(
                doc,
                statement_pages,
                base.TIER2_ALIASES[concept],
                concept,
                "STATEMENT_FALLBACK_NO_VALID_BALANCE_BLOCK",
            )

    validation_errors: list[str] = []
    identity_error = _balance_sheet_identity_error(obs)
    if identity_error:
        validation_errors.append(identity_error)

    tier1_found = sum(obs[k].status == "FOUND" for k in base.TIER1_ALIASES)
    tier2_found = sum(obs[k].status == "FOUND" for k in base.TIER2_ALIASES)
    return {
        "page_count": doc.page_count,
        "tier1_found": tier1_found,
        "tier1_total": len(base.TIER1_ALIASES),
        "tier2_found": tier2_found,
        "tier2_total": len(base.TIER2_ALIASES),
        "balance_sheet_block": balance_meta,
        "validation_errors": validation_errors,
        "observations": {k: asdict(v) for k, v in obs.items()},
    }
