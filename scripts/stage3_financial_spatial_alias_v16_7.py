#!/usr/bin/env python3
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

import fitz

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16 as spatial
import stage3_financial_spatial_alias_v16_3 as v166

DATE_RE = re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日")
HEADER_BLOCKERS = (
    "董事会", "批准", "审计", "财务报表已", "止年度财务报表",
    "第三层次", "变动金额", "主要原因",
)
HEADER_TOKENS = (
    "项目", "附注", "资产", "负债和股东权益", "负债和所有者权益",
    "本集团", "本公司", "本行",
)
X_TOLERANCE = 3.0


def _compact_word_map(row: dict) -> tuple[str, list[int]]:
    chars: list[str] = []
    cmap: list[int] = []
    for idx, word in enumerate(row["words"]):
        text = re.sub(r"\s+", "", str(word["text"]))
        for ch in text:
            chars.append(ch)
            cmap.append(idx)
    return "".join(chars), cmap


def _date_geometries(row: dict) -> list[dict]:
    compact, cmap = _compact_word_map(row)
    out = []
    for match in DATE_RE.finditer(compact):
        first = cmap[match.start()]
        last = cmap[match.end() - 1]
        words = row["words"]
        x0 = float(words[first]["x0"])
        x1 = float(words[last]["x1"])
        out.append({
            "date": f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}",
            "x0": x0,
            "x1": x1,
            "x_center": (x0 + x1) / 2,
            "row_y": float(row["y"]),
            "row_text": row["text"][:500],
        })
    return out


def _qualified_header_row(row: dict, expected: str, alias_x1: float) -> tuple[list[dict], int] | None:
    dates = [d for d in _date_geometries(row) if d["x_center"] >= alias_x1 - 5.0]
    if not dates or not any(d["date"] == expected for d in dates):
        return None
    compact = re.sub(r"\s+", "", row["text"] or "")
    if any(token in compact for token in HEADER_BLOCKERS):
        return None
    y, m, d = expected.split("-")
    expected_cn = f"{int(y)}年{int(m)}月{int(d)}日"
    structural = len(dates) >= 2 or compact == expected_cn or any(token in compact for token in HEADER_TOKENS)
    if not structural:
        return None
    dates.sort(key=lambda item: item["x_center"])
    expected_indexes = [idx for idx, item in enumerate(dates) if item["date"] == expected]
    if not expected_indexes:
        return None
    return dates, expected_indexes[0]


def _find_header_column_evidence(
    doc: fitz.Document,
    candidate: dict,
    expected_economic_date: str,
) -> dict | None:
    expected = v166._canonical_economic_date(expected_economic_date)
    current_page = int(candidate["page"])
    root_page = int((candidate.get("unit_evidence") or {}).get("root_page") or candidate["statement_anchor_page"])
    alias_x1 = float(candidate["alias_x1"])

    for page_1b in range(current_page, max(1, root_page) - 1, -1):
        qualified = []
        for row in v14._rows_from_words(doc[page_1b - 1]):
            result = _qualified_header_row(row, expected, alias_x1)
            if result is None:
                continue
            dates, expected_index = result
            qualified.append((len(dates), -float(row["y"]), row, dates, expected_index))
        if not qualified:
            continue
        # Prefer the richest date-column row on the nearest page. When tied,
        # prefer the higher header row.
        qualified.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _, _, row, dates, expected_index = qualified[0]
        return {
            "page": page_1b,
            "row_y": float(row["y"]),
            "row_text": row["text"][:500],
            "dates": dates,
            "expected_date": expected,
            "expected_column_index": expected_index,
        }
    return None


def _amounts_after_alias(row: dict, alias_x1: float) -> list[dict]:
    nums = [
        dict(item) for item in v14._numeric_word_candidates(row)
        if float(item["x0"]) >= alias_x1 - 1.0
    ]
    nums.sort(key=lambda item: float(item["x0"]))
    if len(nums) >= 2:
        first = nums[0]
        raw = str(first.get("raw") or "")
        val = first["value"]
        if (
            "," not in raw and "." not in raw and not raw.startswith("(")
            and Decimal("0") <= val <= Decimal("300")
        ):
            nums = nums[1:]
    return nums


def _selected_raw_decimal(candidate: dict) -> Decimal | None:
    try:
        return Decimal(str(candidate.get("raw_value")))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _find_candidate_row(doc: fitz.Document, candidate: dict) -> dict | None:
    pno = int(candidate["page"]) - 1
    alias = str(candidate["alias"])
    target_x = float(candidate["alias_x0"])
    selected_raw = _selected_raw_decimal(candidate)
    fallback = None
    for row in v14._rows_from_words(doc[pno]):
        for concept in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"):
            geoms = spatial._alias_geometries(row, alias, concept)
            for geom in geoms:
                if abs(float(geom["x0"]) - target_x) > X_TOLERANCE:
                    continue
                amounts = _amounts_after_alias(row, float(geom["x1"]))
                record = {"row": row, "geom": geom, "amounts": amounts}
                if fallback is None:
                    fallback = record
                if selected_raw is not None and any(a["value"] == selected_raw for a in amounts):
                    return record
    return fallback


def column_role_evidence(
    doc: fitz.Document,
    candidate: dict,
    expected_economic_date: str,
) -> dict:
    found = _find_candidate_row(doc, candidate)
    if found is None:
        return {"pass": False, "reason": "candidate alias row not reconstructed"}
    row = found["row"]
    geom = found["geom"]
    header = _find_header_column_evidence(doc, candidate, expected_economic_date)
    if header is None:
        return {"pass": False, "reason": "no qualified expected-date header row"}
    amounts = found.get("amounts") or _amounts_after_alias(row, float(geom["x1"]))
    idx = int(header["expected_column_index"])
    if idx >= len(amounts):
        return {
            "pass": False,
            "reason": "expected date column index exceeds amount columns",
            "header": header,
            "amounts": [{"raw": str(a["raw"]), "value": str(a["value"]), "x0": float(a["x0"])} for a in amounts],
        }
    expected_amount = amounts[idx]
    selected_raw = _selected_raw_decimal(candidate)
    selected_x = float(candidate["value_x"])
    value_match = selected_raw is not None and expected_amount["value"] == selected_raw
    return {
        "pass": value_match,
        "reason": None if value_match else "selected value is not the frozen-date ordinal amount",
        "header": header,
        "reconstructed_row": row["text"][:800],
        "amounts": [{"raw": str(a["raw"]), "value": str(a["value"]), "x0": float(a["x0"])} for a in amounts],
        "expected_amount": {
            "raw": str(expected_amount["raw"]),
            "value": str(expected_amount["value"]),
            "x0": float(expected_amount["x0"]),
        },
        "selected_raw_value": str(candidate.get("raw_value")),
        "selected_value_x": selected_x,
        "x_delta_diagnostic_only": abs(float(expected_amount["x0"]) - selected_x),
    }


def diagnose_spatial_balance_sheet_v16_7(
    doc: fitz.Document,
    expected_economic_date: str,
) -> dict:
    parsed = v166.diagnose_spatial_balance_sheet_v16_6(doc, expected_economic_date)
    if not parsed.get("recovered"):
        parsed = dict(parsed)
        parsed["column_role_gate"] = {"pass": False, "reason": "V16.6 did not recover"}
        parsed["recovered"] = False
        return parsed

    evidence = {}
    all_pass = True
    for concept, candidate in (parsed.get("selected") or {}).items():
        ev = column_role_evidence(doc, candidate, expected_economic_date)
        evidence[concept] = ev
        all_pass = all_pass and bool(ev.get("pass"))

    out = dict(parsed)
    out["v16_6_recovered"] = True
    out["column_role_gate"] = {
        "pass": all_pass,
        "concepts": evidence,
        "policy": "frozen economic-date ordinal must map to the exact selected raw amount",
    }
    out["recovered"] = bool(all_pass)
    if not all_pass:
        out["selected"] = {}
        out["identity"] = None
    return out
