#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path

import fitz
import requests

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_pdf_parser as base_parser
import stage3_financial_spatial_alias_v17_21 as v21
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard
from stage3_financial_pdf_parser_v13 import parse_pdf_bytes

TARGET_ID = "1221568845"
TARGET_CODE = "600448"
TARGET_DATE = "2024-09-30"
TARGET_SHARD = 0
SOURCE_SHA = "fa72059d35715f20df620691538528f720fe3ae42581c172c853f26799befb93"
PAGES = (5, 6, 7, 8, 12, 13, 14)
EQUITY_ALIASES = tuple(base_parser.TIER2_ALIASES["TOTAL_EQUITY"])
COMBINED_TOTAL_HINTS = (
    "负债和所有者权益（或股东权益）总计",
    "负债和所有者权益合计",
    "负债及股东权益总计",
    "负债和股东权益总计",
)


def _read_versions(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _download(url: str) -> bytes:
    session = requests.Session()
    last: Exception | None = None
    for attempt in range(6):
        try:
            response = session.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 S3G1J-V17.23-600448-equity-geometry",
                    "Referer": "https://www.cninfo.com.cn/",
                },
                timeout=120,
            )
            response.raise_for_status()
            raw = response.content
            if not raw.startswith(b"%PDF"):
                raise ValueError(f"not PDF bytes={len(raw)}")
            return raw
        except Exception as exc:
            last = exc
            if attempt < 5:
                time.sleep(min(2 ** attempt, 12))
    raise RuntimeError(repr(last))


def _row_record(row: dict) -> dict:
    return {
        "text": str(row.get("text") or "")[:1200],
        "y": str(row.get("y")),
        "words": [
            {
                "text": str(word.get("text") or ""),
                "x0": str(word.get("x0")),
                "x1": str(word.get("x1")),
                "y0": str(word.get("y0")),
                "y1": str(word.get("y1")),
            }
            for word in row.get("words") or []
        ],
    }


def _serialize_candidates(candidates: dict[str, list[dict]]) -> dict:
    return {
        concept: [v21._serialize(item) for item in candidates.get(concept, [])]
        for concept in v21.CONCEPTS
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--v17-11-acceptance", required=True)
    ap.add_argument("--v17-21-shard0", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    accepted = json.loads(Path(args.v17_11_acceptance).read_text(encoding="utf-8"))
    source_rows = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if not accepted.get("pass") or TARGET_ID not in source_rows:
        raise ValueError("accepted V17.11 source state mismatch")
    if source_rows[TARGET_ID]["sha256"] != SOURCE_SHA:
        raise ValueError("accepted target SHA mismatch")

    promoted = json.loads(Path(args.v17_21_shard0).read_text(encoding="utf-8"))
    if not promoted.get("pass") or int(promoted.get("shard", -1)) != TARGET_SHARD:
        raise ValueError("V17.21 shard0 evidence mismatch")
    promoted_rows = {str(row["announcement_id"]): row for row in promoted.get("results") or []}
    target_evidence = promoted_rows.get(TARGET_ID)
    if target_evidence is None or target_evidence.get("production_balance_sheet_recovered"):
        raise ValueError("target absent or unexpectedly recovered")
    if target_evidence.get("source_sha256") != SOURCE_SHA or not target_evidence.get("validation_errors"):
        raise ValueError("target source/fail-closed evidence mismatch")

    versions = [row for row in _read_versions(Path(args.versions)) if row["canonical_announcement_id"] == TARGET_ID]
    if len(versions) != 1:
        raise ValueError(f"expected one frozen target row, got {len(versions)}")
    row = versions[0]
    if row["source_code"] != TARGET_CODE or row["economic_date"] != TARGET_DATE:
        raise ValueError("target frozen identity changed")

    raw = _download(row["canonical_source_url"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE_SHA:
        raise ValueError(f"source SHA mismatch: {digest}")

    with fitz.open(stream=raw, filetype="pdf") as doc:
        with _mupdf_diagnostic_guard():
            parsed = parse_pdf_bytes(raw, TARGET_DATE)
            diagnostic = v21.diagnose_spatial_balance_sheet_v17_21(doc, TARGET_DATE)
            events = v21.v17.blocks.formal_statement_events(doc)
            existing, base_funnel = v21.v17.v166._collect_candidates_v16_6(doc, TARGET_DATE)
            bridge, bridge_funnel = v21.v17.v1715._collect_adjacent_bridge_candidates(doc, TARGET_DATE)
            strict_equity, strict_funnel = v21.v17._collect_strict_same_row_equity_candidates(doc, TARGET_DATE)
            reverse_assets, reverse_funnel = v21._collect_reverse_asset_total_candidates(doc, TARGET_DATE)
            merged: dict[str, list[dict]] = defaultdict(list)
            for concept in v21.CONCEPTS:
                merged[concept].extend(existing.get(concept, []))
                merged[concept].extend(bridge.get(concept, []))
            merged["TOTAL_EQUITY"].extend(strict_equity)
            merged["TOTAL_ASSETS"].extend(reverse_assets)
            candidates = v21.v17.v1715._dedupe_candidates(merged)

            page_reports: list[dict] = []
            exact_alias_hits: list[dict] = []
            split_alias_hits: list[dict] = []
            combined_total_hits: list[dict] = []
            for page_1b in PAGES:
                page = doc[page_1b - 1]
                rows = sorted(v14._rows_from_words(page), key=lambda item: float(item["y"]))
                relevant = []
                for index, current in enumerate(rows):
                    text = str(current.get("text") or "")
                    normalized = v14._norm(text)
                    if any(v14._norm(token) in normalized for token in ("权益", "股东", "所有者", "负债和", "负债及", "合计", "总计")):
                        relevant.append({"row_index": index, **_row_record(current)})
                    for alias in EQUITY_ALIASES:
                        geoms = v21.spatial._alias_geometries(current, alias, "TOTAL_EQUITY")
                        for geom in geoms:
                            role = v21.v17.blocks.bind_alias_to_preceding_statement_event(
                                events, page_1b, float(current["y"]), float(geom["x0"])
                            )
                            unit, mult, unit_evidence = v21.v17.blocks.role_local_unit_context(
                                doc, events, role, page_1b, float(current["y"])
                            ) if role is not None else (None, None, None)
                            period = v21.v17.v166._statement_period_evidence(
                                doc, role, unit_evidence, page_1b, TARGET_DATE
                            ) if role is not None and unit_evidence is not None else None
                            amounts = v21.v17.v167._amounts_after_alias(current, float(geom["x1"]))
                            exact_alias_hits.append({
                                "page": page_1b,
                                "row_index": index,
                                "alias": alias,
                                "row": _row_record(current),
                                "alias_x0": str(geom["x0"]),
                                "alias_x1": str(geom["x1"]),
                                "role_event": role,
                                "unit": unit,
                                "unit_multiplier": None if mult is None else str(mult),
                                "unit_evidence": unit_evidence,
                                "period_evidence": period,
                                "amounts_after_alias": [
                                    {"raw": str(item["raw"]), "value": str(item["value"]), "x0": str(item["x0"])}
                                    for item in amounts
                                ],
                            })
                    if index + 1 < len(rows):
                        next_row = rows[index + 1]
                        combined = v14._norm(text + str(next_row.get("text") or ""))
                        for alias in EQUITY_ALIASES:
                            if v14._norm(alias) in combined and v14._norm(alias) not in normalized:
                                split_alias_hits.append({
                                    "page": page_1b,
                                    "alias": alias,
                                    "first_row_index": index,
                                    "first_row": _row_record(current),
                                    "second_row": _row_record(next_row),
                                    "y_delta": str(float(next_row["y"]) - float(current["y"])),
                                })
                        for hint in COMBINED_TOTAL_HINTS:
                            if v14._norm(hint) in combined:
                                combined_total_hits.append({
                                    "page": page_1b,
                                    "hint": hint,
                                    "first_row_index": index,
                                    "first_row": _row_record(current),
                                    "second_row": _row_record(next_row),
                                })
                page_reports.append({
                    "page": page_1b,
                    "text_chars": len((page.get_text("text") or "").strip()),
                    "word_count": len(page.get_text("words") or []),
                    "row_count": len(rows),
                    "relevant_rows": relevant,
                })

    validation_errors = list(parsed.get("validation_errors") or [])
    if parsed.get("balance_sheet_block") is not None or not validation_errors:
        raise ValueError("target no longer fails closed")
    if diagnostic.get("recovered"):
        raise ValueError("target unexpectedly recovered in current production diagnostic")

    group_exact_hits = [
        hit for hit in exact_alias_hits
        if (hit.get("role_event") or {}).get("role") in ("GROUP", "DUAL_GROUP_PARENT")
    ]
    group_split_hits = []
    group_pages = {
        int(event["page"]) for event in events
        if event.get("role") in ("GROUP", "DUAL_GROUP_PARENT")
    }
    for hit in split_alias_hits:
        if hit["page"] >= min(group_pages or {999}) and hit["page"] < 12:
            group_split_hits.append(hit)

    if group_exact_hits:
        conclusion = "DIRECT_GROUP_EQUITY_ALIAS_EXISTS_REVIEW_ROLE_PERIOD_AND_AMOUNT_GATE"
    elif group_split_hits:
        conclusion = "GROUP_EQUITY_ALIAS_SPLIT_ACROSS_ADJACENT_ROWS"
    elif combined_total_hits:
        conclusion = "ONLY_COMBINED_LIABILITIES_AND_EQUITY_TOTAL_VISIBLE_NO_DIRECT_EQUITY_TOTAL"
    else:
        conclusion = "NO_DIRECT_GROUP_EQUITY_TOTAL_EVIDENCE"

    report = {
        "gate": "S3G1J_V17_23_600448_EQUITY_ROW_GEOMETRY_DIAGNOSTIC",
        "pass": True,
        "diagnostic_only": True,
        "no_parser_change": True,
        "no_ocr": True,
        "no_accounting_inference": True,
        "announcement_id": TARGET_ID,
        "source_code": TARGET_CODE,
        "economic_date": TARGET_DATE,
        "canonical_title": row["canonical_title"],
        "canonical_source_url": row["canonical_source_url"],
        "source_sha256": digest,
        "source_bytes": len(raw),
        "production_validation_errors": validation_errors,
        "production_candidate_counts": diagnostic.get("candidate_counts"),
        "production_diagnostic": diagnostic,
        "formal_statement_events": events,
        "candidate_funnels": {
            "base": base_funnel,
            "adjacent_bridge": bridge_funnel,
            "strict_equity": strict_funnel,
            "reverse_asset": reverse_funnel,
        },
        "candidates": _serialize_candidates(candidates),
        "pages": page_reports,
        "exact_equity_alias_hits": exact_alias_hits,
        "group_exact_equity_alias_hits": group_exact_hits,
        "split_equity_alias_hits": split_alias_hits,
        "group_split_equity_alias_hits": group_split_hits,
        "combined_liabilities_equity_total_hits": combined_total_hits,
        "diagnostic_conclusion": conclusion,
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "global_row_tolerance_changed": False,
        "source_policy_changed": False,
        "e_equals_a_minus_l_inference": False,
        "stage4_alpha_locked": True,
        "errors": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "announcement_id": TARGET_ID,
        "candidate_counts": report["production_candidate_counts"],
        "exact_alias_hits": len(exact_alias_hits),
        "group_exact_alias_hits": len(group_exact_hits),
        "split_alias_hits": len(split_alias_hits),
        "group_split_alias_hits": len(group_split_hits),
        "combined_total_hits": len(combined_total_hits),
        "conclusion": conclusion,
        "pass": True,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
