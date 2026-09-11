#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

TARGETS = {
    "1207035181": "320e3a950a4768e73766d57a09bcf34d893d4da949b8ed5a1b2f887852e76229",
    "1221568845": "fa72059d35715f20df620691538528f720fe3ae42581c172c853f26799befb93",
}
COMPARABLE_FIELDS = (
    "document_status",
    "document_error",
    "tie_resolution",
    "selected_source_sha256",
    "selected_source_url",
    "numeric_observations",
)


def read_documents(path: Path) -> dict[str, dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        aid = row["announcement_id"]
        if aid in result:
            raise ValueError(f"duplicate document announcement {aid}")
        result[aid] = row
    return result


def _normalize_nested(value):
    """Normalize object keys while preserving every nested array position."""
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
    """Ignore only top-level conflict-concept order, never nested evidence order."""
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


def comparable_value(row: dict[str, str], field: str) -> str:
    value = row.get(field, "")
    return canonical_document_error(value) if field == "document_error" else value


def compare(
    previous: dict[str, dict[str, str]],
    current: dict[str, dict[str, str]],
    previous_audit: dict,
    current_audit: dict,
) -> dict:
    errors: list[str] = []
    if set(previous) != set(current):
        errors.append(
            f"document identity changed missing={sorted(set(previous)-set(current))[:20]} "
            f"extra={sorted(set(current)-set(previous))[:20]}"
        )
    if len(previous) != 121354 or len(current) != 121354:
        errors.append(
            f"document count changed previous={len(previous)} current={len(current)}"
        )

    changed: list[dict] = []
    regressions: list[str] = []
    for aid in sorted(set(previous) & set(current)):
        old = previous[aid]
        new = current[aid]
        delta = {
            field: {"previous": old.get(field, ""), "current": new.get(field, "")}
            for field in COMPARABLE_FIELDS
            if comparable_value(old, field) != comparable_value(new, field)
        }
        if delta:
            changed.append({"announcement_id": aid, "delta": delta})
            if aid not in TARGETS:
                regressions.append(aid)

    changed_ids = {row["announcement_id"] for row in changed}
    if changed_ids != set(TARGETS):
        errors.append(
            f"document delta mismatch expected={sorted(TARGETS)} "
            f"actual={sorted(changed_ids)}"
        )
    if regressions:
        errors.append(f"unexpected non-target changes {regressions[:20]}")

    for aid, expected_sha in TARGETS.items():
        old = previous.get(aid, {})
        new = current.get(aid, {})
        if old.get("document_status") == "PASS":
            errors.append(f"previous basis already passed target {aid}")
        if new.get("document_status") != "PASS" or new.get("document_error"):
            errors.append(f"V17.26 target did not pass cleanly {aid}")
        if new.get("selected_source_sha256") != expected_sha:
            errors.append(f"V17.26 target source SHA changed {aid}")
        if new.get("numeric_observations") != "3":
            errors.append(
                f"V17.26 target must expose exactly 3 observations {aid}: "
                f"{new.get('numeric_observations')}"
            )
        if new.get("tier1_found") != "0" or new.get("tier2_found") != "3":
            errors.append(f"V17.26 target tier scope changed {aid}")

    previous_errors = int(previous_audit.get("document_error_count", -1))
    current_errors = int(current_audit.get("document_error_count", -1))
    previous_ties = int(previous_audit.get("unresolved_tie_count", -1))
    current_ties = int(current_audit.get("unresolved_tie_count", -1))
    if (previous_errors, current_errors) != (1380, 1378):
        errors.append(
            f"document error accounting changed previous={previous_errors} "
            f"current={current_errors}"
        )
    if (previous_ties, current_ties) != (1297, 1295):
        errors.append(
            f"tie accounting changed previous={previous_ties} current={current_ties}"
        )

    expected_audit = {
        "runtime_generation": "V17.26",
        "shard_gate": "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_26",
        "parser_method": "CNINFO_ORIGINAL_PDF_PYMUPDF_V16_V17_26_EXACT_SOURCE_BALANCE_ONLY_PRODUCTION",
        "methodology_version": "V3.3.6-V17.26",
        "canonical_version_count": 121354,
        "document_count": 121354,
        "numeric_observation_count": 1051778,
        "document_error_count": 1378,
        "unresolved_tie_count": 1295,
        "authority": "CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256",
        "historical_current_f10_used_as_truth": False,
        "stage4_alpha_locked": True,
        "pass": False,
    }
    for field, expected in expected_audit.items():
        if current_audit.get(field) != expected:
            errors.append(
                f"current audit {field} expected={expected!r} "
                f"actual={current_audit.get(field)!r}"
            )

    return {
        "gate": "S3G1J_V17_26_FULL_BASIS_NON_REGRESSION_V2",
        "pass": not errors,
        "previous_document_count": len(previous),
        "current_document_count": len(current),
        "expected_changed_announcement_ids": sorted(TARGETS),
        "actual_changed_announcement_ids": sorted(changed_ids),
        "changed_documents": changed,
        "previous_document_error_count": previous_errors,
        "current_document_error_count": current_errors,
        "previous_unresolved_tie_count": previous_ties,
        "current_unresolved_tie_count": current_ties,
        "unexpected_regression_count": len(regressions),
        "unexpected_regression_announcement_ids": regressions,
        "target_numeric_observations": 3,
        "non_balance_target_concepts_allowed": False,
        "nested_evidence_order_preserved": True,
        "expected_stage3_final_verdict": "FAIL_CLOSED",
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--previous-audit", required=True)
    parser.add_argument("--current-audit", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    report = compare(
        read_documents(Path(args.previous)),
        read_documents(Path(args.current)),
        json.loads(Path(args.previous_audit).read_text(encoding="utf-8")),
        json.loads(Path(args.current_audit).read_text(encoding="utf-8")),
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
