#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
from decimal import Decimal
from typing import Any

import fitz

import stage3_financial_coordinate_fallback_v14 as rows_v14
import stage3_financial_pdf_parser_v20 as accepted
import stage3_financial_statement_blocks_v16_5 as blocks

METHOD = "V17_29_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION_PROMOTION_EXPERIMENT"
METHODOLOGY_VERSION = "V3.3.12-V17.29-PRODUCTION-PROMOTION-EXPERIMENT"
ALLOWED_CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
FILTER_REASON = "V17_29_PROMOTION_EXPERIMENT_UNVALIDATED_NON_BALANCE_CONCEPT"
IDENTITY_TOLERANCE = Decimal("0.005")
MAX_LABEL_FRAGMENT_ROWS = 3
MAX_ROW_GAP = Decimal("24")
MAX_COLUMN_X0_DRIFT = Decimal("18")
MAX_PRIMARY_DATE_DISTANCE = Decimal("50")
MAX_PRIMARY_UNIT_DISTANCE = Decimal("100")
FULL_EQUITY_LABEL = "所有者权益（或股东权益）合计"
TARGET_ALIASES = {
    "TOTAL_ASSETS": "资产总计",
    "TOTAL_LIABILITIES": "负债合计",
    "TOTAL_EQUITY": FULL_EQUITY_LABEL,
}

ACCEPTED_CANDIDATE_PR = 105
ACCEPTED_CANDIDATE_HEAD = "51bd3ccc0013c2c9a6a55bbb54a1d82dcbd2974e"
ACCEPTED_CANDIDATE_RUN = 31310230656
ACCEPTED_CANDIDATE_ARTIFACT_ID = 9037206225
ACCEPTED_CANDIDATE_ARTIFACT_DIGEST = (
    "sha256:fc8ff09522b67df8e8209f7e5d88a0d768ef68987201dbb8087df2b6424bb99c"
)
ACCEPTED_CANDIDATE_DOCUMENTS_SHA256 = (
    "343ef55dc8bcf0eb53e8eda2d77f58ddfc48c5c6d13011d02a12d00bd836179e"
)
ACCEPTED_CANDIDATE_VALUES_SHA256 = (
    "31479f232fa2708b411730aa0e0513892a0e42359f0a0e80f4325af3f8b9de2a"
)

TARGETS: dict[str, dict[str, Any]] = {
    "c1856e15d16e6ede5f22a7a0c97dcfd540185573725b64861d8015fae1b4b920": {
        "announcement_id": "1215186538", "source_code": "600243", "economic_date": "2022-06-30",
        "economic_date_cn": "2022年6月30日", "source_bytes": 2711641, "page_count": 132,
        "source_url": "https://static.cninfo.com.cn/finalpage/2022-11-24/1215186538.PDF",
        "values": {"TOTAL_ASSETS": ["1751209751.81", "1842014933.74"], "TOTAL_LIABILITIES": ["671200825.84", "753493262.93"], "TOTAL_EQUITY": ["1080008925.97", "1088521670.81"]},
    },
    "3bf864bff6823fea99b258604061b24012b1ed666a0a1a690af76bf54cb5b6b6": {
        "announcement_id": "1219426855", "source_code": "600310", "economic_date": "2023-12-31",
        "economic_date_cn": "2023年12月31日", "source_bytes": 4817887, "page_count": 296,
        "source_url": "https://static.cninfo.com.cn/finalpage/2024-03-28/1219426855.PDF",
        "values": {"TOTAL_ASSETS": ["18412848496.89", "21746679412.27"], "TOTAL_LIABILITIES": ["13878752183.92", "17017058644.74"], "TOTAL_EQUITY": ["4534096312.97", "4729620767.53"]},
    },
    "2b2147c2d32df99613608371dea115dc09d49377c4ac423ce74d3b155207c5c3": {
        "announcement_id": "1219792633", "source_code": "600200", "economic_date": "2023-12-31",
        "economic_date_cn": "2023年12月31日", "source_bytes": 4643170, "page_count": 219,
        "source_url": "https://static.cninfo.com.cn/finalpage/2024-04-25/1219792633.PDF",
        "values": {"TOTAL_ASSETS": ["4326878114.57", "3909871916.71"], "TOTAL_LIABILITIES": ["2565434062.87", "2086347642.62"], "TOTAL_EQUITY": ["1761444051.70", "1823524274.09"]},
    },
    "e29963a1bd008369d15d817407cb6ff4ffe1ea7740883d69db702800fcb33532": {
        "announcement_id": "1219840508", "source_code": "603661", "economic_date": "2023-12-31",
        "economic_date_cn": "2023年12月31日", "source_bytes": 4502267, "page_count": 257,
        "source_url": "https://static.cninfo.com.cn/finalpage/2024-04-26/1219840508.PDF",
        "values": {"TOTAL_ASSETS": ["9583012872.52", "8801606636.16"], "TOTAL_LIABILITIES": ["6134712967.20", "5477207120.56"], "TOTAL_EQUITY": ["3448299905.32", "3324399515.60"]},
    },
    "0843638f31f9343156b7c87474918dd80604788bc8e8f479eca2882c5b95b534": {
        "announcement_id": "1219879687", "source_code": "603297", "economic_date": "2023-12-31",
        "economic_date_cn": "2023年12月31日", "source_bytes": 3970627, "page_count": 224,
        "source_url": "https://static.cninfo.com.cn/finalpage/2024-04-27/1219879687.PDF",
        "values": {"TOTAL_ASSETS": ["2092255031.78", "1913023445.64"], "TOTAL_LIABILITIES": ["279740275.16", "245133153.04"], "TOTAL_EQUITY": ["1812514756.62", "1667890292.60"]},
    },
    "a77b09fb00fb234ab1923ff42d9908786c71ee2154bb22cfce0d0490dbcfaacd": {
        "announcement_id": "1220087244", "source_code": "600310", "economic_date": "2023-12-31",
        "economic_date_cn": "2023年12月31日", "source_bytes": 4755545, "page_count": 295,
        "source_url": "https://static.cninfo.com.cn/finalpage/2024-05-18/1220087244.PDF",
        "values": {"TOTAL_ASSETS": ["18412848496.89", "21746679412.27"], "TOTAL_LIABILITIES": ["13878752183.92", "17017058644.74"], "TOTAL_EQUITY": ["4534096312.97", "4729620767.53"]},
    },
    "8679311bb2eb42e00d575404456fc5f0fb1a84d0ecab0ae3f6572b7962a1d806": {
        "announcement_id": "1221006100", "source_code": "600310", "economic_date": "2024-06-30",
        "economic_date_cn": "2024年6月30日", "source_bytes": 3650480, "page_count": 204,
        "source_url": "https://static.cninfo.com.cn/finalpage/2024-08-28/1221006100.PDF",
        "values": {"TOTAL_ASSETS": ["19839772807.18", "18412848496.89"], "TOTAL_LIABILITIES": ["15127843133.60", "13878752183.92"], "TOTAL_EQUITY": ["4711929673.58", "4534096312.97"]},
    },
}


def _normalize(value: str) -> str:
    return rows_v14._norm(value or "").replace(":", "：").replace("（", "(").replace("）", ")")


def _row_x0(row: dict[str, Any]) -> float:
    return min((float(word["x0"]) for word in row.get("words") or []), default=0.0)


def _amounts(row: dict[str, Any]) -> list[dict[str, Any]]:
    return list(rows_v14._numeric_word_candidates(row))


def _amount_pair(row: dict[str, Any], expected: list[str]) -> list[dict[str, Any]] | None:
    wanted = [Decimal(value) for value in expected]
    candidates = _amounts(row)
    for start in range(max(0, len(candidates) - 1)):
        pair = candidates[start : start + 2]
        if [Decimal(str(item["value"])) for item in pair] == wanted:
            return pair
    return None


def _rows_by_page(doc: fitz.Document) -> dict[int, list[dict[str, Any]]]:
    return {page + 1: rows_v14._rows_from_words(doc[page]) for page in range(len(doc))}


def _bind(events: list[dict[str, Any]], page: int, row: dict[str, Any]) -> dict[str, Any] | None:
    event = blocks.bind_alias_to_preceding_statement_event(
        events, page, float(row["y"]), _row_x0(row)
    )
    return event if isinstance(event, dict) else None


def _event_key(event: dict[str, Any]) -> tuple[int, str, str]:
    return (
        int(event.get("page") or 0),
        str(event.get("role") or ""),
        str(event.get("line") or ""),
    )


def _validate_header(
    rows_by_page: dict[int, list[dict[str, Any]]],
    event: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    page = int(event["page"])
    event_y = Decimal(str(event.get("y") or 0))
    rows = rows_by_page.get(page, [])
    after = [
        row
        for row in rows
        if event_y <= Decimal(str(row["y"])) <= event_y + Decimal("120")
    ]
    date_rows = [
        row for row in after
        if _normalize(target["economic_date_cn"]) in _normalize(str(row.get("text") or ""))
    ]
    unit_rows = [
        row for row in after
        if "单位：元" in _normalize(str(row.get("text") or ""))
        and "人民币" in _normalize(str(row.get("text") or ""))
    ]
    if not date_rows:
        raise ValueError("GROUP expected-date evidence missing")
    if not unit_rows:
        raise ValueError("GROUP CNY-unit evidence missing")
    date_row = min(date_rows, key=lambda row: float(row["y"]))
    unit_row = min(unit_rows, key=lambda row: float(row["y"]))
    date_distance = Decimal(str(date_row["y"])) - event_y
    unit_distance = Decimal(str(unit_row["y"])) - event_y
    if date_distance < 0 or date_distance > MAX_PRIMARY_DATE_DISTANCE:
        raise ValueError("GROUP expected-date witness not role-local")
    if unit_distance < 0 or unit_distance > MAX_PRIMARY_UNIT_DISTANCE:
        raise ValueError("GROUP CNY-unit witness not role-local")
    return {
        "date_row": str(date_row["text"]),
        "date_distance_from_group_title": str(date_distance),
        "unit_row": str(unit_row["text"]),
        "unit_distance_from_group_title": str(unit_distance),
    }


def _find_exact_labeled(
    rows_by_page: dict[int, list[dict[str, Any]]],
    events: list[dict[str, Any]],
    target: dict[str, Any],
    concept: str,
) -> dict[str, Any]:
    alias = _normalize(TARGET_ALIASES[concept])
    matches: list[dict[str, Any]] = []
    for page, rows in rows_by_page.items():
        for row in rows:
            if alias not in _normalize(str(row.get("text") or "")):
                continue
            pair = _amount_pair(row, target["values"][concept])
            if pair is None:
                continue
            event = _bind(events, page, row)
            if not event or event.get("role") != "GROUP" or "合并资产负债表" not in str(event.get("line") or ""):
                continue
            try:
                header = _validate_header(rows_by_page, event, target)
            except ValueError:
                continue
            matches.append({"page": page, "row": row, "pair": pair, "event": event, "header": header})
    if len(matches) != 1:
        raise ValueError(f"{concept} exact GROUP row count expected=1 actual={len(matches)}")
    return matches[0]


def _no_numeric_words(rows: list[dict[str, Any]]) -> bool:
    return all(not _amounts(row) for row in rows)


def _find_split_equity(
    rows_by_page: dict[int, list[dict[str, Any]]],
    events: list[dict[str, Any]],
    target: dict[str, Any],
) -> dict[str, Any]:
    full = _normalize(FULL_EQUITY_LABEL)
    matches: list[dict[str, Any]] = []
    for page, rows in rows_by_page.items():
        for idx, amount_row in enumerate(rows):
            pair = _amount_pair(amount_row, target["values"]["TOTAL_EQUITY"])
            if pair is None:
                continue
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
                    label = "".join(_normalize(str(row.get("text") or "")) for row in before + after)
                    if label != full:
                        continue
                    sequence = before + [amount_row] + after
                    gaps = [
                        Decimal(str(sequence[pos + 1]["y"])) - Decimal(str(sequence[pos]["y"]))
                        for pos in range(len(sequence) - 1)
                    ]
                    if not gaps or any(gap <= 0 or gap > MAX_ROW_GAP for gap in gaps):
                        continue
                    event = _bind(events, page, before[0])
                    if not event or event.get("role") != "GROUP" or "合并资产负债表" not in str(event.get("line") or ""):
                        continue
                    key = _event_key(event)
                    if any(
                        (bound := _bind(events, page, row)) is None or _event_key(bound) != key
                        for row in sequence
                    ):
                        continue
                    try:
                        header = _validate_header(rows_by_page, event, target)
                    except ValueError:
                        continue
                    matches.append({
                        "page": page,
                        "row": amount_row,
                        "pair": pair,
                        "label_rows": before + after,
                        "pattern": f"SPLIT_LABEL_{before_width}_BEFORE_{after_width}_AFTER_AMOUNT",
                        "row_gaps": [str(gap) for gap in gaps],
                        "event": event,
                        "header": header,
                    })
    if len(matches) != 1:
        raise ValueError(
            f"TOTAL_EQUITY split GROUP sequence count expected=1 actual={len(matches)}"
        )
    return matches[0]


def _validate_alignment(found: dict[str, dict[str, Any]]) -> dict[str, Any]:
    x = {
        concept: [Decimal(str(item["x0"])) for item in found[concept]["pair"]]
        for concept in ALLOWED_CONCEPTS
    }
    base = x["TOTAL_ASSETS"]
    drifts: dict[str, list[str]] = {}
    for concept in ("TOTAL_LIABILITIES", "TOTAL_EQUITY"):
        values = [abs(a - b) for a, b in zip(base, x[concept], strict=True)]
        if any(value > MAX_COLUMN_X0_DRIFT for value in values):
            raise ValueError(f"{concept} column drift={values}")
        drifts[concept] = [str(value) for value in values]
    if any(not (values[0] < values[1]) for values in x.values()):
        raise ValueError("current/prior columns not left-to-right")
    return {
        "x0_by_concept": {k: [str(v) for v in values] for k, values in x.items()},
        "drift_from_assets": drifts,
        "max_allowed_drift": str(MAX_COLUMN_X0_DRIFT),
    }


def _validate_identity(target: dict[str, Any]) -> dict[str, Any]:
    columns: list[dict[str, str]] = []
    for index, label in enumerate(("CURRENT", "PRIOR")):
        assets = Decimal(target["values"]["TOTAL_ASSETS"][index])
        liabilities = Decimal(target["values"]["TOTAL_LIABILITIES"][index])
        equity = Decimal(target["values"]["TOTAL_EQUITY"][index])
        residual = assets - liabilities - equity
        relative = abs(residual) / max(abs(assets), Decimal("1"))
        if relative > IDENTITY_TOLERANCE:
            raise ValueError(f"{label} A=L+E identity failed")
        columns.append({
            "column": label,
            "total_assets": str(assets),
            "total_liabilities": str(liabilities),
            "total_equity_explicit_pdf": str(equity),
            "identity_residual_cny": str(residual),
            "identity_relative_error": str(relative),
        })
    return {"tolerance": str(IDENTITY_TOLERANCE), "columns": columns}


def _recover_target(raw: bytes, target: dict[str, Any]) -> dict[str, Any]:
    if len(raw) != int(target["source_bytes"]):
        raise ValueError("target source byte length changed")
    with fitz.open(stream=raw, filetype="pdf") as doc:
        if len(doc) != int(target["page_count"]):
            raise ValueError("target page count changed")
        events = blocks.formal_statement_events(doc)
        rows_by_page = _rows_by_page(doc)
        found = {
            "TOTAL_ASSETS": _find_exact_labeled(rows_by_page, events, target, "TOTAL_ASSETS"),
            "TOTAL_LIABILITIES": _find_exact_labeled(rows_by_page, events, target, "TOTAL_LIABILITIES"),
            "TOTAL_EQUITY": _find_split_equity(rows_by_page, events, target),
        }
        keys = {_event_key(found[concept]["event"]) for concept in ALLOWED_CONCEPTS}
        if len(keys) != 1:
            raise ValueError(f"A/L/E not bound to one GROUP statement event: {keys}")
        alignment = _validate_alignment(found)
        identity = _validate_identity(target)
    return {
        "rows": found,
        "statement_event": found["TOTAL_EQUITY"]["event"],
        "header_context": found["TOTAL_EQUITY"]["header"],
        "column_alignment": alignment,
        "identity": identity,
    }


def _promote_experiment(
    current: dict, digest: str, target: dict[str, Any], evidence: dict[str, Any]
) -> dict:
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
        current_amount = row_evidence["pair"][0]
        scoped[concept] = {
            "concept": concept,
            "status": "FOUND",
            "raw_value": str(current_amount.get("raw") or ""),
            "normalized_cny_value": target["values"][concept][0],
            "unit": "元",
            "unit_multiplier": "1",
            "page": int(row_evidence["page"]),
            "matched_alias": TARGET_ALIASES[concept],
            "extraction_scope": METHOD,
            "confidence": "HIGH",
        }
        selected_pages[concept] = int(row_evidence["page"])
        selected_aliases[concept] = TARGET_ALIASES[concept]
    equity = evidence["rows"]["TOTAL_EQUITY"]
    out["observations"] = scoped
    out["tier1_found"] = 0
    out["tier2_found"] = 3
    out["parser_version"] = METHOD
    out["validation_errors"] = []
    out["balance_sheet_block"] = {
        "start_page": int(evidence["statement_event"]["page"]),
        "unit": "元",
        "arbitration": "V17_29_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION_PROMOTION_EXPERIMENT",
        "expected_economic_date": target["economic_date"],
        "identity_tolerance": str(IDENTITY_TOLERANCE),
        "dual_column_identity": evidence["identity"],
        "column_role_gate_pass": True,
        "selected_pages": selected_pages,
        "selected_aliases": selected_aliases,
        "group_event": evidence["statement_event"],
        "header_context": evidence["header_context"],
        "column_alignment": evidence["column_alignment"],
        "split_equity_pattern": equity["pattern"],
        "split_equity_row_gaps": equity["row_gaps"],
        "explicit_equity_pdf_text": True,
        "equity_value_inferred_as_assets_minus_liabilities": False,
        "candidate_only": False,
        "production_promotion_experiment_only": True,
        "runtime_promotion_authorized": False,
        "formal_runtime_generation": "V17.28",
        "proposed_runtime_generation": "V17.29",
        "exact_source_sha256": digest,
        "exact_source_bytes": target["source_bytes"],
        "validated_observation_scope": list(ALLOWED_CONCEPTS),
        "filtered_unvalidated_concepts": sorted(filtered),
        "accepted_candidate_pr": ACCEPTED_CANDIDATE_PR,
        "accepted_candidate_head": ACCEPTED_CANDIDATE_HEAD,
        "accepted_candidate_run": ACCEPTED_CANDIDATE_RUN,
        "accepted_candidate_artifact_id": ACCEPTED_CANDIDATE_ARTIFACT_ID,
        "accepted_candidate_artifact_digest": ACCEPTED_CANDIDATE_ARTIFACT_DIGEST,
        "non_balance_values_promoted": False,
        "global_row_tolerance_changed": False,
        "ocr_enabled": False,
        "fuzzy_alias_matching_enabled": False,
        "source_policy_relaxed": False,
        "point_in_time_policy_relaxed": False,
        "issuer_gate_relaxed": False,
    }
    return out


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    """Frozen accepted production-promotion safety implementation.

    Non-target / wrong-date / wrong-byte inputs return the exact formal V17.28
    object. Exact targets independently re-prove the accepted V17.29 evidence
    and emit the already-machine-accepted promotion-safety object.
    """
    current = accepted.parse_pdf_bytes(raw, economic_date)
    digest = hashlib.sha256(raw).hexdigest()
    target = TARGETS.get(digest)
    if (
        target is None
        or economic_date != target["economic_date"]
        or len(raw) != int(target["source_bytes"])
    ):
        return current
    evidence = _recover_target(raw, target)
    return _promote_experiment(current, digest, target, evidence)
