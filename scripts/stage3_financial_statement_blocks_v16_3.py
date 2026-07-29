#!/usr/bin/env python3
from __future__ import annotations

import re
from decimal import Decimal

import fitz

import stage3_financial_pdf_parser as parser_base
import stage3_financial_coordinate_fallback_v14 as v14

MAX_BLOCK_LOOKBACK = 12
STANDALONE_UNITS = {
    "元": ("元", Decimal("1")),
    "人民币元": ("元", Decimal("1")),
    "千元": ("千元", Decimal("1000")),
    "人民币千元": ("千元", Decimal("1000")),
    "万元": ("万元", Decimal("10000")),
    "人民币万元": ("万元", Decimal("10000")),
    "百万元": ("百万元", Decimal("1000000")),
    "人民币百万元": ("百万元", Decimal("1000000")),
    "亿元": ("亿元", Decimal("100000000")),
    "人民币亿元": ("亿元", Decimal("100000000")),
}

_DATE_PREFIX = r"(?:20\d{2}年\d{1,2}月\d{1,2}日)?"
_DUAL_PATTERNS = (
    re.compile(rf"^{_DATE_PREFIX}合并及(?:母公司|公司|银行)资产负债表$"),
    re.compile(rf"^{_DATE_PREFIX}合并资产负债表(?:和|及)母公司资产负债表$"),
    re.compile(rf"^{_DATE_PREFIX}合并资产负债表及资产负债表$"),
)
_GROUP_PATTERNS = (
    re.compile(rf"^{_DATE_PREFIX}合并资产负债表$"),
    re.compile(r"^consolidatedbalancesheet$", re.I),
    re.compile(r"^consolidatedstatementoffinancialposition$", re.I),
)
_PARENT_PATTERNS = (
    re.compile(rf"^{_DATE_PREFIX}(?:母公司|公司|银行)资产负债表$"),
    re.compile(r"^balancesheetofparentcompany$", re.I),
)


def _norm_title(text: str) -> str:
    compact = re.sub(r"\s+", "", text or "")
    # Evidence-backed extraction corruption observed in 601166 2021.
    compact = compact.replace("合幵", "合并")
    compact = compact.replace("（续）", "").replace("(续)", "").replace("-续", "")
    compact = compact.strip("：:、，,。.;；")
    return compact


def classify_formal_statement_title(text: str) -> tuple[str | None, bool]:
    raw = re.sub(r"\s+", "", text or "").replace("合幵", "合并")
    continuation = bool(re.search(r"(?:（续）|\(续\)|-续|续)$", raw))
    compact = _norm_title(text)
    if not compact or "目录" in compact:
        return None, continuation
    for pattern in _DUAL_PATTERNS:
        if pattern.fullmatch(compact):
            return "DUAL_GROUP_PARENT", continuation
    for pattern in _GROUP_PATTERNS:
        if pattern.fullmatch(compact):
            return "GROUP", continuation
    for pattern in _PARENT_PATTERNS:
        if pattern.fullmatch(compact):
            return "PARENT", continuation
    return None, continuation


def formal_statement_events(doc: fitz.Document) -> list[dict]:
    events: list[dict] = []
    for pno in range(doc.page_count):
        for row in v14._rows_from_words(doc[pno]):
            role, continuation = classify_formal_statement_title(row["text"])
            if role is None:
                continue
            events.append({
                "page": pno + 1,
                "y": float(row["y"]),
                "role": role,
                "continuation": continuation,
                "line": row["text"].strip(),
            })
    return sorted(events, key=lambda e: (e["page"], e["y"]))


def bind_row_to_preceding_statement_event(
    events: list[dict],
    page_1b: int,
    row_y: float,
) -> dict | None:
    eligible = []
    for event in events:
        if event["page"] < max(1, page_1b - MAX_BLOCK_LOOKBACK):
            continue
        if event["page"] > page_1b:
            continue
        if event["page"] == page_1b and float(event["y"]) > float(row_y) + 0.5:
            continue
        eligible.append(event)
    if not eligible:
        return None
    return max(eligible, key=lambda e: (e["page"], e["y"]))


def detect_standalone_statement_unit(text: str) -> tuple[str | None, Decimal | None]:
    compact = re.sub(r"\s+", "", text or "").strip("：:、，,。.;；")
    return STANDALONE_UNITS.get(compact, (None, None))


def _page_units_with_y(page: fitz.Page) -> list[dict]:
    out = []
    for row in v14._rows_from_words(page):
        unit, mult = parser_base.detect_unit(row["text"])
        source = "EXPLICIT_UNIT_LABEL"
        if unit is None:
            unit, mult = detect_standalone_statement_unit(row["text"])
            source = "STANDALONE_STATEMENT_UNIT"
        if unit is not None and mult is not None:
            out.append({
                "y": float(row["y"]),
                "unit": unit,
                "multiplier": mult,
                "source": source,
                "line": row["text"].strip(),
            })
    return out


def role_local_unit_context(
    doc: fitz.Document,
    events: list[dict],
    role_event: dict,
    row_page_1b: int,
    row_y: float,
) -> tuple[str | None, Decimal | None, dict | None]:
    """Find a unit inside the same formal statement segment only.

    Search backwards from the candidate row. On the current page, only units
    above the candidate row are eligible. We stop before a different formal
    statement title. Continuation titles with the same role do not sever the
    block, so a unit on the root title page can propagate to its continuation.
    """
    if role_event["role"] not in ("GROUP", "DUAL_GROUP_PARENT"):
        return None, None, None

    current_page = int(row_page_1b)
    lower_page = max(1, current_page - MAX_BLOCK_LOOKBACK)

    # Find the nearest prior non-continuation formal event that starts this
    # statement family. Same-role continuation events are skipped. A different
    # non-continuation statement is a hard boundary.
    root = role_event
    ordered = [e for e in events if e["page"] <= role_event["page"]]
    ordered.sort(key=lambda e: (e["page"], e["y"]), reverse=True)
    seen_current = False
    for event in ordered:
        if not seen_current:
            if event is role_event or (
                event["page"] == role_event["page"]
                and event["y"] == role_event["y"]
                and event["line"] == role_event["line"]
            ):
                seen_current = True
            continue
        if event["page"] < lower_page:
            break
        if event["role"] == role_event["role"] and event.get("continuation"):
            root = event
            continue
        if event["role"] == role_event["role"] and not event.get("continuation"):
            root = event
            break
        if not event.get("continuation"):
            break

    root_page = max(lower_page, int(root["page"]))

    for page_1b in range(current_page, root_page - 1, -1):
        page = doc[page_1b - 1]
        units = _page_units_with_y(page)
        if page_1b == current_page:
            units = [u for u in units if u["y"] <= float(row_y) + 0.5]
        if not units:
            continue
        # latest preceding unit on the nearest page wins
        unit_record = max(units, key=lambda u: u["y"])
        return unit_record["unit"], unit_record["multiplier"], {
            "page": page_1b,
            "root_page": root_page,
            "source": unit_record["source"],
            "line": unit_record["line"],
        }
    return None, None, None
