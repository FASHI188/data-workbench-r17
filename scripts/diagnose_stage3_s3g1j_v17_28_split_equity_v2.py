#!/usr/bin/env python3
from __future__ import annotations

from decimal import Decimal
from typing import Any

import fitz

import diagnose_stage3_s3g1j_v17_28_split_equity as base


MAX_PRIMARY_DATE_DISTANCE = Decimal("40")
MAX_PRIMARY_UNIT_DISTANCE = Decimal("90")


def validate_header_context(
    doc: fitz.Document, event: dict[str, Any], economic_date_cn: str
) -> dict[str, Any]:
    """Accept repeated exact-date text objects but bind the nearest header witness.

    Quarterly PDFs may expose the statement date twice in the text layer: once as
    the centered statement date and once in a repeated/current-column heading.
    Repetition of the exact expected date is not a conflict. The nearest exact
    date and nearest CNY unit row after the formal GROUP title remain mandatory.
    """
    page = int(event["page"])
    rows = base.rows_v14._rows_from_words(doc[page - 1])
    event_y = Decimal(str(event.get("y") or 0))
    after = [
        row
        for row in rows
        if Decimal(str(row["y"])) >= event_y
        and Decimal(str(row["y"])) <= event_y + Decimal("110")
    ]
    date_rows = [
        row
        for row in after
        if base.normalize_text(economic_date_cn)
        in base.normalize_text(str(row.get("text") or ""))
    ]
    unit_rows = [
        row
        for row in after
        if "单位：元" in base.normalize_text(str(row.get("text") or ""))
        and "人民币" in base.normalize_text(str(row.get("text") or ""))
    ]
    if not date_rows:
        raise ValueError("GROUP expected-date evidence is missing")
    if not unit_rows:
        raise ValueError("GROUP CNY unit evidence is missing")
    primary_date = min(date_rows, key=lambda row: float(row["y"]))
    primary_unit = min(unit_rows, key=lambda row: float(row["y"]))
    date_distance = Decimal(str(primary_date["y"])) - event_y
    unit_distance = Decimal(str(primary_unit["y"])) - event_y
    if date_distance < 0 or date_distance > MAX_PRIMARY_DATE_DISTANCE:
        raise ValueError(
            f"GROUP primary expected-date distance={date_distance}"
        )
    if unit_distance < 0 or unit_distance > MAX_PRIMARY_UNIT_DISTANCE:
        raise ValueError(f"GROUP primary CNY-unit distance={unit_distance}")
    return {
        "date_row": str(primary_date["text"]),
        "date_text_object_count": len(date_rows),
        "date_distance_from_group_title": str(date_distance),
        "unit_row": str(primary_unit["text"]),
        "unit_text_object_count": len(unit_rows),
        "unit_distance_from_group_title": str(unit_distance),
        "duplicate_exact_date_objects_allowed": True,
    }


base.validate_header_context = validate_header_context


if __name__ == "__main__":
    raise SystemExit(base.main())
