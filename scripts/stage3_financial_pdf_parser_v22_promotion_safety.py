#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
from decimal import Decimal
from typing import Any

import fitz

import stage3_financial_pdf_parser_v21 as accepted
import stage3_financial_pdf_parser_v21_promotion_safety as geom
import stage3_financial_statement_blocks_v16_5 as blocks

METHOD = "V17_30_CROSS_PAGE_EQUITY_PRODUCTION_PROMOTION_EXPERIMENT"
METHODOLOGY_VERSION = "V3.3.14-V17.30-CROSS-PAGE-PROMOTION-EXPERIMENT"
ALLOWED_CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
FILTER_REASON = "V17_30_PROMOTION_EXPERIMENT_UNVALIDATED_NON_BALANCE_CONCEPT"
IDENTITY_TOLERANCE = Decimal("0.005")
FULL_EQUITY_ALIAS = "所有者权益（或股东权益）合计"
TARGET_ALIASES = {
    "TOTAL_ASSETS": "资产总计",
    "TOTAL_LIABILITIES": "负债合计",
    "TOTAL_EQUITY": FULL_EQUITY_ALIAS,
}

ACCEPTED_PROMOTION_PR = 121
ACCEPTED_PROMOTION_HEAD = "2cd84a81b3d4f291aae2ae2cb5b6daf8629ad030"
ACCEPTED_PROMOTION_RUN = 31452374012
ACCEPTED_PROMOTION_ARTIFACT_ID = 9086776910
ACCEPTED_PROMOTION_ARTIFACT_DIGEST = (
    "sha256:d3bb089c7e0524a39b62016f6b6b41539aec99894b874c2940678bee24edebc4"
)
ACCEPTED_PROMOTION_REPORT_SHA256 = (
    "854d79ff1a826b13579ef5014d666994f7b5520f5a0c35dfc7f3d93f5eb41a16"
)

TARGETS: dict[str, dict[str, Any]] = {
    "d765c94532cd41a496d147da72cbff392bce4ff776b41b88d95dcf3f1fb697c8": {
        "announcement_id": "1223347318",
        "source_code": "605289",
        "economic_date": "2025-03-31",
        "economic_date_cn": "2025年3月31日",
        "source_url": "https://static.cninfo.com.cn/finalpage/2025-04-28/1223347318.PDF",
        "source_bytes": 492929,
        "equity_prefix": "所有者权益（或股东权益）合",
        "equity_suffix": "计",
        "next_page_head": [
            "上海罗曼科技股份有限公司2025 年第一季度报告",
            "计",
            "负债和所有者权益（或股东",
            "2,250,857,154.79 2,237,673,819.93",
            "权益）总计",
        ],
        "next_statement_title": "合并利润表",
        "values": {
            "TOTAL_ASSETS": ["2250857154.79", "2237673819.93"],
            "TOTAL_LIABILITIES": ["954370096.74", "961178424.14"],
            "TOTAL_EQUITY": ["1296487058.05", "1276495395.79"],
        },
        "selected_pages": {"TOTAL_ASSETS": 7, "TOTAL_LIABILITIES": 8, "TOTAL_EQUITY": 8},
    },
    "7540a56179783625ac256726480ef32faf85a893549057fe9e6546abfd6ee903": {
        "announcement_id": "1223407043",
        "source_code": "605162",
        "economic_date": "2024-12-31",
        "economic_date_cn": "2024年12月31日",
        "source_url": "https://static.cninfo.com.cn/finalpage/2025-04-30/1223407043.PDF",
        "source_bytes": 1367714,
        "equity_prefix": "所有者权益（或股东权",
        "equity_suffix": "益）合计",
        "next_page_head": [
            "浙江新中港热电股份有限公司2024 年年度报告",
            "益）合计",
            "负债和所有者权益（或",
            "1,885,230,514.78 1,750,850,622.44",
            "股东权益）总计",
        ],
        "next_statement_title": "母公司资产负债表",
        "values": {
            "TOTAL_ASSETS": ["1885230514.78", "1750850622.44"],
            "TOTAL_LIABILITIES": ["564752701.93", "490942613.17"],
            "TOTAL_EQUITY": ["1320477812.85", "1259908009.27"],
        },
        "selected_pages": {"TOTAL_ASSETS": 83, "TOTAL_LIABILITIES": 84, "TOTAL_EQUITY": 84},
    },
}


def _norm(text: str) -> str:
    return geom._normalize(text or "")


def _find_cross_page_equity(
    rows_by_page: dict[int, list[dict[str, Any]]],
    events: list[dict[str, Any]],
    target: dict[str, Any],
) -> dict[str, Any]:
    prefix = _norm(target["equity_prefix"])
    suffix = _norm(target["equity_suffix"])
    full = _norm(FULL_EQUITY_ALIAS)
    if prefix + suffix != full:
        raise ValueError("configured cross-page equity fragments do not exactly complete alias")

    matches: list[dict[str, Any]] = []
    for page, rows in rows_by_page.items():
        for row in rows:
            pair = geom._amount_pair(row, target["values"]["TOTAL_EQUITY"])
            if pair is None:
                continue
            if not _norm(str(row.get("text") or "")).startswith(prefix):
                continue
            event = geom._bind(events, page, row)
            if not event or event.get("role") != "GROUP" or "合并资产负债表" not in str(event.get("line") or ""):
                continue
            try:
                header = geom._validate_header(rows_by_page, event, target)
            except ValueError:
                continue
            next_rows = rows_by_page.get(page + 1, [])
            head = [str(x.get("text") or "") for x in next_rows[: len(target["next_page_head"])]]
            if [_norm(x) for x in head] != [_norm(x) for x in target["next_page_head"]]:
                continue
            if len(head) < 2 or _norm(head[1]) != suffix:
                continue
            boundary_rows = [_norm(str(x.get("text") or "")) for x in next_rows[:12]]
            if not any(_norm(target["next_statement_title"]) in x for x in boundary_rows):
                continue
            matches.append(
                {
                    "page": page,
                    "pair": pair,
                    "row": row,
                    "event": event,
                    "header": header,
                    "suffix_page": page + 1,
                    "next_page_head": head,
                }
            )
    if len(matches) != 1:
        raise ValueError(f"cross-page exact equity candidate count expected=1 actual={len(matches)}")
    return matches[0]


def _recover_target(raw: bytes, target: dict[str, Any]) -> dict[str, Any]:
    formal_snapshot = accepted.parse_pdf_bytes(raw, target["economic_date"])
    validation = list(formal_snapshot.get("validation_errors") or [])
    if int(formal_snapshot.get("tier2_found") or 0) != 3 or "NO_VALIDATED_BALANCE_SHEET_BLOCK" not in validation:
        raise ValueError("formal V17.29 no longer fails closed on exact cross-page target")

    with fitz.open(stream=raw, filetype="pdf") as doc:
        events = blocks.formal_statement_events(doc)
        rows_by_page = geom._rows_by_page(doc)
        found = {
            "TOTAL_ASSETS": geom._find_exact_labeled(rows_by_page, events, target, "TOTAL_ASSETS"),
            "TOTAL_LIABILITIES": geom._find_exact_labeled(rows_by_page, events, target, "TOTAL_LIABILITIES"),
            "TOTAL_EQUITY": _find_cross_page_equity(rows_by_page, events, target),
        }
        keys = {geom._event_key(found[c]["event"]) for c in ALLOWED_CONCEPTS}
        if len(keys) != 1:
            raise ValueError("A/L/E are not bound to exactly one GROUP statement event")
        alignment = geom._validate_alignment(found)
        identity = geom._validate_identity(target)

    if any(Decimal(str(x.get("identity_residual_cny"))) != 0 for x in identity["columns"]):
        raise ValueError("cross-page target dual-column identity is not exact zero")

    return {
        "formal_snapshot": formal_snapshot,
        "rows": found,
        "statement_event": found["TOTAL_EQUITY"]["event"],
        "header_context": found["TOTAL_EQUITY"]["header"],
        "column_alignment": alignment,
        "identity": identity,
        "cross_page": {
            "equity_amount_page": int(found["TOTAL_EQUITY"]["page"]),
            "suffix_page": int(found["TOTAL_EQUITY"]["suffix_page"]),
            "equity_prefix": target["equity_prefix"],
            "equity_suffix": target["equity_suffix"],
            "completed_alias": FULL_EQUITY_ALIAS,
            "next_page_head": found["TOTAL_EQUITY"]["next_page_head"],
            "next_statement_title": target["next_statement_title"],
        },
    }


def _promote_experiment(current: dict, digest: str, target: dict[str, Any], evidence: dict[str, Any]) -> dict:
    out = copy.deepcopy(current)
    observations = out.get("observations") or {}
    scoped: dict[str, dict[str, Any]] = {}
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

    if selected_pages != target["selected_pages"]:
        raise ValueError(f"selected page identity drift {target['announcement_id']} {selected_pages}")

    out["observations"] = scoped
    out["tier1_found"] = 0
    out["tier2_found"] = 3
    out["parser_version"] = METHOD
    out["validation_errors"] = []
    out["balance_sheet_block"] = {
        "start_page": int(evidence["statement_event"]["page"]),
        "unit": "元",
        "arbitration": "V17_30_EXACT_SOURCE_CROSS_PAGE_GROUP_EQUITY_PRODUCTION_PROMOTION_EXPERIMENT",
        "expected_economic_date": target["economic_date"],
        "identity_tolerance": str(IDENTITY_TOLERANCE),
        "dual_column_identity": evidence["identity"],
        "column_role_gate_pass": True,
        "selected_pages": selected_pages,
        "selected_aliases": selected_aliases,
        "group_event": evidence["statement_event"],
        "header_context": evidence["header_context"],
        "column_alignment": evidence["column_alignment"],
        "cross_page_equity_pattern": "ONE_PAGE_EXACT_ALIAS_CONTINUATION",
        "cross_page_equity": evidence["cross_page"],
        "explicit_equity_pdf_text": True,
        "equity_value_inferred_as_assets_minus_liabilities": False,
        "candidate_only": False,
        "production_promotion_experiment_only": True,
        "runtime_promotion_authorized": False,
        "formal_runtime_generation": "V17.29",
        "proposed_runtime_generation": "V17.30_NOT_AUTHORIZED",
        "exact_source_sha256": digest,
        "exact_source_bytes": target["source_bytes"],
        "validated_observation_scope": list(ALLOWED_CONCEPTS),
        "filtered_unvalidated_concepts": sorted(filtered),
        "accepted_promotion_pr": ACCEPTED_PROMOTION_PR,
        "accepted_promotion_head": ACCEPTED_PROMOTION_HEAD,
        "accepted_promotion_run": ACCEPTED_PROMOTION_RUN,
        "accepted_promotion_artifact_id": ACCEPTED_PROMOTION_ARTIFACT_ID,
        "accepted_promotion_artifact_digest": ACCEPTED_PROMOTION_ARTIFACT_DIGEST,
        "accepted_promotion_report_sha256": ACCEPTED_PROMOTION_REPORT_SHA256,
        "non_balance_values_promoted": False,
        "global_row_tolerance_changed": False,
        "ocr_enabled": False,
        "fuzzy_alias_matching_enabled": False,
        "source_policy_relaxed": False,
        "point_in_time_policy_relaxed": False,
        "issuer_gate_relaxed": False,
        "accounting_tolerance_relaxed": False,
    }
    return out


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    """Frozen V17.30 candidate production-promotion implementation.

    Non-target / wrong-date / wrong-byte inputs return the exact formal V17.29
    object. The two exact SHA-bound targets independently re-prove the registered
    cross-page promotion-safety evidence before emitting a safety-only candidate
    object. This module does not activate V17.30 runtime authority.
    """
    current = accepted.parse_pdf_bytes(raw, economic_date)
    digest = hashlib.sha256(raw).hexdigest()
    target = TARGETS.get(digest)
    if target is None or economic_date != target["economic_date"] or len(raw) != int(target["source_bytes"]):
        return current
    evidence = _recover_target(raw, target)
    return _promote_experiment(current, digest, target, evidence)
