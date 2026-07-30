#!/usr/bin/env python3
from __future__ import annotations

import re

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_statement_blocks_v16_3 as base


# Freeze accepted readers before installing narrow V16-only extensions. Calling
# the monkeypatched base function from the wrapper would recurse into itself.
_ORIGINAL_PAGE_UNITS_WITH_Y = base._page_units_with_y
_ORIGINAL_FORMAL_STATEMENT_EVENTS = base.formal_statement_events

_PRESENTATION_UNIT_RE = re.compile(
    r"(?:以|按)\s*(?:人民币)?\s*(百万元|亿元|万元|千元|元)\s*(?:列示|计量|表示)",
    re.I,
)


def _explicit_presentation_unit(text: str):
    compact = re.sub(r"\s+", "", text or "")
    match = _PRESENTATION_UNIT_RE.search(compact)
    if not match:
        return None, None
    unit = match.group(1)
    return unit, base.STANDALONE_UNITS[unit]


def _page_units_with_y_v16_5(page):
    out = list(_ORIGINAL_PAGE_UNITS_WITH_Y(page))
    seen = {
        (round(float(item["y"]), 2), item["unit"], str(item["multiplier"]), item["source"])
        for item in out
    }

    # PDF text extraction often emits each visible unit label as its own text
    # line even when word-coordinate reconstruction merges several columns into
    # one visual row. Accept only exact standalone units or explicit statement
    # presentation clauses such as `以人民币百万元列示`. Narrative currency
    # mentions remain rejected.
    for line in (page.get_text("text") or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        unit, mult = base.detect_standalone_statement_unit(stripped)
        source = "TEXT_LINE_STANDALONE_STATEMENT_UNIT"
        if unit is None or mult is None:
            unit, mapped = _explicit_presentation_unit(stripped)
            mult = None if mapped is None else mapped[1]
            source = "TEXT_LINE_EXPLICIT_PRESENTATION_UNIT"
        if unit is None or mult is None:
            continue
        rects = page.search_for(stripped)
        if not rects:
            # y is used to prevent borrowing a unit from below the candidate row.
            # Fail closed when the exact visible evidence cannot be positioned.
            continue
        for rect in rects:
            key = (round(float(rect.y0), 2), unit, str(mult), source)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "y": float(rect.y0),
                "unit": unit,
                "multiplier": mult,
                "source": source,
                "line": stripped,
            })
    return out


def _generic_balance_heading(text: str) -> bool:
    compact = base._norm_title(text)
    compact = re.sub(r"(?:（续）|\(续\)|-续|续)$", "", compact)
    compact = compact.strip("：:、，,。.;；")
    compact = re.sub(r"^20\d{2}年\d{1,2}月\d{1,2}日", "", compact)
    compact = re.sub(r"^(?:\d{1,2}|[一二三四五六七八九十]+)[、.．:：)]", "", compact)
    if compact.startswith("未经审计"):
        compact = compact[len("未经审计"):]
    return compact == "资产负债表"


def formal_statement_events(doc):
    """Promote a generic balance-sheet heading only with explicit dual-role geometry.

    A generic `资产负债表` title is normally UNKNOWN and remains fail-closed. The
    sole V17 extension is when the *same page* visibly contains both a group
    header (`本集团`) and a parent/bank header (`本公司`/`本行`/`母公司`) such that
    the already-audited V14 coordinate splitter can establish a left/right role
    boundary. That positive geometry makes the table explicitly dual-role.
    """
    events = list(_ORIGINAL_FORMAL_STATEMENT_EVENTS(doc))
    out = []
    split_cache = {}
    for event in events:
        if event.get("role") != "UNKNOWN_STATEMENT" or not _generic_balance_heading(event.get("line") or ""):
            out.append(event)
            continue
        page_1b = int(event["page"])
        if page_1b not in split_cache:
            split_cache[page_1b] = v14._page_role_split(doc[page_1b - 1])
        split = split_cache[page_1b]
        if split is None:
            out.append(event)
            continue
        promoted = dict(event)
        promoted["role"] = "DUAL_GROUP_PARENT"
        promoted["matched_title"] = "GENERIC_BALANCE_SHEET_WITH_EXPLICIT_DUAL_ROLE_HEADERS"
        promoted["role_header_evidence"] = {
            "group_header_x": str(split["group_header_x"]),
            "parent_header_x": str(split["parent_header_x"]),
            "split_x": str(split["split_x"]),
        }
        out.append(promoted)
    return sorted(out, key=lambda e: (e["page"], e["y"], e["x0"]))


base._page_units_with_y = _page_units_with_y_v16_5


def __getattr__(name):
    return getattr(base, name)
