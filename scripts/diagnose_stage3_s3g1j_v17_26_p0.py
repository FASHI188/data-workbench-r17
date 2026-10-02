#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
import requests

import diagnose_stage3_s3g1j_p0_layout_evidence as layout_evidence
import diagnose_stage3_s3g1j_p0_v17_24 as prior_diagnostic
import stage3_financial_pdf_parser_v15 as v17_24
import stage3_financial_pdf_parser_v18 as v17_26
import stage3_financial_spatial_alias_v17_24 as spatial
import stage3_financial_statement_blocks_v17_25 as generic_witness

P0_CLASS = "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3"
P0_PRIORITY = "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT"
ALL_MISSING = "MISSING_CANDIDATES_TOTAL_ASSETS_TOTAL_LIABILITIES_TOTAL_EQUITY"
EQUITY_MISSING = "MISSING_CANDIDATES_TOTAL_EQUITY"
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")

SOURCE_CLASSIFIER_RUN = 30734063100
SOURCE_CLASSIFIER_ARTIFACT = "stage3-s3g1j-v17-26-residual-classification-v2"
SOURCE_CLASSIFIER_DIGEST = (
    "sha256:f667e5e494e6ac1456a370b5dab47677b4925d0466beedceec3e47bdeb5f16a5"
)
P0_GZIP_SHA256 = "75f41b4576fc843b93bca6ac98f12a12e72475daaa0f00473e2a6edae5fdcf90"
P0_PLAINTEXT_SHA256 = "3500694439fc4573b1546c001b647ecb0bee6804691df8306727255debbeef49"
SOURCE_FULL_RUN = 30733013665
SOURCE_FULL_ARTIFACT = "stage3-s3g1j-v17-26-full-final"
SOURCE_FULL_DIGEST = (
    "sha256:7f2e707e9192af527ff0444b48caf6bebfbfa1ef7559ec2810b6f47b1790567b"
)
DOCUMENTS_GZIP_SHA256 = "891d6e10b92e13e3aea604ab9e22bd8dd0ea66764cc485a68abdc50eb8742d68"
DOCUMENTS_PLAINTEXT_SHA256 = "98cd05e8ea3569e779080c76c3bbde55174bd919d66cbfcda84a99315be71108"

EXPECTED_IDS = (
    "1200907104", "1201708762", "1202195310", "1202774611",
    "1202799494", "1203358200", "1204077386", "1205543437",
    "1207621057", "1209806910", "1209825769", "1215186538",
    "1219426855", "1219792633", "1219834247", "1219840508",
    "1219879687", "1220087244", "1221006100", "1223347318",
    "1223407043",
)
EXPECTED_GENERIC_PROMOTED_IDS = (
    "1200907104", "1201708762", "1202195310", "1202774611",
    "1203358200", "1204077386", "1205543437",
)
EXPECTED_SIGNATURE_COUNTS = {ALL_MISSING: 10, EQUITY_MISSING: 11}
EXPECTED_CANDIDATE_PATTERNS = {
    '{"TOTAL_ASSETS":0,"TOTAL_EQUITY":0,"TOTAL_LIABILITIES":0}': 10,
    '{"TOTAL_ASSETS":3,"TOTAL_EQUITY":0,"TOTAL_LIABILITIES":1}': 11,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_gzip_plaintext(path: Path) -> str:
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_p0(path: Path) -> list[dict[str, str]]:
    if sha256_file(path) != P0_GZIP_SHA256:
        raise ValueError("V17.26 P0 ledger gzip SHA mismatch")
    if sha256_gzip_plaintext(path) != P0_PLAINTEXT_SHA256:
        raise ValueError("V17.26 P0 ledger plaintext SHA mismatch")
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 21:
        raise ValueError(f"V17.26 P0 population changed {len(rows)}")
    ids = tuple(sorted(str(row["announcement_id"]) for row in rows))
    if ids != tuple(sorted(EXPECTED_IDS)):
        raise ValueError(f"V17.26 P0 identities changed {ids}")
    for row in rows:
        if row.get("residual_class") != P0_CLASS:
            raise ValueError(f"unexpected P0 class {row.get('announcement_id')}")
        if row.get("priority_class") != P0_PRIORITY:
            raise ValueError(f"unexpected P0 priority {row.get('announcement_id')}")
    rows.sort(key=lambda row: (row["economic_date"], row["announcement_id"]))
    return rows


def compact_layout(layout: dict[str, Any]) -> dict[str, Any]:
    alias_role_counts: dict[str, Counter[str]] = {
        concept: Counter() for concept in CONCEPTS
    }
    alias_row_counts = Counter()
    for row in layout.get("alias_rows") or []:
        concept = str(row.get("concept") or "")
        if concept not in alias_role_counts:
            continue
        alias_row_counts[concept] += 1
        event = row.get("bound_event") or {}
        alias_role_counts[concept][str(event.get("role") or "NONE")] += 1
    return {
        "page_count": layout.get("page_count"),
        "candidate_pages_1b": layout.get("candidate_pages_1b"),
        "inspected_pages_1b": layout.get("inspected_pages_1b"),
        "formal_event_role_counts": layout.get("formal_event_role_counts"),
        "title_rows": layout.get("title_rows"),
        "alias_row_counts": dict(sorted(alias_row_counts.items())),
        "alias_bound_role_counts": {
            concept: dict(sorted(counter.items()))
            for concept, counter in alias_role_counts.items()
        },
        "alias_rows": layout.get("alias_rows"),
    }


def next_gate(signature: str, generic_count: int) -> str:
    if generic_count:
        return "GENERIC_GROUP_WITNESS_PRESENT_BUT_DOWNSTREAM_GATE_FAILED"
    if signature == ALL_MISSING:
        return "NO_FORMAL_SPATIAL_ALE_CANDIDATES_AFTER_ACCEPTED_ROLE_BINDING"
    if signature == EQUITY_MISSING:
        return "GROUP_ASSET_LIABILITY_PRESENT_BUT_GROUP_EQUITY_MISSING"
    return "UNCLASSIFIED_FAIL_CLOSED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p0-ledger", required=True)
    parser.add_argument("--documents", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    p0_path = Path(args.p0_ledger)
    documents_path = Path(args.documents)
    if sha256_file(documents_path) != DOCUMENTS_GZIP_SHA256:
        raise ValueError("V17.26 documents gzip SHA mismatch")
    if sha256_gzip_plaintext(documents_path) != DOCUMENTS_PLAINTEXT_SHA256:
        raise ValueError("V17.26 documents plaintext SHA mismatch")

    targets = load_p0(p0_path)
    target_ids = {row["announcement_id"] for row in targets}
    documents = prior_diagnostic.load_full_documents(
        documents_path, DOCUMENTS_GZIP_SHA256, target_ids
    )

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "data-workbench-r17-stage3-v17-26-p0-diagnostic/1.0",
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
            if actual_sha != evidence["sha256"]:
                raise ValueError(
                    f"source SHA changed expected={evidence['sha256']} actual={actual_sha}"
                )
            if len(raw) != evidence["bytes"]:
                raise ValueError(
                    f"source bytes changed expected={evidence['bytes']} actual={len(raw)}"
                )
            source_sha_matches += 1

            accepted = dict(v17_24.parse_pdf_bytes(raw, target["economic_date"]))
            current = dict(v17_26.parse_pdf_bytes(raw, target["economic_date"]))
            if current != accepted:
                raise ValueError("non-target V17.26 parse differs from accepted V17.25")
            if prior_diagnostic.is_recovered(current):
                raise ValueError("current P0 document unexpectedly recovered")

            with fitz.open(stream=raw, filetype="pdf") as doc:
                spatial_diagnostic = spatial.diagnose_spatial_balance_sheet_v17_24(
                    doc, target["economic_date"]
                )
                generic_diagnostic = generic_witness.diagnose_generic_group_witness(doc)
            layout = compact_layout(layout_evidence.collect_layout(raw, target))
            signature = prior_diagnostic.diagnostic_signature(
                False, spatial_diagnostic
            )
            generic_count = int(
                generic_diagnostic.get("promoted_generic_group_count") or 0
            )
            results.append(
                {
                    "announcement_id": aid,
                    "source_code": target["source_code"],
                    "issuer_org_id": target["issuer_org_id"],
                    "report_family": target["report_family"],
                    "economic_date": target["economic_date"],
                    "canonical_title": target["canonical_title"],
                    "canonical_source_url": evidence["url"],
                    "source_sha256": actual_sha,
                    "source_bytes": len(raw),
                    "v17_26_equals_v17_25": True,
                    "v17_26": prior_diagnostic.slim_parsed(current),
                    "spatial_diagnostic": spatial_diagnostic,
                    "diagnostic_signature": signature,
                    "generic_group_witness_diagnostic": generic_diagnostic,
                    "layout": layout,
                    "next_gate": next_gate(signature, generic_count),
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
            f"S3G1J_V17_26_P0_DIAGNOSTIC {index}/{len(targets)} aid={aid}",
            flush=True,
        )

    results.sort(key=lambda row: (row["economic_date"], row["announcement_id"]))
    signature_counts = Counter(row["diagnostic_signature"] for row in results)
    candidate_patterns = Counter(
        json.dumps(
            {
                concept: int(
                    ((row["spatial_diagnostic"].get("candidate_counts") or {}).get(concept))
                    or 0
                )
                for concept in CONCEPTS
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        for row in results
    )
    generic_promoted_ids = sorted(
        row["announcement_id"]
        for row in results
        if int(
            row["generic_group_witness_diagnostic"].get(
                "promoted_generic_group_count"
            )
            or 0
        )
        > 0
    )
    next_gate_counts = Counter(row["next_gate"] for row in results)
    role_counts = Counter()
    alias_role_counts: dict[str, Counter[str]] = {
        concept: Counter() for concept in CONCEPTS
    }
    for row in results:
        role_counts.update(row["layout"].get("formal_event_role_counts") or {})
        for concept, counts in (
            row["layout"].get("alias_bound_role_counts") or {}
        ).items():
            alias_role_counts[concept].update(counts)

    passed = (
        not failures
        and len(results) == 21
        and source_sha_matches == 21
        and all(row["v17_26_equals_v17_25"] for row in results)
        and not any(row["v17_26"]["recovered"] for row in results)
        and dict(sorted(signature_counts.items())) == EXPECTED_SIGNATURE_COUNTS
        and dict(sorted(candidate_patterns.items())) == EXPECTED_CANDIDATE_PATTERNS
        and generic_promoted_ids == sorted(EXPECTED_GENERIC_PROMOTED_IDS)
    )
    report = {
        "gate": "S3G1J_V17_26_CURRENT_P0_SOURCE_DIAGNOSTIC_V1",
        "source_classifier_run": SOURCE_CLASSIFIER_RUN,
        "source_classifier_artifact": SOURCE_CLASSIFIER_ARTIFACT,
        "source_classifier_artifact_digest": SOURCE_CLASSIFIER_DIGEST,
        "source_full_basis_run": SOURCE_FULL_RUN,
        "source_full_basis_artifact": SOURCE_FULL_ARTIFACT,
        "source_full_basis_artifact_digest": SOURCE_FULL_DIGEST,
        "p0_gzip_sha256": P0_GZIP_SHA256,
        "p0_plaintext_sha256": P0_PLAINTEXT_SHA256,
        "documents_gzip_sha256": DOCUMENTS_GZIP_SHA256,
        "documents_plaintext_sha256": DOCUMENTS_PLAINTEXT_SHA256,
        "runtime_generation": "V17.26",
        "target_count": 21,
        "processed_count": len(results),
        "source_sha_match_count": source_sha_matches,
        "current_recovered_count": sum(
            bool(row["v17_26"]["recovered"]) for row in results
        ),
        "v17_26_equals_v17_25_count": sum(
            bool(row["v17_26_equals_v17_25"]) for row in results
        ),
        "signature_counts": dict(sorted(signature_counts.items())),
        "candidate_count_patterns": dict(sorted(candidate_patterns.items())),
        "generic_group_witness_promoted_count": len(generic_promoted_ids),
        "generic_group_witness_promoted_announcement_ids": generic_promoted_ids,
        "next_gate_counts": dict(sorted(next_gate_counts.items())),
        "formal_event_role_totals": dict(sorted(role_counts.items())),
        "alias_bound_role_totals": {
            concept: dict(sorted(counter.items()))
            for concept, counter in alias_role_counts.items()
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
