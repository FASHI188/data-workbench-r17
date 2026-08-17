#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import compare_stage3_s3g1j_v17_27_full_final as v1

EXPECTED_PREVIOUS_TIES = 1295
EXPECTED_CURRENT_TIES = 1290
EXPECTED_RECOVERED_TIES = 5


def _normalize_nested(value):
    if isinstance(value, dict):
        return {key: _normalize_nested(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize_nested(item) for item in value]
    return value


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_document_error(value: str) -> str:
    """Ignore only top-level conflict-concept order; preserve nested evidence order."""
    if not value:
        return ""
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
    normalized = _normalize_nested(parsed)
    if isinstance(normalized, list):
        normalized = sorted(normalized, key=_canonical_json)
    return _canonical_json(normalized)


def canonical_document(row: dict[str, str]) -> tuple[str, ...]:
    values: list[str] = []
    for field in v1.DOC_FIELDS:
        value = row.get(field, "")
        if field == "document_error":
            values.append(canonical_document_error(value))
        elif field == "candidate_evidence_json":
            values.append(v1._normalize_json_text(value))
        else:
            values.append(value)
    return tuple(values)


def compare(
    previous_docs_rows: list[dict[str, str]],
    current_docs_rows: list[dict[str, str]],
    previous_values_rows: list[dict[str, str]],
    current_values_rows: list[dict[str, str]],
    previous_audit: dict,
    current_audit: dict,
) -> dict:
    previous_ties = int(previous_audit.get("unresolved_tie_count", -1))
    current_ties = int(current_audit.get("unresolved_tie_count", -1))

    # V1 incorrectly expected the five recovered TIE_SOURCE_INCOMPLETE targets
    # to remain unresolved. Feed V1 its legacy expectation, then enforce the
    # corrected transition explicitly below.
    current_for_v1 = dict(current_audit)
    current_for_v1["unresolved_tie_count"] = EXPECTED_PREVIOUS_TIES

    original_canonical_doc = v1._canonical_doc
    v1._canonical_doc = canonical_document
    try:
        report = v1.compare(
            previous_docs_rows,
            current_docs_rows,
            previous_values_rows,
            current_values_rows,
            previous_audit,
            current_for_v1,
        )
    finally:
        v1._canonical_doc = original_canonical_doc

    errors = list(report.get("errors") or [])
    if previous_ties != EXPECTED_PREVIOUS_TIES:
        errors.append(
            f"previous unresolved ties expected={EXPECTED_PREVIOUS_TIES} actual={previous_ties}"
        )
    if current_ties != EXPECTED_CURRENT_TIES:
        errors.append(
            f"current unresolved ties expected={EXPECTED_CURRENT_TIES} actual={current_ties}"
        )
    if previous_ties - current_ties != EXPECTED_RECOVERED_TIES:
        errors.append(
            "unresolved tie recovery mismatch "
            f"expected={EXPECTED_RECOVERED_TIES} actual={previous_ties-current_ties}"
        )

    report.update(
        {
            "gate": "S3G1J_V17_27_FULL_BASIS_NON_REGRESSION_V2",
            "previous_unresolved_tie_count": previous_ties,
            "current_unresolved_tie_count": current_ties,
            "recovered_unresolved_tie_count": previous_ties - current_ties,
            "expected_recovered_unresolved_tie_count": EXPECTED_RECOVERED_TIES,
            "top_level_conflict_concept_order_normalized": True,
            "nested_conflict_evidence_order_preserved": True,
            "errors": errors,
            "pass": not errors,
            "execution_verdict": "PASS" if not errors else "FAIL",
        }
    )
    return report


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
        v1.read_gz(Path(args.previous_documents)),
        v1.read_gz(Path(args.current_documents)),
        v1.read_gz(Path(args.previous_values)),
        v1.read_gz(Path(args.current_values)),
        v1.read_audit(Path(args.previous_audit)),
        v1.read_audit(Path(args.current_audit)),
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
