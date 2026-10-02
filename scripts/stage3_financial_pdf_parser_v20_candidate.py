#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
from decimal import Decimal
from typing import Any

import fitz

import stage3_financial_coordinate_fallback_v14 as rows_v14
import stage3_financial_pdf_parser_v19 as accepted
import stage3_financial_statement_blocks_v16_5 as blocks


METHOD = "V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_CANDIDATE"
METHODOLOGY_VERSION = "V3.3.8-V17.28-CANDIDATE"
ALLOWED_CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
FILTER_REASON = "V17_28_CANDIDATE_UNVALIDATED_NON_BALANCE_CONCEPT"
IDENTITY_TOLERANCE = Decimal("0.005")
MAX_SEQUENCE_ROWS = 3
MAX_ROW_GAP = Decimal("24")
MAX_EQUITY_ASSET_COLUMN_X0_DRIFT = Decimal("18")
MAX_PRIMARY_DATE_DISTANCE = Decimal("40")
MAX_PRIMARY_UNIT_DISTANCE = Decimal("90")
PARTIAL_EQUITY_LABEL = "所有者权益（或股东权益）合"
FULL_EQUITY_LABEL = "所有者权益（或股东权益）合计"
TARGET_ALIASES = {
    "TOTAL_ASSETS": "资产总计",
    "TOTAL_LIABILITIES": "负债合计",
    "TOTAL_EQUITY": FULL_EQUITY_LABEL,
}

TARGETS: dict[str, dict[str, Any]] = {
    "b2aa4afa67e2b02010d5ba708d4e5fe02138623ff4bc48718c03029111a64568": {
        "announcement_id": "1207621057",
        "source_code": "603995",
        "economic_date": "2020-03-31",
        "economic_date_cn": "2020年3月31日",
        "source_bytes": 477621,
        "group_anchor_page": 7,
        "pages": {
            "TOTAL_ASSETS": 8,
            "TOTAL_LIABILITIES": 9,
            "TOTAL_EQUITY": 10,
        },
        "values": {
            "TOTAL_ASSETS": ["5470381065.66", "5189894320.88"],
            "TOTAL_LIABILITIES": ["2220814468.73", "2026096822.42"],
            "TOTAL_EQUITY": ["3249566596.93", "3163797498.46"],
        },
        "split_pattern": "LABEL_AND_AMOUNTS_THEN_CONTINUATION",
    },
    "0bd1da8bdac0aff2a3e99b83adc29e7b60e959c99dd29b8ab88cbda1344b441c": {
        "announcement_id": "1209825769",
        "source_code": "603757",
        "economic_date": "2021-03-31",
        "economic_date_cn": "2021年3月31日",
        "source_bytes": 633887,
        "group_anchor_page": 8,
        "pages": {
            "TOTAL_ASSETS": 10,
            "TOTAL_LIABILITIES": 10,
            "TOTAL_EQUITY": 11,
        },
        "values": {
            "TOTAL_ASSETS": ["1615699540.62", "1595907051.24"],
            "TOTAL_LIABILITIES": ["312375993.81", "334336378.51"],
            "TOTAL_EQUITY": ["1303323546.81", "1261570672.73"],
        },
        "split_pattern": "LABEL_THEN_AMOUNTS_THEN_CONTINUATION",
    },
}


def _normalize(value: str) -> str:
    return (
        rows_v14._norm(value or "")
        .replace(":", "：")
        .replace("（", "(")
        .replace("）", ")")
    )


def _recovered(parsed: dict) -> bool:
    observations = parsed.get("observations") or {}
    return (
        all(
            isinstance(observations.get(concept), dict)
            and observations[concept].get("status") == "FOUND"
            for concept in ALLOWED_CONCEPTS
        )
        and isinstance(parsed.get("balance_sheet_block"), dict)
        and not list(parsed.get("validation_errors") or [])
    )


def _row_x0(row: dict[str, Any]) -> float:
    words = list(row.get("words") or [])
    return min((float(word["x0"]) for word in words), default=0.0)


def _amounts(row: dict[str, Any]) -> list[dict[str, Any]]:
    return list(rows_v14._numeric_word_candidates(row))


def _amount_pair(
    row: dict[str, Any], expected: list[str]
) -> list[dict[str, Any]] | None:
    wanted = [Decimal(value) for value in expected]
    candidates = _amounts(row)
    for start in range(max(0, len(candidates) - 1)):
        pair = candidates[start : start + 2]
        if [Decimal(str(item["value"])) for item in pair] == wanted:
            return pair
    return None


def _amount_only_row(row: dict[str, Any], pair: list[dict[str, Any]]) -> bool:
    allowed = {_normalize(str(item["raw"])) for item in pair}
    tokens = [_normalize(str(word.get("text") or "")) for word in row.get("words") or []]
    tokens = [token for token in tokens if token not in {"", "(", ")"}]
    return bool(tokens) and all(token in allowed for token in tokens)


def _find_exact_row(
    rows: list[dict[str, Any]], concept: str, expected: list[str]
) -> dict[str, Any]:
    alias = TARGET_ALIASES[concept]
    matches: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if _normalize(alias) not in _normalize(str(row.get("text") or "")):
            continue
        pair = _amount_pair(row, expected)
        if pair is not None:
            matches.append({"index": index, "row": row, "pair": pair})
    if len(matches) != 1:
        raise ValueError(
            f"{concept} exact row count expected=1 actual={len(matches)}"
        )
    return matches[0]


def _find_split_equity(
    rows: list[dict[str, Any]], expected: list[str]
) -> dict[str, Any]:
    partial = _normalize(PARTIAL_EQUITY_LABEL)
    full = _normalize(FULL_EQUITY_LABEL)
    matches: list[dict[str, Any]] = []
    for index, label_row in enumerate(rows):
        text = _normalize(str(label_row.get("text") or ""))
        if partial not in text or full in text:
            continue
        window = rows[index : min(len(rows), index + MAX_SEQUENCE_ROWS)]
        continuation_positions = [
            offset
            for offset, row in enumerate(window)
            if _normalize(str(row.get("text") or "")) == "计"
        ]
        if len(continuation_positions) != 1 or continuation_positions[0] == 0:
            continue
        continuation_offset = continuation_positions[0]
        amount_matches: list[tuple[int, list[dict[str, Any]]]] = []
        for offset, row in enumerate(window[: continuation_offset + 1]):
            pair = _amount_pair(row, expected)
            if pair is not None:
                amount_matches.append((offset, pair))
        if len(amount_matches) != 1:
            continue
        amount_offset, pair = amount_matches[0]
        amount_row = window[amount_offset]
        if amount_offset > 0 and not _amount_only_row(amount_row, pair):
            continue
        gaps = [
            Decimal(str(window[pos + 1]["y"])) - Decimal(str(window[pos]["y"]))
            for pos in range(continuation_offset)
        ]
        if not gaps or any(gap <= 0 or gap > MAX_ROW_GAP for gap in gaps):
            continue
        matches.append(
            {
                "label_row": label_row,
                "amount_row": amount_row,
                "continuation_row": window[continuation_offset],
                "pair": pair,
                "row_gaps": [str(gap) for gap in gaps],
                "pattern": (
                    "LABEL_AND_AMOUNTS_THEN_CONTINUATION"
                    if amount_offset == 0
                    else "LABEL_THEN_AMOUNTS_THEN_CONTINUATION"
                ),
            }
        )
    if len(matches) != 1:
        raise ValueError(
            f"split equity sequence count expected=1 actual={len(matches)}"
        )
    return matches[0]


def _validate_group_event(
    events: list[dict[str, Any]], page: int, row: dict[str, Any], target: dict
) -> dict[str, Any]:
    event = blocks.bind_alias_to_preceding_statement_event(
        events, page, float(row["y"]), _row_x0(row)
    )
    if not isinstance(event, dict):
        raise ValueError("split equity label has no formal statement event")
    if event.get("role") != "GROUP":
        raise ValueError(f"split equity role must be GROUP actual={event.get('role')}")
    if int(event.get("page") or 0) != int(target["group_anchor_page"]):
        raise ValueError("split equity GROUP anchor page changed")
    if "合并资产负债表" not in str(event.get("line") or ""):
        raise ValueError("split equity anchor is not consolidated balance sheet")
    return event


def _validate_header(
    doc: fitz.Document, event: dict[str, Any], target: dict
) -> dict[str, Any]:
    page = int(event["page"])
    rows = rows_v14._rows_from_words(doc[page - 1])
    event_y = Decimal(str(event.get("y") or 0))
    after = [
        row
        for row in rows
        if event_y <= Decimal(str(row["y"])) <= event_y + Decimal("110")
    ]
    date_rows = [
        row
        for row in after
        if _normalize(target["economic_date_cn"])
        in _normalize(str(row.get("text") or ""))
    ]
    unit_rows = [
        row
        for row in after
        if "单位：元" in _normalize(str(row.get("text") or ""))
        and "人民币" in _normalize(str(row.get("text") or ""))
    ]
    if not date_rows:
        raise ValueError("GROUP expected-date evidence missing")
    if not unit_rows:
        raise ValueError("GROUP CNY-unit evidence missing")
    primary_date = min(date_rows, key=lambda row: float(row["y"]))
    primary_unit = min(unit_rows, key=lambda row: float(row["y"]))
    date_distance = Decimal(str(primary_date["y"])) - event_y
    unit_distance = Decimal(str(primary_unit["y"])) - event_y
    if date_distance < 0 or date_distance > MAX_PRIMARY_DATE_DISTANCE:
        raise ValueError("GROUP expected-date witness not role-local")
    if unit_distance < 0 or unit_distance > MAX_PRIMARY_UNIT_DISTANCE:
        raise ValueError("GROUP CNY-unit witness not role-local")
    return {
        "date_row": str(primary_date["text"]),
        "date_text_object_count": len(date_rows),
        "date_distance_from_group_title": str(date_distance),
        "unit_row": str(primary_unit["text"]),
        "unit_text_object_count": len(unit_rows),
        "unit_distance_from_group_title": str(unit_distance),
        "duplicate_exact_date_objects_allowed": True,
    }


def _validate_alignment(
    asset_pair: list[dict[str, Any]], equity_pair: list[dict[str, Any]]
) -> dict[str, Any]:
    asset_x = [Decimal(str(item["x0"])) for item in asset_pair]
    equity_x = [Decimal(str(item["x0"])) for item in equity_pair]
    drift = [abs(a - e) for a, e in zip(asset_x, equity_x, strict=True)]
    if any(value > MAX_EQUITY_ASSET_COLUMN_X0_DRIFT for value in drift):
        raise ValueError(f"equity/asset column drift={drift}")
    if not (asset_x[0] < asset_x[1] and equity_x[0] < equity_x[1]):
        raise ValueError("current/prior columns are not left-to-right ordered")
    return {
        "asset_x0": [str(value) for value in asset_x],
        "equity_x0": [str(value) for value in equity_x],
        "absolute_x0_drift": [str(value) for value in drift],
        "max_allowed_drift": str(MAX_EQUITY_ASSET_COLUMN_X0_DRIFT),
    }


def _validate_identity(target: dict) -> dict[str, Any]:
    values = target["values"]
    columns: list[dict[str, str]] = []
    for index, label in enumerate(("CURRENT", "PRIOR")):
        assets = Decimal(values["TOTAL_ASSETS"][index])
        liabilities = Decimal(values["TOTAL_LIABILITIES"][index])
        equity = Decimal(values["TOTAL_EQUITY"][index])
        residual = assets - liabilities - equity
        relative = abs(residual) / max(abs(assets), Decimal("1"))
        if relative > IDENTITY_TOLERANCE:
            raise ValueError(f"{label} A=L+E identity failed")
        columns.append(
            {
                "column": label,
                "total_assets": str(assets),
                "total_liabilities": str(liabilities),
                "total_equity_explicit_pdf": str(equity),
                "identity_residual_cny": str(residual),
                "identity_relative_error": str(relative),
            }
        )
    return {"tolerance": str(IDENTITY_TOLERANCE), "columns": columns}


def _recover_target(raw: bytes, target: dict) -> dict[str, Any]:
    if len(raw) != int(target["source_bytes"]):
        raise ValueError("target source byte length changed")
    with fitz.open(stream=raw, filetype="pdf") as doc:
        events = blocks.formal_statement_events(doc)
        asset_rows = rows_v14._rows_from_words(
            doc[int(target["pages"]["TOTAL_ASSETS"]) - 1]
        )
        liability_rows = rows_v14._rows_from_words(
            doc[int(target["pages"]["TOTAL_LIABILITIES"]) - 1]
        )
        equity_rows = rows_v14._rows_from_words(
            doc[int(target["pages"]["TOTAL_EQUITY"]) - 1]
        )
        asset = _find_exact_row(
            asset_rows, "TOTAL_ASSETS", target["values"]["TOTAL_ASSETS"]
        )
        liability = _find_exact_row(
            liability_rows, "TOTAL_LIABILITIES", target["values"]["TOTAL_LIABILITIES"]
        )
        equity = _find_split_equity(
            equity_rows, target["values"]["TOTAL_EQUITY"]
        )
        if equity["pattern"] != target["split_pattern"]:
            raise ValueError("target split-equity pattern changed")
        event = _validate_group_event(
            events,
            int(target["pages"]["TOTAL_EQUITY"]),
            equity["label_row"],
            target,
        )
        header = _validate_header(doc, event, target)
        alignment = _validate_alignment(asset["pair"], equity["pair"])
        identity = _validate_identity(target)
    return {
        "rows": {
            "TOTAL_ASSETS": asset,
            "TOTAL_LIABILITIES": liability,
            "TOTAL_EQUITY": equity,
        },
        "group_event": event,
        "header_context": header,
        "column_alignment": alignment,
        "identity": identity,
    }


def _promote(current: dict, digest: str, target: dict, evidence: dict) -> dict:
    out = copy.deepcopy(current)
    observations = out.get("observations") or {}
    scoped: dict[str, dict] = {}
    filtered: list[str] = []
    for concept, observation in observations.items():
        if concept in ALLOWED_CONCEPTS:
            continue
        if isinstance(observation, dict) and observation.get("status") == "FOUND":
            filtered.append(concept)
        scoped[concept] = {"status": "NOT_FOUND", "reason": FILTER_REASON}

    selected_pages: dict[str, int] = {}
    selected_aliases: dict[str, str] = {}
    for concept in ALLOWED_CONCEPTS:
        row_evidence = evidence["rows"][concept]
        pair = row_evidence["pair"]
        current_amount = pair[0]
        page = int(target["pages"][concept])
        alias = TARGET_ALIASES[concept]
        scoped[concept] = {
            "concept": concept,
            "status": "FOUND",
            "raw_value": str(current_amount.get("raw") or ""),
            "normalized_cny_value": target["values"][concept][0],
            "unit": "元",
            "unit_multiplier": "1",
            "page": page,
            "matched_alias": alias,
            "extraction_scope": "V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_CANDIDATE",
            "confidence": "HIGH",
        }
        selected_pages[concept] = page
        selected_aliases[concept] = alias

    block = {
        "start_page": int(target["group_anchor_page"]),
        "unit": "元",
        "arbitration": "V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_DUAL_IDENTITY",
        "expected_economic_date": target["economic_date"],
        "identity_tolerance": str(IDENTITY_TOLERANCE),
        "dual_column_identity": evidence["identity"],
        "column_role_gate_pass": True,
        "selected_pages": selected_pages,
        "selected_aliases": selected_aliases,
        "group_event": evidence["group_event"],
        "header_context": evidence["header_context"],
        "column_alignment": evidence["column_alignment"],
        "split_equity_pattern": target["split_pattern"],
        "split_equity_row_gaps": evidence["rows"]["TOTAL_EQUITY"]["row_gaps"],
        "explicit_equity_pdf_text": True,
        "equity_value_inferred_as_assets_minus_liabilities": False,
        "candidate_only": True,
        "production_runtime_generation": "V17.27",
        "candidate_generation": "V17.28",
        "exact_source_sha256": digest,
        "validated_observation_scope": list(ALLOWED_CONCEPTS),
        "filtered_unvalidated_concepts": sorted(filtered),
        "non_balance_values_promoted": False,
        "global_row_tolerance_changed": False,
        "ocr_enabled": False,
        "fuzzy_alias_matching_enabled": False,
    }
    out["observations"] = scoped
    out["tier1_found"] = 0
    out["tier2_found"] = 3
    out["parser_version"] = METHOD
    out["balance_sheet_block"] = block
    out["validation_errors"] = []
    return out


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    """Recover only two accepted split-row GROUP equity source/date identities.

    Every non-target input returns the formal V17.27 object unchanged. A target
    must match the frozen source SHA, byte length, economic date, formal GROUP
    statement role, role-local period/unit evidence, exact row geometry, aligned
    amount columns and two independently closing A=L+E columns.
    """
    current = dict(accepted.parse_pdf_bytes(raw, economic_date))
    digest = hashlib.sha256(raw).hexdigest()
    target = TARGETS.get(digest)
    if target is None or economic_date != target["economic_date"]:
        return current
    if _recovered(current):
        raise ValueError(
            f"V17.27 unexpectedly recovered V17.28 target {target['announcement_id']}"
        )
    evidence = _recover_target(raw, target)
    proposed = _promote(current, digest, target, evidence)
    if not _recovered(proposed):
        raise ValueError(
            f"V17.28 candidate did not recover {target['announcement_id']}"
        )
    return proposed
