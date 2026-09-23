#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import hashlib
import itertools
import json
from decimal import Decimal
from pathlib import Path

import fitz
import requests

import diagnose_stage3_s3g1j_v17_11_remaining as legacy
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard
from stage3_financial_pdf_parser_v12 import parse_pdf_bytes
import stage3_financial_spatial_alias_v17_17 as v17

TARGET_ANNOUNCEMENT_ID = "1219311356"
TARGET_SOURCE_CODE = "600372"
TARGET_ECONOMIC_DATE = "2023-12-31"
TARGET_CATEGORY = "CANDIDATES_NO_VALID_IDENTITY"
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")


def _load_v17_18_target(root: Path) -> dict:
    matches: list[dict] = []
    for path in sorted(glob.glob(str(root / "shard*.json"))):
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        if not report.get("pass"):
            raise ValueError(f"V17.18 shard not pass: {path}")
        for row in report.get("diagnostics") or []:
            if str(row.get("announcement_id")) == TARGET_ANNOUNCEMENT_ID:
                matches.append(row)
    if len(matches) != 1:
        raise ValueError(f"expected one V17.18 target row, got {len(matches)}")
    target = matches[0]
    if target.get("funnel_category") != TARGET_CATEGORY:
        raise ValueError(f"target category changed: {target.get('funnel_category')}")
    if target.get("production_balance_sheet_block") is not None:
        raise ValueError("target unexpectedly has validated production block")
    return target


def _candidate_sets(doc: fitz.Document, economic_date: str) -> tuple[dict, dict]:
    existing, base_funnel = v17.v166._collect_candidates_v16_6(doc, economic_date)
    bridge, bridge_funnel = v17.v1715._collect_adjacent_bridge_candidates(doc, economic_date)
    strict_equity, strict_funnel = v17._collect_strict_same_row_equity_candidates(doc, economic_date)
    merged: dict[str, list[dict]] = {concept: [] for concept in CONCEPTS}
    for concept in CONCEPTS:
        merged[concept].extend(existing.get(concept, []))
        merged[concept].extend(bridge.get(concept, []))
    merged["TOTAL_EQUITY"].extend(strict_equity)
    candidates = v17.v1715._dedupe_candidates(merged)
    return candidates, {
        "base_funnel": base_funnel,
        "bridge_funnel": bridge_funnel,
        "strict_equity_funnel": strict_funnel,
    }


def _identity_row(combo: tuple[dict, dict, dict], doc: fitz.Document, economic_date: str) -> dict:
    assets, liabilities, equity = combo
    a = Decimal(str(assets["value"]))
    l = Decimal(str(liabilities["value"]))
    e = Decimal(str(equity["value"]))
    residual = a - l - e
    denominator = max(abs(a), abs(l), abs(e), Decimal("1"))
    relative = abs(residual) / denominator
    selected = {
        "TOTAL_ASSETS": assets,
        "TOTAL_LIABILITIES": liabilities,
        "TOTAL_EQUITY": equity,
    }
    direct = {
        concept: v17._direct_column_evidence(doc, candidate, economic_date)
        for concept, candidate in selected.items()
    }
    return {
        "identity_residual_cny": str(residual),
        "identity_relative_error": str(relative),
        "within_0_005": relative <= Decimal("0.005"),
        "page_span": max(int(row["page"]) for row in combo) - min(int(row["page"]) for row in combo),
        "anchor_span": max(int(row["statement_anchor_page"]) for row in combo)
        - min(int(row["statement_anchor_page"]) for row in combo),
        "selected": {concept: v17._serialize(candidate) for concept, candidate in selected.items()},
        "direct_column_evidence": direct,
        "all_direct_column_evidence_pass": all(bool((direct.get(concept) or {}).get("pass")) for concept in CONCEPTS),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", required=True)
    parser.add_argument("--v17-11-acceptance", required=True)
    parser.add_argument("--v17-18-candidate-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    accepted = json.loads(Path(args.v17_11_acceptance).read_text(encoding="utf-8"))
    source_rows = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if not accepted.get("pass") or len(source_rows) != 82:
        raise ValueError("not the accepted V17.11 exact-82 source state")
    source = source_rows.get(TARGET_ANNOUNCEMENT_ID)
    if source is None:
        raise ValueError("target not present in accepted source state")

    prior = _load_v17_18_target(Path(args.v17_18_candidate_root))
    rows = [
        row
        for row in legacy._read_rows(Path(args.versions))
        if row["canonical_announcement_id"] == TARGET_ANNOUNCEMENT_ID
    ]
    if len(rows) != 1:
        raise ValueError(f"expected one frozen version row, got {len(rows)}")
    row = rows[0]
    if row["source_code"] != TARGET_SOURCE_CODE or row["economic_date"] != TARGET_ECONOMIC_DATE:
        raise ValueError("target frozen identity changed")

    session = requests.Session()
    raw = legacy._download(session, row["canonical_source_url"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != source["sha256"] or digest != prior["source_sha256"]:
        raise ValueError("target source SHA changed")

    with fitz.open(stream=raw, filetype="pdf") as doc:
        with _mupdf_diagnostic_guard():
            parsed = parse_pdf_bytes(raw, row["economic_date"])
            candidates, funnels = _candidate_sets(doc, row["economic_date"])
            current = v17.diagnose_spatial_balance_sheet_v17_17(doc, row["economic_date"])
            combinations = [
                _identity_row(combo, doc, row["economic_date"])
                for combo in itertools.product(
                    candidates.get("TOTAL_ASSETS", []),
                    candidates.get("TOTAL_LIABILITIES", []),
                    candidates.get("TOTAL_EQUITY", []),
                )
            ]

    combinations.sort(
        key=lambda item: (
            Decimal(item["identity_relative_error"]),
            item["page_span"],
            item["anchor_span"],
        )
    )
    validation_errors = list(parsed.get("validation_errors") or [])
    if parsed.get("balance_sheet_block") is not None or not validation_errors:
        raise ValueError("target no longer remains fail closed")
    if current.get("recovered") or current.get("identity_recovered_before_column_gate"):
        raise ValueError("current V17.17 diagnostic unexpectedly recovered identity")

    serialized_candidates = {
        concept: [
            {
                **v17._serialize(candidate),
                "direct_column_evidence": v17._direct_column_evidence(
                    fitz.open(stream=raw, filetype="pdf"), candidate, row["economic_date"]
                ),
            }
            for candidate in candidates.get(concept, [])
        ]
        for concept in CONCEPTS
    }

    report = {
        "gate": "S3G1J_V17_19_EXACT_ONE_IDENTITY_CANDIDATE_DIAGNOSTIC",
        "pass": True,
        "diagnostic_only": True,
        "no_parser_change": True,
        "no_ocr": True,
        "announcement_id": TARGET_ANNOUNCEMENT_ID,
        "source_code": TARGET_SOURCE_CODE,
        "economic_date": TARGET_ECONOMIC_DATE,
        "canonical_title": row["canonical_title"],
        "canonical_source_url": row["canonical_source_url"],
        "source_sha256": digest,
        "source_bytes": len(raw),
        "v17_18_category": prior["funnel_category"],
        "production_validation_errors": validation_errors,
        "candidate_counts": {concept: len(candidates.get(concept, [])) for concept in CONCEPTS},
        "funnels": funnels,
        "candidates": serialized_candidates,
        "identity_combination_count": len(combinations),
        "identity_combinations": combinations,
        "best_identity_combination": combinations[0] if combinations else None,
        "any_combination_within_0_005": any(item["within_0_005"] for item in combinations),
        "current_v17_17_diagnostic": current,
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "global_row_tolerance_changed": False,
        "e_equals_a_minus_l_inference": False,
        "source_policy_changed": False,
        "stage4_alpha_locked": True,
        "errors": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "announcement_id": TARGET_ANNOUNCEMENT_ID,
                "candidate_counts": report["candidate_counts"],
                "identity_combination_count": len(combinations),
                "best_identity_relative_error": (
                    combinations[0]["identity_relative_error"] if combinations else None
                ),
                "any_combination_within_0_005": report["any_combination_within_0_005"],
                "pass": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
