#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
import requests

import diagnose_stage3_s3g1j_v17_26_p0 as base
import diagnose_stage3_s3g1j_p0_v17_24 as prior_diagnostic
import stage3_financial_spatial_alias_v17_24 as spatial
import stage3_financial_statement_blocks_v17_25 as generic_witness

CONCEPTS = base.CONCEPTS


def _candidate_diagnostic(
    raw: bytes, economic_date: str
) -> tuple[dict[str, Any], dict[str, Any]]:
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
        finally:
            spatial.v21.v17.blocks.formal_statement_events = original
    return witness, diagnostic


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
            "User-Agent": "data-workbench-r17-stage3-v17-26-p0-candidate-spatial/1.0",
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
            witness, diagnostic = _candidate_diagnostic(
                raw, target["economic_date"]
            )
            counts = {
                concept: int((diagnostic.get("candidate_counts") or {}).get(concept) or 0)
                for concept in CONCEPTS
            }
            results.append(
                {
                    "announcement_id": aid,
                    "source_code": target["source_code"],
                    "report_family": target["report_family"],
                    "economic_date": target["economic_date"],
                    "source_sha256": actual_sha,
                    "generic_group_witness_count": int(
                        witness.get("promoted_generic_group_count") or 0
                    ),
                    "candidate_counts": counts,
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
    passed = (
        not failures
        and len(results) == 21
        and source_sha_matches == 21
        and promoted_ids == sorted(base.EXPECTED_GENERIC_PROMOTED_IDS)
        and not recovered_ids
    )
    report = {
        "gate": "S3G1J_V17_26_CURRENT_P0_GENERIC_CANDIDATE_SPATIAL_V1",
        "base_diagnostic_gate": base_report.get("gate"),
        "source_classifier_run": base.SOURCE_CLASSIFIER_RUN,
        "source_full_basis_run": base.SOURCE_FULL_RUN,
        "runtime_generation": "V17.26",
        "candidate_only_statement_role_override": True,
        "formal_runtime_changed": False,
        "target_count": 21,
        "processed_count": len(results),
        "source_sha_match_count": source_sha_matches,
        "generic_group_witness_promoted_count": len(promoted_ids),
        "generic_group_witness_promoted_announcement_ids": promoted_ids,
        "candidate_count_patterns": dict(sorted(pattern_counts.items())),
        "promoted_candidate_count_patterns": dict(
            sorted(promoted_pattern_counts.items())
        ),
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
