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
_UNIT_TOKEN_RE = re.compile(r"(?:人民币)?(?:百万元|千元|万元|亿元|元)")

TITLE_PHRASES = (
    ("合并资产负债表和母公司资产负债表", "DUAL_GROUP_PARENT"),
    ("合并资产负债表及母公司资产负债表", "DUAL_GROUP_PARENT"),
    ("合并资产负债表及资产负债表", "DUAL_GROUP_PARENT"),
    ("合并及母公司资产负债表", "DUAL_GROUP_PARENT"),
    ("合并及公司资产负债表", "DUAL_GROUP_PARENT"),
    ("合并及银行资产负债表", "DUAL_GROUP_PARENT"),
    ("consolidatedstatementoffinancialposition", "GROUP"),
    ("consolidatedbalancesheet", "GROUP"),
    ("balancesheetofparentcompany", "PARENT"),
    ("母公司资产负债表", "PARENT"),
    ("合并资产负债表", "GROUP"),
    ("银行资产负债表", "PARENT"),
    ("公司资产负债表", "PARENT"),
    # An otherwise unqualified balance-sheet title is not assumed to be group.
    # It is a hard block boundary so a prior GROUP role cannot leak into it.
    ("资产负债表", "UNKNOWN_STATEMENT"),
)
NARRATIVE_TITLE_BLOCKERS = (
    "编制", "调整", "影响", "按照", "依据", "首次执行", "期初", "上述",
    "变动", "原因", "列示如下",
    "对合并资产负债表", "在合并资产负债表", "合并资产负债表中",
)


def _norm_title(text: str) -> str:
    compact = re.sub(r"\s+", "", text or "")
    # Evidence-backed extraction corruption observed in 601166 2021.
    return compact.replace("合幵", "合并")


def _compact_word_map(row: dict) -> tuple[str, list[int]]:
    chars: list[str] = []
    word_for_char: list[int] = []
    for idx, word in enumerate(row["words"]):
        text = _norm_title(str(word["text"]))
        for ch in text:
            chars.append(ch)
            word_for_char.append(idx)
    return "".join(chars), word_for_char


def _title_occurrences(row: dict) -> list[dict]:
    compact, char_map = _compact_word_map(row)
    if not compact or "目录" in compact:
        return []
    if len(compact) > 80 or any(token in compact for token in NARRATIVE_TITLE_BLOCKERS):
        return []

    occupied: list[tuple[int, int]] = []
    out = []
    # Longest phrases come first, preventing a dual title from being split into
    # overlapping GROUP/PARENT/UNKNOWN substring events.
    for phrase, role in TITLE_PHRASES:
        needle = _norm_title(phrase)
        start = 0
        while True:
            pos = compact.find(needle, start)
            if pos < 0:
                break
            end = pos + len(needle)
            if any(not (end <= a or pos >= b) for a, b in occupied):
                start = pos + 1
                continue
            first_word = char_map[pos]
            last_word = char_map[end - 1]
            words = row["words"]
            occupied.append((pos, end))
            out.append({
                "role": role,
                "phrase": phrase,
                "x0": float(words[first_word]["x0"]),
                "x1": float(words[last_word]["x1"]),
                "x_center": (float(words[first_word]["x0"]) + float(words[last_word]["x1"])) / 2,
                "compact_pos": pos,
            })
            start = end
    return sorted(out, key=lambda item: item["x0"])


def classify_formal_statement_title(text: str) -> tuple[str | None, bool]:
    """String-level classifier used by regressions and trace summaries."""
    compact = _norm_title(text)
    continuation = bool(re.search(r"(?:（续）|\(续\)|-续|续)$", compact))
    compact = compact.replace("（续）", "").replace("(续)", "").replace("-续", "")
    compact = compact.strip("：:、，,。.;；")
    if not compact or "目录" in compact or any(token in compact for token in NARRATIVE_TITLE_BLOCKERS):
        return None, continuation
    compact = re.sub(r"^20\d{2}年\d{1,2}月\d{1,2}日", "", compact)
    for phrase, role in TITLE_PHRASES:
        if compact == _norm_title(phrase):
            return role, continuation
    return None, continuation


def formal_statement_events(doc: fitz.Document) -> list[dict]:
    events: list[dict] = []
    for pno in range(doc.page_count):
        for row in v14._rows_from_words(doc[pno]):
            continuation = bool(re.search(r"(?:（续）|\(续\)|-续|续)\s*$", row["text"]))
            for occurrence in _title_occurrences(row):
                events.append({
                    "page": pno + 1,
                    "y": float(row["y"]),
                    "x0": occurrence["x0"],
                    "x1": occurrence["x1"],
                    "x_center": occurrence["x_center"],
                    "role": occurrence["role"],
                    "continuation": continuation,
                    "line": row["text"].strip(),
                    "matched_title": occurrence["phrase"],
                })
    return sorted(events, key=lambda e: (e["page"], e["y"], e["x0"]))


def bind_alias_to_preceding_statement_event(
    events: list[dict],
    page_1b: int,
    row_y: float,
    alias_x: float,
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

    latest_page = max(e["page"] for e in eligible)
    page_events = [e for e in eligible if e["page"] == latest_page]
    latest_y = max(float(e["y"]) for e in page_events)
    # Side-by-side titles can occupy the same header band. Bind the alias to the
    # horizontally nearest title instead of the last text line emitted by PDF.
    band = [e for e in page_events if abs(float(e["y"]) - latest_y) <= 8.0]
    if len(band) > 1:
        return min(band, key=lambda e: abs(float(e["x_center"]) - float(alias_x)))
    return max(page_events, key=lambda e: (e["y"], -abs(float(e["x_center"]) - float(alias_x))))


def detect_standalone_statement_unit(text: str) -> tuple[str | None, Decimal | None]:
    compact = re.sub(r"\s+", "", text or "").strip("：:、，,。.;；")
    direct = STANDALONE_UNITS.get(compact)
    if direct is not None:
        return direct

    # Dual group/parent tables often print the same unit once per numeric column
    # on one visual row: e.g. `人民币元 人民币元 人民币元 人民币元`.
    tokens = _UNIT_TOKEN_RE.findall(compact)
    if not tokens:
        return None, None
    remainder = _UNIT_TOKEN_RE.sub("", compact).strip("：:、，,。.;；")
    if remainder:
        return None, None
    mapped = [STANDALONE_UNITS.get(token) for token in tokens]
    if any(item is None for item in mapped):
        return None, None
    if len({item[1] for item in mapped if item is not None}) != 1:
        return None, None
    return mapped[0]


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


def _same_event(a: dict, b: dict) -> bool:
    return (
        a["page"] == b["page"]
        and abs(float(a["y"]) - float(b["y"])) <= 0.1
        and a["role"] == b["role"]
        and a.get("matched_title") == b.get("matched_title")
        and abs(float(a.get("x_center", 0)) - float(b.get("x_center", 0))) <= 0.1
    )


def role_local_unit_context(
    doc: fitz.Document,
    events: list[dict],
    role_event: dict,
    row_page_1b: int,
    row_y: float,
) -> tuple[str | None, Decimal | None, dict | None]:
    """Find a unit inside the same formal statement segment only."""
    if role_event["role"] not in ("GROUP", "DUAL_GROUP_PARENT"):
        return None, None, None

    current_page = int(row_page_1b)
    lower_page = max(1, current_page - MAX_BLOCK_LOOKBACK)
    root = role_event
    ordered = sorted(
        [e for e in events if e["page"] <= role_event["page"]],
        key=lambda e: (e["page"], e["y"], e["x0"]),
        reverse=True,
    )
    seen_current = False
    for event in ordered:
        if not seen_current:
            if _same_event(event, role_event):
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
        # PARENT or UNKNOWN_STATEMENT starts another statement and is a hard
        # boundary; a prior group unit must never cross it.
        if not event.get("continuation"):
            break

    root_page = max(lower_page, int(root["page"]))
    for page_1b in range(current_page, root_page - 1, -1):
        units = _page_units_with_y(doc[page_1b - 1])
        if page_1b == current_page:
            units = [u for u in units if u["y"] <= float(row_y) + 0.5]
        if not units:
            continue
        unit_record = max(units, key=lambda u: u["y"])
        return unit_record["unit"], unit_record["multiplier"], {
            "page": page_1b,
            "root_page": root_page,
            "source": unit_record["source"],
            "line": unit_record["line"],
        }
    return None, None, None
