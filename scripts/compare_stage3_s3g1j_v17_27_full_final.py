#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

TARGETS = {
    "1200907104": {
        "source_sha256": "87a313e900dd74ec976e2c6e5c0eeb0e7c7cfd5e68c31e9ede3ae8c01c7e9d49",
        "economic_date": "2015-03-31",
        "values": {
            "TOTAL_ASSETS": "4888152213.85",
            "TOTAL_LIABILITIES": "1510781556.82",
            "TOTAL_EQUITY": "3377370657.03",
        },
    },
    "1201708762": {
        "source_sha256": "e7af0c09c31f0be1e83fdb118c603a141c094739767de01b90f57680ce9596a8",
        "economic_date": "2015-09-30",
        "values": {
            "TOTAL_ASSETS": "4874736170.10",
            "TOTAL_LIABILITIES": "1441408971.22",
            "TOTAL_EQUITY": "3433327198.88",
        },
    },
    "1202195310": {
        "source_sha256": "04b84b49ce4e36a4c9089e13cd46f717ef27c7d93c141533d7d7ff2299513925",
        "economic_date": "2016-03-31",
        "values": {
            "TOTAL_ASSETS": "5097002228.22",
            "TOTAL_LIABILITIES": "1542170536.28",
            "TOTAL_EQUITY": "3554831691.94",
        },
    },
    "1202774611": {
        "source_sha256": "eb0c9e0b559e1960316f3844ac32e7299cf31391fec1d83ee6b4fb2fe37aef14",
        "economic_date": "2016-09-30",
        "values": {
            "TOTAL_ASSETS": "5482906412.71",
            "TOTAL_LIABILITIES": "1838330886.91",
            "TOTAL_EQUITY": "3644575525.80",
        },
    },
    "1203358200": {
        "source_sha256": "3d009555c7acb24c7d9cc0cb52ec3d5e43c473379b0c02c5bc832d6a3d773c82",
        "economic_date": "2017-03-31",
        "values": {
            "TOTAL_ASSETS": "5755203586.29",
            "TOTAL_LIABILITIES": "1966640135.46",
            "TOTAL_EQUITY": "3788563450.83",
        },
    },
}

DOC_FIELDS = (
    "exchange", "source_code", "effective_code", "issuer_org_id", "report_family",
    "economic_date", "announcement_id", "revision_sequence", "source_published_at",
    "effective_session", "available_at", "canonical_title", "canonical_source_url",
    "selected_source_url", "selected_source_sha256", "selected_source_bytes",
    "tie_candidate_count", "tie_resolution", "candidate_evidence_json", "tier1_found",
    "tier2_found", "numeric_observations", "document_status", "document_error",
)
STABLE_NUMERIC_FIELDS = (
    "exchange", "source_code", "effective_code", "issuer_org_id", "report_family",
    "economic_date", "announcement_id", "revision_sequence", "source_published_at",
    "effective_session", "available_at", "concept", "raw_value",
    "normalized_cny_value", "unit", "unit_multiplier", "source_url", "source_sha256",
    "source_format", "page", "matched_alias", "confidence",
)
EXCLUDED_GENERATION_FIELDS = ("extraction_method", "methodology_version")
EXPECTED_PARSER_METHOD = (
    "CNINFO_ORIGINAL_PDF_PYMUPDF_V17_V17_27_"
    "EXACT_SOURCE_NORMAL_EQUITY_PRODUCTION"
)
EXPECTED_METHODOLOGY = "V3.3.7-V17.27"
EXPECTED_SHARD_GATE = "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_27"
EXPECTED_RUNTIME_GENERATION = "V17.27"
EXPECTED_PAGES = {
    "TOTAL_ASSETS": "9",
    "TOTAL_LIABILITIES": "10",
    "TOTAL_EQUITY": "11",
}
EXPECTED_ALIASES = {
    "TOTAL_ASSETS": "资产总计",
    "TOTAL_LIABILITIES": "负债合计",
    "TOTAL_EQUITY": "所有者权益合计",
}


def read_gz(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_audit(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_json_text(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
    return json.dumps(
        parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _canonical_doc(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(
        _normalize_json_text(row.get(field, ""))
        if field in {"candidate_evidence_json", "document_error"}
        else row.get(field, "")
        for field in DOC_FIELDS
    )


def _numeric_tuple(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(row.get(field, "") for field in STABLE_NUMERIC_FIELDS)


def semantic_multiset_sha(counter: Counter[tuple[str, ...]]) -> str:
    digest = hashlib.sha256()
    for payload, count in sorted(counter.items()):
        line = json.dumps(
            [list(payload), count], ensure_ascii=False, separators=(",", ":")
        )
        digest.update((line + "\n").encode("utf-8"))
    return digest.hexdigest()


def _document_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        aid = row.get("announcement_id", "")
        if not aid or aid in result:
            raise ValueError(f"invalid or duplicate document identity {aid!r}")
        result[aid] = row
    return result


def _target_numeric_summary(
    aid: str, rows: list[dict[str, str]], expected: dict, errors: list[str]
) -> dict:
    by_concept: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_concept.setdefault(row.get("concept", ""), []).append(row)
    if len(rows) != 3:
        errors.append(f"{aid}: expected 3 numeric rows, actual={len(rows)}")
    if set(by_concept) != set(expected["values"]):
        errors.append(
            f"{aid}: concept scope expected={sorted(expected['values'])} "
            f"actual={sorted(by_concept)}"
        )
    evidence: dict[str, dict] = {}
    for concept, value in expected["values"].items():
        concept_rows = by_concept.get(concept, [])
        if len(concept_rows) != 1:
            errors.append(f"{aid}: {concept} row count={len(concept_rows)}")
            continue
        row = concept_rows[0]
        checks = {
            "normalized_cny_value": value,
            "source_sha256": expected["source_sha256"],
            "source_format": "PDF",
            "extraction_method": EXPECTED_PARSER_METHOD,
            "methodology_version": EXPECTED_METHODOLOGY,
            "page": EXPECTED_PAGES[concept],
            "matched_alias": EXPECTED_ALIASES[concept],
            "confidence": "HIGH",
            "economic_date": expected["economic_date"],
        }
        for field, required in checks.items():
            if row.get(field, "") != required:
                errors.append(
                    f"{aid}: {concept} {field} expected={required!r} "
                    f"actual={row.get(field, '')!r}"
                )
        evidence[concept] = {field: row.get(field, "") for field in checks}
    return {
        "numeric_row_count": len(rows),
        "concepts": sorted(by_concept),
        "evidence": evidence,
    }


def compare(
    previous_docs_rows: list[dict[str, str]],
    current_docs_rows: list[dict[str, str]],
    previous_values_rows: list[dict[str, str]],
    current_values_rows: list[dict[str, str]],
    previous_audit: dict,
    current_audit: dict,
) -> dict:
    errors: list[str] = []
    previous_docs = _document_index(previous_docs_rows)
    current_docs = _document_index(current_docs_rows)

    if len(previous_docs) != 121354 or len(current_docs) != 121354:
        errors.append(
            f"document count expected=121354 previous={len(previous_docs)} "
            f"current={len(current_docs)}"
        )
    if set(previous_docs) != set(current_docs):
        errors.append(
            f"document identity changed missing={sorted(set(previous_docs)-set(current_docs))[:20]} "
            f"extra={sorted(set(current_docs)-set(previous_docs))[:20]}"
        )

    changed_ids: list[str] = []
    non_target_doc_drift: list[str] = []
    target_document_evidence: dict[str, dict] = {}
    for aid in sorted(set(previous_docs) & set(current_docs)):
        old = previous_docs[aid]
        new = current_docs[aid]
        if _canonical_doc(old) != _canonical_doc(new):
            changed_ids.append(aid)
            if aid not in TARGETS:
                non_target_doc_drift.append(aid)

    if set(changed_ids) != set(TARGETS):
        errors.append(
            f"document delta mismatch expected={sorted(TARGETS)} actual={changed_ids}"
        )
    if non_target_doc_drift:
        errors.append(f"non-target document drift {non_target_doc_drift[:20]}")

    for aid, expected in TARGETS.items():
        old = previous_docs.get(aid, {})
        new = current_docs.get(aid, {})
        if old.get("document_status") == "PASS" or not old.get("document_error"):
            errors.append(f"previous V17.26 basis was not fail-closed for {aid}")
        required = {
            "document_status": "PASS",
            "document_error": "",
            "selected_source_sha256": expected["source_sha256"],
            "numeric_observations": "3",
            "tier1_found": "0",
            "tier2_found": "3",
            "economic_date": expected["economic_date"],
        }
        for field, value in required.items():
            if new.get(field, "") != value:
                errors.append(
                    f"{aid}: document {field} expected={value!r} "
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
            evidence = exact[0]
            if evidence.get("tier1_found") != 0 or evidence.get("tier2_found") != 3:
                errors.append(f"{aid}: candidate evidence tier counts changed")
            if evidence.get("parser_version") != "V17_27_EXACT_SOURCE_NORMAL_EQUITY_IDENTITY_PRODUCTION":
                errors.append(
                    f"{aid}: candidate evidence parser version changed "
                    f"{evidence.get('parser_version')!r}"
                )
            if evidence.get("validation_errors") not in ([], None):
                errors.append(f"{aid}: candidate evidence retained validation errors")
        target_document_evidence[aid] = {
            field: new.get(field, "") for field in required
        }

    previous_counter = Counter(_numeric_tuple(row) for row in previous_values_rows)
    current_existing_rows = [
        row for row in current_values_rows if row.get("announcement_id", "") not in TARGETS
    ]
    current_existing_counter = Counter(_numeric_tuple(row) for row in current_existing_rows)
    previous_numeric_sha = semantic_multiset_sha(previous_counter)
    current_existing_numeric_sha = semantic_multiset_sha(current_existing_counter)

    if len(previous_values_rows) != 1051778:
        errors.append(
            f"previous numeric count expected=1051778 actual={len(previous_values_rows)}"
        )
    if len(current_values_rows) != 1051793:
        errors.append(
            f"current numeric count expected=1051793 actual={len(current_values_rows)}"
        )
    if len(current_existing_rows) != 1051778:
        errors.append(
            f"current existing numeric count expected=1051778 actual={len(current_existing_rows)}"
        )
    if previous_counter != current_existing_counter:
        missing = list((previous_counter - current_existing_counter).items())[:5]
        extra = list((current_existing_counter - previous_counter).items())[:5]
        errors.append(f"existing numeric semantic drift missing={missing} extra={extra}")
    if previous_numeric_sha != current_existing_numeric_sha:
        errors.append(
            f"existing numeric semantic SHA drift previous={previous_numeric_sha} "
            f"current={current_existing_numeric_sha}"
        )

    target_numeric_evidence: dict[str, dict] = {}
    for aid, expected in TARGETS.items():
        previous_target_rows = [
            row for row in previous_values_rows if row.get("announcement_id", "") == aid
        ]
        if previous_target_rows:
            errors.append(f"previous V17.26 basis already contains numeric rows for {aid}")
        current_target_rows = [
            row for row in current_values_rows if row.get("announcement_id", "") == aid
        ]
        target_numeric_evidence[aid] = _target_numeric_summary(
            aid, current_target_rows, expected, errors
        )

    previous_expected = {
        "runtime_generation": "V17.26",
        "shard_gate": "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_26",
        "parser_method": (
            "CNINFO_ORIGINAL_PDF_PYMUPDF_V16_V17_26_"
            "EXACT_SOURCE_BALANCE_ONLY_PRODUCTION"
        ),
        "methodology_version": "V3.3.6-V17.26",
        "canonical_version_count": 121354,
        "document_count": 121354,
        "numeric_observation_count": 1051778,
        "document_error_count": 1378,
        "unresolved_tie_count": 1295,
        "pass": False,
    }
    current_expected = {
        "runtime_generation": EXPECTED_RUNTIME_GENERATION,
        "shard_gate": EXPECTED_SHARD_GATE,
        "parser_method": EXPECTED_PARSER_METHOD,
        "methodology_version": EXPECTED_METHODOLOGY,
        "canonical_version_count": 121354,
        "document_count": 121354,
        "numeric_observation_count": 1051793,
        "document_error_count": 1373,
        "unresolved_tie_count": 1295,
        "authority": "CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256",
        "historical_current_f10_used_as_truth": False,
        "stage4_alpha_locked": True,
        "pass": False,
    }
    for label, audit, expected in (
        ("previous", previous_audit, previous_expected),
        ("current", current_audit, current_expected),
    ):
        for field, value in expected.items():
            if audit.get(field) != value:
                errors.append(
                    f"{label} audit {field} expected={value!r} "
                    f"actual={audit.get(field)!r}"
                )

    return {
        "gate": "S3G1J_V17_27_FULL_BASIS_NON_REGRESSION",
        "pass": not errors,
        "execution_verdict": "PASS" if not errors else "FAIL",
        "final_data_gate_pass": False,
        "final_data_verdict": "FAIL_CLOSED",
        "previous_document_count": len(previous_docs),
        "current_document_count": len(current_docs),
        "previous_numeric_count": len(previous_values_rows),
        "current_numeric_count": len(current_values_rows),
        "previous_document_error_count": previous_audit.get("document_error_count"),
        "current_document_error_count": current_audit.get("document_error_count"),
        "previous_unresolved_tie_count": previous_audit.get("unresolved_tie_count"),
        "current_unresolved_tie_count": current_audit.get("unresolved_tie_count"),
        "expected_changed_announcement_ids": sorted(TARGETS),
        "actual_changed_announcement_ids": changed_ids,
        "non_target_document_rows": len(current_docs) - len(TARGETS),
        "non_target_document_exact_equal": not non_target_doc_drift,
        "existing_numeric_rows": len(current_existing_rows),
        "existing_numeric_exact_equal": previous_counter == current_existing_counter,
        "stable_numeric_fields": list(STABLE_NUMERIC_FIELDS),
        "excluded_generation_fields": list(EXCLUDED_GENERATION_FIELDS),
        "previous_existing_numeric_semantic_sha256": previous_numeric_sha,
        "current_existing_numeric_semantic_sha256": current_existing_numeric_sha,
        "target_document_evidence": target_document_evidence,
        "target_numeric_evidence": target_numeric_evidence,
        "target_numeric_rows": sum(
            item["numeric_row_count"] for item in target_numeric_evidence.values()
        ),
        "non_balance_target_concepts_allowed": False,
        "unexpected_document_regression_count": len(non_target_doc_drift),
        "errors": errors,
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
