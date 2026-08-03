#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import requests

import build_stage3_s3g1j_v17_28_candidate_full as base


UNRESOLVED_TIE_RESOLUTIONS = frozenset(
    {"TIE_SOURCE_INCOMPLETE", "TIE_VALUE_CONFLICT"}
)


def is_unresolved_tie(row: dict[str, str]) -> bool:
    return row.get("tie_resolution") in UNRESOLVED_TIE_RESOLUTIONS


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("--documents", required=True)
    cli.add_argument("--values", required=True)
    cli.add_argument("--out", required=True)
    args = cli.parse_args()

    documents_path = Path(args.documents)
    values_path = Path(args.values)
    if base.sha256(documents_path) != base.SOURCE_DOCUMENTS_SHA256:
        raise ValueError("accepted V17.27 document ledger SHA changed")
    if base.sha256(values_path) != base.SOURCE_VALUES_SHA256:
        raise ValueError("accepted V17.27 value ledger SHA changed")
    source_docs = base.read_gz(documents_path)
    source_values = base.read_gz(values_path)
    if len(source_docs) != base.SOURCE_DOCUMENT_ROWS:
        raise ValueError(f"source document count changed {len(source_docs)}")
    if len(source_values) != base.SOURCE_NUMERIC_ROWS:
        raise ValueError(f"source numeric count changed {len(source_values)}")

    source_doc_by_aid = {row["announcement_id"]: row for row in source_docs}
    if len(source_doc_by_aid) != len(source_docs):
        raise ValueError("duplicate source document identity")
    if not set(base.TARGETS_BY_AID).issubset(source_doc_by_aid):
        raise ValueError("candidate target population absent")
    if any(row["announcement_id"] in base.TARGETS_BY_AID for row in source_values):
        raise ValueError("candidate targets already contain numeric rows")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "data-workbench-r17-v17-28-split-equity-candidate-v2/1.0",
            "Accept": "application/pdf,*/*;q=0.8",
        }
    )
    target_docs: dict[str, dict[str, str]] = {}
    target_values: list[dict[str, str]] = []
    details: list[dict] = []
    for aid in sorted(base.TARGETS_BY_AID):
        document, numeric, detail = base.build_target(
            session, source_doc_by_aid[aid]
        )
        target_docs[aid] = document
        target_values.extend(numeric)
        details.append(detail)

    if len(target_docs) != 2 or len(target_values) != base.TARGET_NUMERIC_ROWS:
        raise ValueError(
            f"candidate target output changed docs={len(target_docs)} values={len(target_values)}"
        )
    if Counter(row["announcement_id"] for row in target_values) != Counter(
        {aid: 3 for aid in base.TARGETS_BY_AID}
    ):
        raise ValueError("candidate target numeric distribution changed")

    candidate_docs = [
        dict(target_docs.get(row["announcement_id"], row)) for row in source_docs
    ]
    candidate_values = [dict(row) for row in source_values] + [
        dict(row) for row in target_values
    ]
    candidate_docs.sort(key=lambda row: row["announcement_id"])
    candidate_values.sort(key=lambda row: (row["announcement_id"], row["concept"]))

    non_target_source_docs = [
        row for row in source_docs if row["announcement_id"] not in base.TARGETS_BY_AID
    ]
    non_target_candidate_docs = [
        row for row in candidate_docs if row["announcement_id"] not in base.TARGETS_BY_AID
    ]
    base.require_exact_rows(
        "non-target document",
        non_target_source_docs,
        non_target_candidate_docs,
        tuple(base.common.DOC_FIELDS),
    )

    existing_candidate_values = [
        row
        for row in candidate_values
        if row["announcement_id"] not in base.TARGETS_BY_AID
    ]
    base.require_exact_rows(
        "existing numeric",
        source_values,
        existing_candidate_values,
        tuple(base.common.NUMERIC_FIELDS),
    )

    source_errors = sum(
        row["document_status"] != "PASS" or bool(row["document_error"])
        for row in source_docs
    )
    candidate_errors = sum(
        row["document_status"] != "PASS" or bool(row["document_error"])
        for row in candidate_docs
    )
    source_ties = sum(is_unresolved_tie(row) for row in source_docs)
    candidate_ties = sum(is_unresolved_tie(row) for row in candidate_docs)
    source_tie_taxonomy = Counter(
        row["tie_resolution"] for row in source_docs if is_unresolved_tie(row)
    )
    candidate_tie_taxonomy = Counter(
        row["tie_resolution"] for row in candidate_docs if is_unresolved_tie(row)
    )
    if source_tie_taxonomy != Counter(
        {"TIE_SOURCE_INCOMPLETE": 1276, "TIE_VALUE_CONFLICT": 14}
    ):
        raise ValueError(f"source unresolved tie taxonomy changed {source_tie_taxonomy}")
    if candidate_tie_taxonomy != Counter(
        {"TIE_SOURCE_INCOMPLETE": 1274, "TIE_VALUE_CONFLICT": 14}
    ):
        raise ValueError(
            f"candidate unresolved tie taxonomy changed {candidate_tie_taxonomy}"
        )
    if (source_errors, candidate_errors) != (
        base.SOURCE_ERRORS,
        base.CANDIDATE_ERRORS,
    ):
        raise ValueError(
            f"candidate error accounting source={source_errors} candidate={candidate_errors}"
        )
    if (source_ties, candidate_ties) != (
        base.SOURCE_UNRESOLVED_TIES,
        base.CANDIDATE_UNRESOLVED_TIES,
    ):
        raise ValueError(
            f"candidate tie accounting source={source_ties} candidate={candidate_ties}"
        )
    if len(candidate_values) != base.CANDIDATE_NUMERIC_ROWS:
        raise ValueError(f"candidate numeric count changed {len(candidate_values)}")

    source_counter = Counter(
        base.baseline_compare._numeric_tuple(row) for row in source_values
    )
    existing_counter = Counter(
        base.baseline_compare._numeric_tuple(row)
        for row in existing_candidate_values
    )
    source_semantic_sha = base.baseline_compare.semantic_multiset_sha(source_counter)
    candidate_existing_semantic_sha = base.baseline_compare.semantic_multiset_sha(
        existing_counter
    )
    if source_counter != existing_counter:
        raise ValueError("existing numeric 22-field multiset changed")
    if source_semantic_sha != base.SOURCE_EXISTING_NUMERIC_SEMANTIC_SHA256:
        raise ValueError(f"source semantic SHA changed {source_semantic_sha}")
    if candidate_existing_semantic_sha != source_semantic_sha:
        raise ValueError("candidate existing numeric semantic SHA changed")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    docs_out = out / "stage3_financial_documents_v17_28_candidate.csv.gz"
    values_out = out / "stage3_financial_values_v17_28_candidate.csv.gz"
    base.common.write_gz(docs_out, base.common.DOC_FIELDS, candidate_docs)
    base.common.write_gz(values_out, base.common.NUMERIC_FIELDS, candidate_values)

    report = {
        "gate": "S3G1J_V17_28_SPLIT_GROUP_EQUITY_CANDIDATE_SAFETY_V2",
        "failed_v1_contract_reason": (
            "V1 counted only TIE_SOURCE_INCOMPLETE. The accepted finalizer audit "
            "defines unresolved ties as TIE_SOURCE_INCOMPLETE plus TIE_VALUE_CONFLICT."
        ),
        "candidate_only": True,
        "formal_runtime_generation": "V17.27",
        "candidate_generation": "V17.28",
        "parser_method": base.candidate.METHOD,
        "methodology_version": base.candidate.METHODOLOGY_VERSION,
        "target_announcement_ids": sorted(base.TARGETS_BY_AID),
        "target_count": 2,
        "target_numeric_rows": base.TARGET_NUMERIC_ROWS,
        "target_details": details,
        "source_document_rows": len(source_docs),
        "candidate_document_rows": len(candidate_docs),
        "source_numeric_rows": len(source_values),
        "candidate_numeric_rows": len(candidate_values),
        "source_document_errors": source_errors,
        "candidate_document_errors": candidate_errors,
        "document_error_reduction": source_errors - candidate_errors,
        "unresolved_tie_definition": sorted(UNRESOLVED_TIE_RESOLUTIONS),
        "source_unresolved_tie_taxonomy": dict(sorted(source_tie_taxonomy.items())),
        "candidate_unresolved_tie_taxonomy": dict(
            sorted(candidate_tie_taxonomy.items())
        ),
        "source_unresolved_ties": source_ties,
        "candidate_unresolved_ties": candidate_ties,
        "unresolved_tie_reduction": source_ties - candidate_ties,
        "non_target_document_rows": len(non_target_source_docs),
        "non_target_document_exact_equal": True,
        "existing_numeric_rows": len(source_values),
        "existing_numeric_exact_equal": True,
        "stable_numeric_field_count": len(
            base.baseline_compare.STABLE_NUMERIC_FIELDS
        ),
        "source_existing_numeric_semantic_sha256": source_semantic_sha,
        "candidate_existing_numeric_semantic_sha256": candidate_existing_semantic_sha,
        "candidate_documents_sha256": base.sha256(docs_out),
        "candidate_values_sha256": base.sha256(values_out),
        "non_balance_values_promoted": False,
        "source_policy_changed": False,
        "point_in_time_policy_changed": False,
        "issuer_gate_changed": False,
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "ocr_enabled": False,
        "fuzzy_alias_matching_enabled": False,
        "e_equals_a_minus_l_inference": False,
        "production_runtime_changed": False,
        "production_data_changed": False,
        "trained_model_changed": False,
        "candidate_promotion_authorized": False,
        "final_data_verdict": "FAIL_CLOSED",
        "stage3_status": "NOT_READY",
        "stage4_alpha_live_locked": True,
        "main_changed": False,
        "pass": True,
        "errors": [],
    }
    report_path = out / "stage3_s3g1j_v17_28_candidate_safety.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
