#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter

import fitz

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16_7 as v167
import stage3_financial_statement_blocks_v16_5 as accepted

GROUP_WITNESS_ALIAS = "归属于母公司所有者权益合计"
TOTAL_EQUITY_ALIAS = "所有者权益合计"
MAX_WITNESS_LOOKAHEAD_PAGES = 12
EXACT_AMOUNT_COLUMNS = 2

# Freeze the accepted reader before candidate monkeypatching.
_ACCEPTED_FORMAL_STATEMENT_EVENTS = accepted.formal_statement_events


def _exact_alias_amounts(row: dict, alias: str) -> list[dict]:
    compact, char_map = v167._compact_word_map(row)
    needle = v14._norm(alias)
    if not compact.startswith(needle):
        return []
    if len(char_map) < len(needle):
        return []
    last_word = char_map[len(needle) - 1]
    words = row.get("words") or []
    if last_word >= len(words):
        return []
    alias_x1 = float(words[last_word]["x1"])
    return v167._amounts_after_alias(row, alias_x1)


def _event_after(a: dict, b: dict) -> bool:
    return (
        int(b["page"]),
        float(b["y"]),
        float(b.get("x0") or 0.0),
    ) > (
        int(a["page"]),
        float(a["y"]),
        float(a.get("x0") or 0.0),
    )


def _inside_segment(
    event: dict,
    next_event: dict | None,
    page_1b: int,
    row_y: float,
) -> bool:
    if page_1b < int(event["page"]):
        return False
    if page_1b == int(event["page"]) and row_y <= float(event["y"]) + 0.5:
        return False
    if page_1b > int(event["page"]) + MAX_WITNESS_LOOKAHEAD_PAGES:
        return False
    if next_event is None:
        return True
    if page_1b > int(next_event["page"]):
        return False
    if page_1b == int(next_event["page"]) and row_y >= float(next_event["y"]) - 0.5:
        return False
    return True


def _generic_group_witness(
    doc: fitz.Document,
    event: dict,
    next_event: dict | None,
) -> dict | None:
    if event.get("role") != "UNKNOWN_STATEMENT":
        return None
    if not accepted._generic_balance_heading(str(event.get("line") or "")):
        return None

    last_page = min(
        doc.page_count,
        int(event["page"]) + MAX_WITNESS_LOOKAHEAD_PAGES,
        int(next_event["page"]) if next_event is not None else doc.page_count,
    )
    witness_rows: list[dict] = []
    total_rows: list[dict] = []
    for page_1b in range(int(event["page"]), last_page + 1):
        for row in v14._rows_from_words(doc[page_1b - 1]):
            row_y = float(row["y"])
            if not _inside_segment(event, next_event, page_1b, row_y):
                continue
            witness_amounts = _exact_alias_amounts(row, GROUP_WITNESS_ALIAS)
            if len(witness_amounts) == EXACT_AMOUNT_COLUMNS:
                witness_rows.append(
                    {
                        "page": page_1b,
                        "y": row_y,
                        "row_text": str(row.get("text") or "")[:800],
                        "amounts": [str(item["value"]) for item in witness_amounts],
                    }
                )
            total_amounts = _exact_alias_amounts(row, TOTAL_EQUITY_ALIAS)
            if len(total_amounts) == EXACT_AMOUNT_COLUMNS:
                total_rows.append(
                    {
                        "page": page_1b,
                        "y": row_y,
                        "row_text": str(row.get("text") or "")[:800],
                        "amounts": [str(item["value"]) for item in total_amounts],
                    }
                )

    same_page_pairs = [
        (witness, total)
        for witness in witness_rows
        for total in total_rows
        if witness["page"] == total["page"] and witness["y"] < total["y"]
    ]
    if len(same_page_pairs) != 1:
        return None
    witness, total = same_page_pairs[0]
    if witness["amounts"] != total["amounts"]:
        return None
    return {
        "source": "V17_25_GENERIC_BALANCE_SHEET_EXPLICIT_PARENT_ATTRIBUTABLE_EQUITY_WITNESS",
        "generic_title": str(event.get("line") or ""),
        "generic_title_page": int(event["page"]),
        "witness_alias": GROUP_WITNESS_ALIAS,
        "witness_page": witness["page"],
        "witness_y": witness["y"],
        "witness_amounts": witness["amounts"],
        "total_equity_alias": TOTAL_EQUITY_ALIAS,
        "total_equity_page": total["page"],
        "total_equity_y": total["y"],
        "total_equity_amounts": total["amounts"],
        "same_page": True,
        "amounts_equal": True,
        "amount_column_count": EXACT_AMOUNT_COLUMNS,
    }


def formal_statement_events(doc: fitz.Document) -> list[dict]:
    events = list(_ACCEPTED_FORMAL_STATEMENT_EVENTS(doc))
    ordered = sorted(events, key=lambda row: (row["page"], row["y"], row.get("x0", 0.0)))
    promoted: list[dict] = []
    funnel = Counter()
    for index, event in enumerate(ordered):
        if event.get("role") != "UNKNOWN_STATEMENT":
            promoted.append(event)
            continue
        funnel["unknown_statement_events"] += 1
        next_event = next(
            (candidate for candidate in ordered[index + 1 :] if _event_after(event, candidate)),
            None,
        )
        witness = _generic_group_witness(doc, event, next_event)
        if witness is None:
            funnel["unknown_without_exact_group_witness"] += 1
            promoted.append(event)
            continue
        row = dict(event)
        row["role"] = "GROUP"
        row["matched_title"] = (
            "GENERIC_BALANCE_SHEET_WITH_EXPLICIT_PARENT_ATTRIBUTABLE_EQUITY_WITNESS"
        )
        row["v17_25_generic_group_witness"] = witness
        promoted.append(row)
        funnel["promoted_generic_group_events"] += 1
    return sorted(promoted, key=lambda row: (row["page"], row["y"], row.get("x0", 0.0)))


def diagnose_generic_group_witness(doc: fitz.Document) -> dict:
    accepted_events = list(_ACCEPTED_FORMAL_STATEMENT_EVENTS(doc))
    candidate_events = formal_statement_events(doc)
    accepted_unknown = [
        event for event in accepted_events if event.get("role") == "UNKNOWN_STATEMENT"
    ]
    promoted = [
        event
        for event in candidate_events
        if event.get("v17_25_generic_group_witness") is not None
    ]
    return {
        "accepted_unknown_statement_count": len(accepted_unknown),
        "promoted_generic_group_count": len(promoted),
        "promoted_events": [
            {
                "page": event["page"],
                "line": event["line"],
                "role": event["role"],
                "matched_title": event["matched_title"],
                "witness": event["v17_25_generic_group_witness"],
            }
            for event in promoted
        ],
    }
