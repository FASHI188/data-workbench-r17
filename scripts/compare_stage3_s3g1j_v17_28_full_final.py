#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import compare_stage3_s3g1j_v17_27_full_final_v2 as v27

TARGETS = {
    "1207621057": {
        "source_sha256": "b2aa4afa67e2b02010d5ba708d4e5fe02138623ff4bc48718c03029111a64568",
        "source_bytes": "477621",
        "economic_date": "2020-03-31",
        "page_count": 19,
        "values": {
            "TOTAL_ASSETS": ("5470381065.66", "8", "资产总计"),
            "TOTAL_LIABILITIES": ("2220814468.73", "9", "负债合计"),
            "TOTAL_EQUITY": ("3249566596.93", "10", "所有者权益（或股东权益）合计"),
        },
    },
    "1209825769": {
        "source_sha256": "0bd1da8bdac0aff2a3e99b83adc29e7b60e959c99dd29b8ab88cbda1344b441c",
        "source_bytes": "633887",
        "economic_date": "2021-03-31",
        "page_count": 20,
        "values": {
            "TOTAL_ASSETS": ("1615699540.62", "10", "资产总计"),
            "TOTAL_LIABILITIES": ("312375993.81", "10", "负债合计"),
            "TOTAL_EQUITY": ("1303323546.81", "11", "所有者权益（或股东权益）合计"),
        },
    },
}
EXPECTED_EXTRACTOR_METHOD = (
    "CNINFO_ORIGINAL_PDF_PYMUPDF_V18_V17_28_"
    "EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION"
)
EXPECTED_PARSER_VERSION = "V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION"
EXPECTED_METHODOLOGY = "V3.3.8-V17.28"
EXPECTED_SHARD_GATE = "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_28"

read_gz = v27.v1.read_gz
read_audit = v27.v1.read_audit
canonical_document = v27.canonical_document
numeric_tuple = v27.v1._numeric_tuple
semantic_multiset_sha = v27.v1.semantic_multiset_sha


def document_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        aid = row.get("announcement_id", "")
        if not aid or aid in out:
            raise ValueError(f"invalid or duplicate document identity {aid!r}")
        out[aid] = row
    return out


def compare(
    previous_docs_rows: list[dict[str, str]],
    current_docs_rows: list[dict[str, str]],
    previous_values_rows: list[dict[str, str]],
    current_values_rows: list[dict[str, str]],
    previous_audit: dict,
    current_audit: dict,
) -> dict:
    errors: list[str] = []
    previous_docs = document_index(previous_docs_rows)
    current_docs = document_index(current_docs_rows)

    if len(previous_docs) != 121354 or len(current_docs) != 121354:
        errors.append(
            f"document count expected=121354 previous={len(previous_docs)} "
            f"current={len(current_docs)}"
        )
    if set(previous_docs) != set(current_docs):
        errors.append("document identities changed")

    changed_ids = [
        aid for aid in sorted(set(previous_docs) & set(current_docs))
        if canonical_document(previous_docs[aid]) != canonical_document(current_docs[aid])
    ]
    if changed_ids != sorted(TARGETS):
        errors.append(
            f"document delta mismatch expected={sorted(TARGETS)} actual={changed_ids}"
        )

    target_document_evidence: dict[str, dict] = {}
    for aid, expected in TARGETS.items():
        old = previous_docs.get(aid, {})
        new = current_docs.get(aid, {})
        if old.get("document_status") == "PASS" or not old.get("document_error"):
            errors.append(f"{aid}: previous V17.27 row was not fail-closed")
        required = {
            "document_status": "PASS",
            "document_error": "",
            "tie_candidate_count": "1",
            "tie_resolution": "SINGLE_CANONICAL",
            "selected_source_sha256": expected["source_sha256"],
            "selected_source_bytes": expected["source_bytes"],
            "numeric_observations": "3",
            "tier1_found": "0",
            "tier2_found": "3",
            "economic_date": expected["economic_date"],
        }
        for field, wanted in required.items():
            if new.get(field, "") != wanted:
                errors.append(
                    f"{aid}: document {field} expected={wanted!r} "
                    f"actual={new.get(field, '')!r}"
                )
        try:
            candidates = json.loads(new.get("candidate_evidence_json") or "[]")
        except json.JSONDecodeError:
            candidates = []
            errors.append(f"{aid}: candidate_evidence_json invalid")
        exact = [
            row for row in candidates
            if isinstance(row, dict)
            and str(row.get("id") or "") == aid
            and str(row.get("sha256") or "") == expected["source_sha256"]
        ]
        if len(exact) != 1:
            errors.append(f"{aid}: exact source evidence count={len(exact)}")
        else:
            evidence_expected = {
                "bytes": int(expected["source_bytes"]),
                "tier1_found": 0,
                "tier2_found": 3,
                "page_count": expected["page_count"],
                "parser_version": EXPECTED_PARSER_VERSION,
                "validation_errors": [],
            }
            for field, wanted in evidence_expected.items():
                if exact[0].get(field) != wanted:
                    errors.append(
                        f"{aid}: evidence {field} expected={wanted!r} "
                        f"actual={exact[0].get(field)!r}"
                    )
        target_document_evidence[aid] = {
            field: new.get(field, "") for field in required
        }

    previous_counter = Counter(numeric_tuple(row) for row in previous_values_rows)
    current_existing_rows = [
        row for row in current_values_rows
        if row.get("announcement_id", "") not in TARGETS
    ]
    current_counter = Counter(numeric_tuple(row) for row in current_existing_rows)
    previous_sha = semantic_multiset_sha(previous_counter)
    current_sha = semantic_multiset_sha(current_counter)

    if len(previous_values_rows) != 1051793:
        errors.append(
            f"previous numeric count expected=1051793 actual={len(previous_values_rows)}"
        )
    if len(current_values_rows) != 1051799:
        errors.append(
            f"current numeric count expected=1051799 actual={len(current_values_rows)}"
        )
    if len(current_existing_rows) != 1051793:
        errors.append(
            f"current existing numeric count expected=1051793 "
            f"actual={len(current_existing_rows)}"
        )
    if previous_counter != current_counter:
        missing = list((previous_counter - current_counter).items())[:5]
        extra = list((current_counter - previous_counter).items())[:5]
        errors.append(
            f"existing numeric 22-field multiset drift missing={missing} extra={extra}"
        )
    if previous_sha != current_sha:
        errors.append(
            f"existing numeric semantic SHA drift previous={previous_sha} "
            f"current={current_sha}"
        )

    target_numeric_evidence: dict[str, dict] = {}
    for aid, expected in TARGETS.items():
        if any(row.get("announcement_id", "") == aid for row in previous_values_rows):
            errors.append(f"{aid}: previous V17.27 already contains numeric rows")
        rows = [
            row for row in current_values_rows
            if row.get("announcement_id", "") == aid
        ]
        if len(rows) != 3:
            errors.append(f"{aid}: target numeric row count={len(rows)}")
        by_concept = {row.get("concept", ""): row for row in rows}
        if set(by_concept) != set(expected["values"]):
            errors.append(f"{aid}: target concept scope={sorted(by_concept)}")
        evidence: dict[str, dict] = {}
        for concept, (value, page, alias) in expected["values"].items():
            row = by_concept.get(concept, {})
            required = {
                "normalized_cny_value": value,
                "source_sha256": expected["source_sha256"],
                "source_format": "PDF",
                "page": page,
                "matched_alias": alias,
                "confidence": "HIGH",
                "economic_date": expected["economic_date"],
                "extraction_method": EXPECTED_EXTRACTOR_METHOD,
                "methodology_version": EXPECTED_METHODOLOGY,
            }
            for field, wanted in required.items():
                if row.get(field, "") != wanted:
                    errors.append(
                        f"{aid}: {concept} {field} expected={wanted!r} "
                        f"actual={row.get(field, '')!r}"
                    )
            evidence[concept] = {
                field: row.get(field, "") for field in required
            }
        target_numeric_evidence[aid] = evidence

    previous_expected = {
        "runtime_generation": "V17.27",
        "shard_gate": "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_27",
        "parser_method": (
            "CNINFO_ORIGINAL_PDF_PYMUPDF_V17_V17_27_"
            "EXACT_SOURCE_NORMAL_EQUITY_PRODUCTION"
        ),
        "methodology_version": "V3.3.7-V17.27",
        "canonical_version_count": 121354,
        "document_count": 121354,
        "numeric_observation_count": 1051793,
        "document_error_count": 1373,
        "unresolved_tie_count": 1290,
        "pass": False,
    }
    current_expected = {
        "runtime_generation": "V17.28",
        "shard_gate": EXPECTED_SHARD_GATE,
        "parser_method": EXPECTED_EXTRACTOR_METHOD,
        "methodology_version": EXPECTED_METHODOLOGY,
        "canonical_version_count": 121354,
        "document_count": 121354,
        "numeric_observation_count": 1051799,
        "document_error_count": 1371,
        "unresolved_tie_count": 1288,
        "authority": "CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256",
        "historical_current_f10_used_as_truth": False,
        "stage4_alpha_locked": True,
        "pass": False,
    }
    for label, audit, expected in (
        ("previous", previous_audit, previous_expected),
        ("current", current_audit, current_expected),
    ):
        for field, wanted in expected.items():
            if audit.get(field) != wanted:
                errors.append(
                    f"{label} audit {field} expected={wanted!r} "
                    f"actual={audit.get(field)!r}"
                )

    previous_taxonomy = Counter(
        row.get("tie_resolution", "") for row in previous_docs_rows
    )
    current_taxonomy = Counter(
        row.get("tie_resolution", "") for row in current_docs_rows
    )
    for key, old_count, new_count in (
        ("TIE_SOURCE_INCOMPLETE", 1276, 1274),
        ("TIE_VALUE_CONFLICT", 14, 14),
    ):
        if previous_taxonomy[key] != old_count or current_taxonomy[key] != new_count:
            errors.append(
                f"tie taxonomy {key} expected={old_count}->{new_count} "
                f"actual={previous_taxonomy[key]}->{current_taxonomy[key]}"
            )

    return {
        "gate": "S3G1J_V17_28_FULL_BASIS_NON_REGRESSION",
        "pass": not errors,
        "execution_verdict": "PASS" if not errors else "FAIL",
        "final_data_verdict": "FAIL_CLOSED",
        "previous_document_count": len(previous_docs_rows),
        "current_document_count": len(current_docs_rows),
        "previous_numeric_count": len(previous_values_rows),
        "current_numeric_count": len(current_values_rows),
        "changed_announcement_ids": changed_ids,
        "non_target_document_equal_count": len(current_docs) - len(changed_ids),
        "existing_numeric_semantic_sha256_previous": previous_sha,
        "existing_numeric_semantic_sha256_current": current_sha,
        "target_document_evidence": target_document_evidence,
        "target_numeric_evidence": target_numeric_evidence,
        "previous_unresolved_ties": previous_audit.get("unresolved_tie_count"),
        "current_unresolved_ties": current_audit.get("unresolved_tie_count"),
        "errors": errors,
        "stage4_alpha_locked": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-documents", required=True)
    parser.add_argument("--current-documents", required=True)
    parser.add_argument("--previous-values", required=True)
    parser.add_argument("--current-values", required=True)
    parser.add_argument("--previous-audit", required=True)
    parser.add_argument("--current-audit", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = compare(
        read_gz(Path(args.previous_documents)),
        read_gz(Path(args.current_documents)),
        read_gz(Path(args.previous_values)),
        read_gz(Path(args.current_values)),
        read_audit(Path(args.previous_audit)),
        read_audit(Path(args.current_audit)),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
