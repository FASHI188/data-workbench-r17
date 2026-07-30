#!/usr/bin/env python3
from __future__ import annotations

import re

import stage3_financial_statement_blocks_v16_3 as base


# Freeze the accepted V16.4 readers before installing the narrow V16.5/V17.2
# extensions. Calling the monkeypatched base functions from the wrappers would
# recurse into the wrappers themselves.
_ORIGINAL_PAGE_UNITS_WITH_Y = base._page_units_with_y
_ORIGINAL_TITLE_OCCURRENCES = base._title_occurrences


def _page_units_with_y_v16_5(page):
    out = list(_ORIGINAL_PAGE_UNITS_WITH_Y(page))
    seen = {
        (round(float(item["y"]), 2), item["unit"], str(item["multiplier"]), item["source"])
        for item in out
    }

    # PDF text extraction often emits each visible unit label as its own text
    # line even when word-coordinate reconstruction merges several columns into
    # one visual row. Accept only lines that are themselves exact standalone
    # statement units; narrative currency mentions remain rejected.
    for line in (page.get_text("text") or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        unit, mult = base.detect_standalone_statement_unit(stripped)
        if unit is None or mult is None:
            continue
        rects = page.search_for(stripped)
        if not rects:
            # y is used only to ensure a unit is not borrowed from below the
            # candidate row. Statement unit lines are header lines; fail closed
            # if the exact line cannot be positioned.
            continue
        for rect in rects:
            key = (round(float(rect.y0), 2), unit, str(mult), "TEXT_LINE_STANDALONE_STATEMENT_UNIT")
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "y": float(rect.y0),
                "unit": unit,
                "multiplier": mult,
                "source": "TEXT_LINE_STANDALONE_STATEMENT_UNIT",
                "line": stripped,
            })
    return out


def _strict_unknown_statement_title(text: str) -> bool:
    """Return true only for a genuine unqualified balance-sheet heading.

    V16.3 intentionally treats an otherwise unqualified ``资产负债表`` heading as
    a hard statement boundary. The coordinate occurrence finder, however, used
    substring matching, so short narrative rows such as ``资产负债表日后事项`` or
    ``在资产负债表中列示`` could become false UNKNOWN_STATEMENT boundaries.

    Preserve the intended fail-closed boundary for genuine headings, including
    continuation/page-range decorations observed in official PDFs, while
    rejecting narrative substring references. This changes statement-event
    classification only; GROUP/PARENT phrases, units, values, dates and A=L+E
    policy are untouched.
    """
    compact = base._norm_title(text)
    compact = re.sub(r"(?:（续）|\(续\)|-续|续)$", "", compact)
    compact = compact.strip("：:、，,。.;；")
    compact = re.sub(r"^20\d{2}年\d{1,2}月\d{1,2}日", "", compact)
    compact = re.sub(r"^(?:\d{1,2}|[一二三四五六七八九十]+)[、.．:：)]", "", compact)
    if compact.startswith("未经审计"):
        compact = compact[len("未经审计"):]
    if not compact.startswith("资产负债表"):
        return False
    suffix = compact[len("资产负债表"):].strip("：:、，,。.;；")
    if not suffix:
        return True
    # Official headings sometimes carry only a page/page-span marker on the
    # reconstructed row, e.g. ``资产负债表 10-12``.
    if re.fullmatch(r"\d+(?:[-－–—/]\d+)?", suffix):
        return True
    # Restatement comparison headers can be merged into the title row by PDF
    # word reconstruction; preserve that known structural form.
    if suffix and re.fullmatch(r"(?:会计政策变更前|会计政策变更|会计政策变更后)+", suffix):
        return True
    return False


def _title_occurrences_v17_2(row):
    occurrences = list(_ORIGINAL_TITLE_OCCURRENCES(row))
    if not any(item.get("role") == "UNKNOWN_STATEMENT" for item in occurrences):
        return occurrences
    if _strict_unknown_statement_title(row.get("text") or ""):
        return occurrences
    return [item for item in occurrences if item.get("role") != "UNKNOWN_STATEMENT"]


base._page_units_with_y = _page_units_with_y_v16_5
base._title_occurrences = _title_occurrences_v17_2


def __getattr__(name):
    return getattr(base, name)
