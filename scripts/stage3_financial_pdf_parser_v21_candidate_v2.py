#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
from decimal import Decimal
from typing import Any

import stage3_financial_pdf_parser_v21_candidate as base

METHOD = "V17_29_EXACT_SOURCE_SPLIT_GROUP_EQUITY_CANDIDATE_V2"
METHODOLOGY_VERSION = "V3.3.12-V17.29-CANDIDATE-V2"
ALLOWED_CONCEPTS = base.ALLOWED_CONCEPTS
IDENTITY_TOLERANCE = base.IDENTITY_TOLERANCE
MAX_LABEL_FRAGMENT_ROWS = base.MAX_LABEL_FRAGMENT_ROWS
MAX_ROW_GAP = base.MAX_ROW_GAP
MAX_COLUMN_X0_DRIFT = base.MAX_COLUMN_X0_DRIFT
FULL_EQUITY_LABEL = base.FULL_EQUITY_LABEL
TARGET_ALIASES = base.TARGET_ALIASES
TARGETS = base.TARGETS
accepted = base.accepted
fitz = base.fitz
blocks = base.blocks


def _label_text(rows: list[dict[str, Any]]) -> str:
    return "".join(base._normalize(str(row.get("text") or "")) for row in rows)


def _no_numeric_words(rows: list[dict[str, Any]]) -> bool:
    return all(not base._amounts(row) for row in rows)


def _sequence_gaps(rows: list[dict[str, Any]]) -> list[Decimal]:
    return [
        Decimal(str(rows[pos + 1]["y"])) - Decimal(str(rows[pos]["y"]))
        for pos in range(len(rows) - 1)
    ]


def _bounded_sequence(rows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    gaps = _sequence_gaps(rows)
    ok = bool(gaps) and all(Decimal("0") < gap <= MAX_ROW_GAP for gap in gaps)
    return ok, [str(gap) for gap in gaps]


def _find_split_equity(
    rows_by_page: dict[int, list[dict[str, Any]]],
    events: list[dict[str, Any]],
    target: dict[str, Any],
) -> dict[str, Any]:
    """Find one exact explicit GROUP equity pair with a complete bounded label.

    Accepted forms are deliberately narrow and source-bound:
    1) full label and exact two amounts on one row;
    2) complete label in <=3 consecutive rows immediately before the amounts;
    3) complete label split around the amount row, with <=3 consecutive text-only
       rows before and <=3 immediately after. The amount row is excluded from the
       label text. All participating rows must bind to the same formal GROUP event.
    """
    full = base._normalize(FULL_EQUITY_LABEL)
    matches: list[dict[str, Any]] = []

    for page, rows in rows_by_page.items():
        for idx, amount_row in enumerate(rows):
            pair = base._amount_pair(amount_row, target["values"]["TOTAL_EQUITY"])
            if pair is None:
                continue

            patterns: list[dict[str, Any]] = []

            if full in base._normalize(str(amount_row.get("text") or "")):
                patterns.append(
                    {
                        "label_rows": [amount_row],
                        "sequence_rows": [amount_row],
                        "pattern": "LABEL_AND_AMOUNTS",
                        "row_gaps": [],
                    }
                )

            for before_width in range(1, MAX_LABEL_FRAGMENT_ROWS + 1):
                start = idx - before_width
                if start < 0:
                    continue
                before = rows[start:idx]
                if not _no_numeric_words(before) or _label_text(before) != full:
                    continue
                sequence = before + [amount_row]
                ok, gaps = _bounded_sequence(sequence)
                if ok:
                    patterns.append(
                        {
                            "label_rows": before,
                            "sequence_rows": sequence,
                            "pattern": f"SPLIT_LABEL_{before_width}_ROWS_THEN_AMOUNTS",
                            "row_gaps": gaps,
                        }
                    )

            for before_width in range(1, MAX_LABEL_FRAGMENT_ROWS + 1):
                start = idx - before_width
                if start < 0:
                    continue
                before = rows[start:idx]
                if not _no_numeric_words(before):
                    continue
                for after_width in range(1, MAX_LABEL_FRAGMENT_ROWS + 1):
                    stop = idx + 1 + after_width
                    if stop > len(rows):
                        continue
                    after = rows[idx + 1 : stop]
                    if not _no_numeric_words(after):
                        continue
                    if _label_text(before + after) != full:
                        continue
                    sequence = before + [amount_row] + after
                    ok, gaps = _bounded_sequence(sequence)
                    if not ok:
                        continue
                    patterns.append(
                        {
                            "label_rows": before + after,
                            "sequence_rows": sequence,
                            "pattern": (
                                f"SPLIT_LABEL_{before_width}_BEFORE_"
                                f"{after_width}_AFTER_AMOUNT"
                            ),
                            "row_gaps": gaps,
                        }
                    )

            # For the exact amount row, more than one accepted pattern is an
            # ambiguity and therefore fail-closed rather than arbitrated.
            for pattern in patterns:
                label_row = pattern["label_rows"][0]
                event = base._bind(events, page, label_row)
                if (
                    not event
                    or event.get("role") != "GROUP"
                    or "合并资产负债表" not in str(event.get("line") or "")
                ):
                    continue
                event_key = base._event_key(event)
                if any(
                    (bound := base._bind(events, page, seq_row)) is None
                    or base._event_key(bound) != event_key
                    for seq_row in pattern["sequence_rows"]
                ):
                    continue
                try:
                    header = base._validate_header(rows_by_page, event, target)
                except ValueError:
                    continue
                matches.append(
                    {
                        "page": page,
                        "row": amount_row,
                        "pair": pair,
                        "label_rows": pattern["label_rows"],
                        "pattern": pattern["pattern"],
                        "row_gaps": pattern["row_gaps"],
                        "event": event,
                        "header": header,
                    }
                )

    if len(matches) != 1:
        raise ValueError(
            f"TOTAL_EQUITY split GROUP sequence count expected=1 actual={len(matches)}"
        )
    return matches[0]


def _recover_target(raw: bytes, target: dict[str, Any]) -> dict[str, Any]:
    if len(raw) != int(target["source_bytes"]):
        raise ValueError("target source byte length changed")
    with fitz.open(stream=raw, filetype="pdf") as doc:
        if len(doc) != int(target["page_count"]):
            raise ValueError("target page count changed")
        events = blocks.formal_statement_events(doc)
        rows_by_page = base._rows_by_page(doc)
        found = {
            "TOTAL_ASSETS": base._find_exact_labeled(
                rows_by_page, events, target, "TOTAL_ASSETS"
            ),
            "TOTAL_LIABILITIES": base._find_exact_labeled(
                rows_by_page, events, target, "TOTAL_LIABILITIES"
            ),
            "TOTAL_EQUITY": _find_split_equity(rows_by_page, events, target),
        }
        keys = {base._event_key(found[concept]["event"]) for concept in ALLOWED_CONCEPTS}
        if len(keys) != 1:
            raise ValueError(f"A/L/E not bound to one GROUP statement event: {keys}")
        alignment = base._validate_alignment(found)
        identity = base._validate_identity(target)
    return {
        "rows": found,
        "statement_event": found["TOTAL_EQUITY"]["event"],
        "header_context": found["TOTAL_EQUITY"]["header"],
        "column_alignment": alignment,
        "identity": identity,
    }


def _promote(
    current: dict, digest: str, target: dict[str, Any], evidence: dict[str, Any]
) -> dict:
    out = base._promote(current, digest, target, evidence)
    out["parser_version"] = METHOD
    for concept in ALLOWED_CONCEPTS:
        out["observations"][concept]["extraction_scope"] = METHOD
    out["balance_sheet_block"]["candidate_parser_revision"] = "V2"
    return out


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    current = accepted.parse_pdf_bytes(raw, economic_date)
    digest = hashlib.sha256(raw).hexdigest()
    target = TARGETS.get(digest)
    if (
        target is None
        or economic_date != target["economic_date"]
        or len(raw) != int(target["source_bytes"])
    ):
        return current
    if base._recovered(current):
        raise ValueError(
            f"V17.28 unexpectedly recovered V17.29 target {target['announcement_id']}"
        )
    evidence = _recover_target(raw, target)
    proposed = _promote(current, digest, target, evidence)
    if not base._recovered(proposed):
        raise ValueError(
            f"V17.29 candidate V2 did not recover {target['announcement_id']}"
        )
    return proposed
