#!/usr/bin/env python3
from __future__ import annotations

import stage3_financial_statement_blocks_v16_3 as base


# Freeze the accepted V16.4 page-unit reader before installing the narrow
# V16.5 extension. Calling base._page_units_with_y after monkeypatching it would
# recurse into this function.
_ORIGINAL_PAGE_UNITS_WITH_Y = base._page_units_with_y


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


base._page_units_with_y = _page_units_with_y_v16_5


def __getattr__(name):
    return getattr(base, name)
