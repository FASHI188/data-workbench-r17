#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import fitz
import requests

import diagnose_stage3_s3g1j_v17_26_p0 as base
import diagnose_stage3_s3g1j_p0_v17_24 as prior_diagnostic
import stage3_financial_spatial_alias_v17_24 as spatial
import stage3_financial_statement_blocks_v17_25 as generic_witness

CONCEPTS = base.CONCEPTS
IDENTITY_TOLERANCE = spatial.v21.spatial.IDENTITY_TOLERANCE
MAX_PAGE_SPAN = spatial.v21.spatial.MAX_PAGE_SPAN
MAX_ANCHOR_SPAN = spatial.v21.spatial.MAX_ANCHOR_SPAN


def _collect_candidates(
    doc: fitz.Document, economic_date: str
) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    existing, base_funnel = spatial.v21.v17.v166._collect_candidates_v16_6(
        doc, economic_date
    )
    bridge, bridge_funnel = spatial.v21.v17.v1715._collect_adjacent_bridge_candidates(
        doc, economic_date
    )
    strict_equity, strict_funnel = (
        spatial.v21.v17._collect_strict_same_row_equity_candidates(
            doc, economic_date
        )
    )
    reverse_assets, reverse_funnel = spatial.v21._collect_reverse_asset_total_candidates(
        doc, economic_date
    )
    corrupted_equity, corrupted_funnel = spatial._collect_exact_corrupted_equity_candidates(
        doc, economic_date
    )

    merged: dict[str, list[dict]] = defaultdict(list)
    for concept in CONCEPTS:
        merged[concept].extend(existing.get(concept, []))
        merged[concept].extend(bridge.get(concept, []))
    merged["TOTAL_EQUITY"].extend(strict_equity)
    merged["TOTAL_EQUITY"].extend(corrupted_equity)
    merged["TOTAL_ASSETS"].extend(reverse_assets)
    candidates = spatial.v21.v17.v1715._dedupe_candidates(merged)
    funnels = {
        "base_funnel": base_funnel,
        "bridge_funnel": bridge_funnel,
        "strict_equity_funnel": strict_funnel,
        "reverse_asset_funnel": reverse_funnel,
        "corrupted_equity_funnel": corrupted_funnel,
    }
    return candidates, funnels


def _serialize_candidates(candidates: dict[str, list[dict]]) -> dict[str, list[dict]]:
    return {
        concept: [spatial._serialize(candidate) for candidate in candidates.get(concept, [])]
        for concept in CONCEPTS
    }


def _identity_combinations(candidates: dict[str, list[dict]]) -> list[dict[str, Any]]:
    combinations: list[dict[str, Any]] = []
    for asset_index, assets in enumerate(candidates.get("TOTAL_ASSETS", [])):
        for liability_index, liabilities in enumerate(
            candidates.get("TOTAL_LIABILITIES", [])
        ):
            for equity_index, equity in enumerate(candidates.get("TOTAL_EQUITY", [])):
                trio = (assets, liabilities, equity)
                roles = sorted({str(item.get("statement_role") or "") for item in trio})
                pages = [int(item["page"]) for item in trio]
                anchors = [int(item["statement_anchor_page"]) for item in trio]
                page_span = max(pages) - min(pages)
                anchor_span = max(anchors) - min(anchors)
                residual = assets["value"] - (
                    liabilities["value"] + equity["value"]
                )
                relative_error = abs(residual) / max(
                    abs(assets["value"]),
                    abs(liabilities["value"] + equity["value"]),
                    Decimal("1"),
                )
                role_pass = set(roles).issubset({"GROUP", "DUAL_GROUP_PARENT"})
                page_span_pass = page_span <= MAX_PAGE_SPAN
                anchor_span_pass = anchor_span <= MAX_ANCHOR_SPAN
                tolerance_pass = relative_error <= IDENTITY_TOLERANCE
                combinations.append(
                    {
                        "candidate_indexes": {
                            "TOTAL_ASSETS": asset_index,
                            "TOTAL_LIABILITIES": liability_index,
                            "TOTAL_EQUITY": equity_index,
                        },
                        "values": {
                            "TOTAL_ASSETS": str(assets["value"]),
                            "TOTAL_LIABILITIES": str(liabilities["value"]),
                            "TOTAL_EQUITY": str(equity["value"]),
                        },
                        "pages": {
                            "TOTAL_ASSETS": int(assets["page"]),
                            "TOTAL_LIABILITIES": int(liabilities["page"]),
                            "TOTAL_EQUITY": int(equity["page"]),
                        },
                        "statement_anchor_pages": {
                            "TOTAL_ASSETS": int(assets["statement_anchor_page"]),
                            "TOTAL_LIABILITIES": int(liabilities["statement_anchor_page"]),
                            "TOTAL_EQUITY": int(equity["statement_anchor_page"]),
                        },
                        "aliases": {
                            "TOTAL_ASSETS": str(assets.get("alias") or ""),
                            "TOTAL_LIABILITIES": str(liabilities.get("alias") or ""),
                            "TOTAL_EQUITY": str(equity.get("alias") or ""),
                        },
                        "roles": roles,
                        "identity_residual_cny": str(residual),
                        "identity_absolute_residual_cny": str(abs(residual)),
                        "identity_relative_error": str(relative_error),
                        "page_span": page_span,
                        "anchor_span": anchor_span,
                        "role_pass": role_pass,
                        "page_span_pass": page_span_pass,
                        "anchor_span_pass": anchor_span_pass,
                        "identity_tolerance": str(IDENTITY_TOLERANCE),
                        "identity_tolerance_pass": tolerance_pass,
                        "eligible_identity": bool(
                            role_pass
                            and page_span_pass
                            and anchor_span_pass
                            and tolerance_pass
                        ),
                    }
                )
    combinations.sort(
        key=lambda row: (
            Decimal(row["identity_relative_error"]),
            Decimal(row["identity_absolute_residual_cny"]),
            row["page_span"],
            row["anchor_span"],
            tuple(row["candidate_indexes"].values()),
        )
    )
    return combinations


def _failure_stage(
    witness_count: int,
    counts: dict[str, int],
    combinations: list[dict[str, Any]],
) -> str:
    if witness_count <= 0:
        return "NO_GENERIC_GROUP_WITNESS"
    if not all(counts.get(concept, 0) > 0 for concept in CONCEPTS):
        return "PERIOD_OR_ROLE_GATE_REMOVED_ALE_CANDIDATES"
    if combinations and not any(row["eligible_identity"] for row in combinations):
        return "ALE_CANDIDATES_PRESENT_NO_IDENTITY_WITHIN_TOLERANCE"
    if any(row["eligible_identity"] for row in combinations):
        return "IDENTITY_PRESENT_BUT_DOWNSTREAM_COLUMN_GATE_FAILED"
    return "UNCLASSIFIED_CANDIDATE_FAILURE"


def _candidate_diagnostic(
    raw: bytes, economic_date: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict]], list[dict[str, Any]]]:
    with fitz.open(stream=raw, filetype="pdf") as doc:
        witness = generic_witness.diagnose_generic_group_witness(doc)
        original = spatial.v21.v17.blocks.formal_statement_events
        spatial.v21.v17.blocks.formal_statement_events = (
            generic_witness.formal_statement_events
        )
        try:
            diagnostic = spatial.diagnose_spatial_balance_sheet_v17_24(
                doc, economic_date
            )
            candidates, funnels = _collect_candidates(doc, economic_date)
        finally:
            spatial.v21.v17.blocks.formal_statement_events = original
    # The public diagnostic and the explicit collector must agree exactly.
    counts = {concept: len(candidates.get(concept, [])) for concept in CONCEPTS}
    if counts != {
        concept: int((diagnostic.get("candidate_counts") or {}).get(concept) or 0)
        for concept in CONCEPTS
    }:
        raise ValueError("candidate detail counts disagree with public diagnostic")
    for funnel_name, funnel in funnels.items():
        if dict(funnel) != dict(diagnostic.get(funnel_name) or {}):
            raise ValueError(f"candidate detail funnel disagrees: {funnel_name}")
    return (
        witness,
        diagnostic,
        _serialize_candidates(candidates),
        _identity_combinations(candidates),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p0-ledger", required=True)
    parser.add_argument("--documents", required=True)
    parser.add_argument("--base-report", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    p0_path = Path(args.p0_ledger)
    documents_path = Path(args.documents)
    base_report = json.loads(Path(args.base_report).read_text(encoding="utf-8"))
    if base_report.get("pass") is not True or base_report.get("processed_count") != 21:
        raise ValueError("base P0 diagnostic is not accepted")
    if base.sha256_file(documents_path) != base.DOCUMENTS_GZIP_SHA256:
        raise ValueError("V17.26 documents gzip SHA mismatch")
    if base.sha256_gzip_plaintext(documents_path) != base.DOCUMENTS_PLAINTEXT_SHA256:
        raise ValueError("V17.26 documents plaintext SHA mismatch")

    targets = base.load_p0(p0_path)
    target_ids = {row["announcement_id"] for row in targets}
    documents = prior_diagnostic.load_full_documents(
        documents_path, base.DOCUMENTS_GZIP_SHA256, target_ids
    )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "data-workbench-r17-stage3-v17-26-p0-candidate-spatial/2.0",
            "Accept": "application/pdf,*/*;q=0.8",
        }
    )

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    source_sha_matches = 0
    for index, target in enumerate(targets, 1):
        aid = target["announcement_id"]
        try:
            evidence = prior_diagnostic.source_evidence(documents[aid])
            raw = prior_diagnostic.download(session, evidence["url"])
            actual_sha = hashlib.sha256(raw).hexdigest()
            if actual_sha != evidence["sha256"] or len(raw) != evidence["bytes"]:
                raise ValueError("source identity changed")
            source_sha_matches += 1
            witness, diagnostic, candidates, combinations = _candidate_diagnostic(
                raw, target["economic_date"]
            )
            counts = {
                concept: int((diagnostic.get("candidate_counts") or {}).get(concept) or 0)
                for concept in CONCEPTS
            }
            witness_count = int(witness.get("promoted_generic_group_count") or 0)
            results.append(
                {
                    "announcement_id": aid,
                    "source_code": target["source_code"],
                    "report_family": target["report_family"],
                    "economic_date": target["economic_date"],
                    "source_sha256": actual_sha,
                    "generic_group_witness_count": witness_count,
                    "candidate_counts": counts,
                    "candidates": candidates,
                    "identity_combinations": combinations,
                    "best_identity_combination": combinations[0] if combinations else None,
                    "candidate_failure_stage": _failure_stage(
                        witness_count, counts, combinations
                    ),
                    "candidate_diagnostic": diagnostic,
                    "candidate_recovered": bool(diagnostic.get("recovered")),
                    "identity_recovered_before_column_gate": bool(
                        diagnostic.get("identity_recovered_before_column_gate")
                    ),
                    "column_role_gate": diagnostic.get("column_role_gate") or {},
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "announcement_id": aid,
                    "source_code": target.get("source_code", ""),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(
            f"S3G1J_V17_26_P0_CANDIDATE_SPATIAL {index}/{len(targets)} aid={aid}",
            flush=True,
        )

    results.sort(key=lambda row: (row["economic_date"], row["announcement_id"]))
    promoted_ids = sorted(
        row["announcement_id"]
        for row in results
        if row["generic_group_witness_count"] > 0
    )
    pattern_counts = Counter(
        json.dumps(row["candidate_counts"], sort_keys=True, separators=(",", ":"))
        for row in results
    )
    promoted_pattern_counts = Counter(
        json.dumps(row["candidate_counts"], sort_keys=True, separators=(",", ":"))
        for row in results
        if row["generic_group_witness_count"] > 0
    )
    promoted_failure_stages = Counter(
        row["candidate_failure_stage"]
        for row in results
        if row["generic_group_witness_count"] > 0
    )
    column_gate_reasons = Counter(
        str((row["column_role_gate"] or {}).get("reason") or "")
        for row in results
        if row["generic_group_witness_count"] > 0
    )
    promoted_funnel_totals: dict[str, Counter[str]] = {
        "base_funnel": Counter(),
        "bridge_funnel": Counter(),
        "strict_equity_funnel": Counter(),
        "reverse_asset_funnel": Counter(),
        "corrupted_equity_funnel": Counter(),
    }
    for row in results:
        if row["generic_group_witness_count"] <= 0:
            continue
        diagnostic = row["candidate_diagnostic"]
        for funnel in promoted_funnel_totals:
            promoted_funnel_totals[funnel].update(diagnostic.get(funnel) or {})

    recovered_ids = sorted(
        row["announcement_id"] for row in results if row["candidate_recovered"]
    )
    identity_ids = sorted(
        row["announcement_id"]
        for row in results
        if row["identity_recovered_before_column_gate"]
    )
    eligible_combination_ids = sorted(
        row["announcement_id"]
        for row in results
        if any(item["eligible_identity"] for item in row["identity_combinations"])
    )
    passed = (
        not failures
        and len(results) == 21
        and source_sha_matches == 21
        and promoted_ids == sorted(base.EXPECTED_GENERIC_PROMOTED_IDS)
        and promoted_failure_stages
        == {
            "ALE_CANDIDATES_PRESENT_NO_IDENTITY_WITHIN_TOLERANCE": 5,
            "PERIOD_OR_ROLE_GATE_REMOVED_ALE_CANDIDATES": 2,
        }
        and not recovered_ids
        and not identity_ids
        and not eligible_combination_ids
    )
    report = {
        "gate": "S3G1J_V17_26_CURRENT_P0_GENERIC_CANDIDATE_SPATIAL_V2",
        "base_diagnostic_gate": base_report.get("gate"),
        "source_classifier_run": base.SOURCE_CLASSIFIER_RUN,
        "source_full_basis_run": base.SOURCE_FULL_RUN,
        "runtime_generation": "V17.26",
        "candidate_only_statement_role_override": True,
        "formal_runtime_changed": False,
        "identity_tolerance": str(IDENTITY_TOLERANCE),
        "max_page_span": MAX_PAGE_SPAN,
        "max_anchor_span": MAX_ANCHOR_SPAN,
        "target_count": 21,
        "processed_count": len(results),
        "source_sha_match_count": source_sha_matches,
        "generic_group_witness_promoted_count": len(promoted_ids),
        "generic_group_witness_promoted_announcement_ids": promoted_ids,
        "candidate_count_patterns": dict(sorted(pattern_counts.items())),
        "promoted_candidate_count_patterns": dict(
            sorted(promoted_pattern_counts.items())
        ),
        "promoted_candidate_failure_stage_counts": dict(
            sorted(promoted_failure_stages.items())
        ),
        "eligible_identity_combination_count": len(eligible_combination_ids),
        "eligible_identity_combination_announcement_ids": eligible_combination_ids,
        "identity_recovered_before_column_gate_count": len(identity_ids),
        "identity_recovered_before_column_gate_announcement_ids": identity_ids,
        "candidate_recovered_count": len(recovered_ids),
        "candidate_recovered_announcement_ids": recovered_ids,
        "promoted_column_gate_reason_counts": dict(
            sorted(column_gate_reasons.items())
        ),
        "promoted_funnel_totals": {
            key: dict(sorted(value.items()))
            for key, value in promoted_funnel_totals.items()
        },
        "results": results,
        "execution_failures": failures,
        "parser_changed": False,
        "runtime_authority_changed": False,
        "production_data_changed": False,
        "trained_model_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_locked": True,
        "pass": passed,
        "errors": failures,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "results"},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
