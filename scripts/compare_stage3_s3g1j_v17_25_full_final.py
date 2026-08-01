#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

EXPECTED_RECOVERIES = {
    "1207035181": "320e3a950a4768e73766d57a09bcf34d893d4da949b8ed5a1b2f887852e76229",
    "1221568845": None,
}


def read_documents(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    out: dict[str, dict] = {}
    for row in rows:
        aid = str(row["announcement_id"])
        if aid in out:
            raise ValueError(f"duplicate document announcement {aid}")
        out[aid] = row
    return out


def _normalize_json(value):
    if isinstance(value, dict):
        return {key: _normalize_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [_normalize_json(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    return value


def canonical_document_error(value: str) -> str:
    """Canonicalize structured error evidence without changing its content.

    Historical tie/value-conflict errors are JSON arrays whose element order can vary
    when equivalent evidence is rebuilt. The array order is not semantic, but every
    key, scalar, duplicate and nested value remains part of the comparison.
    Non-JSON errors are compared byte-for-byte as before.
    """
    if not value:
        return ""
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
    return json.dumps(
        _normalize_json(parsed),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def comparable_value(row: dict, field: str) -> str:
    value = row.get(field, "")
    if field == "document_error":
        return canonical_document_error(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--previous-audit", required=True)
    parser.add_argument("--current-audit", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    previous = read_documents(Path(args.previous))
    current = read_documents(Path(args.current))
    previous_audit = json.loads(Path(args.previous_audit).read_text(encoding="utf-8"))
    current_audit = json.loads(Path(args.current_audit).read_text(encoding="utf-8"))
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
        comparable = (
            "document_status",
            "document_error",
            "tie_resolution",
            "selected_source_sha256",
            "selected_source_url",
            "numeric_observations",
        )
        delta = {
            field: {"previous": old.get(field, ""), "current": new.get(field, "")}
            for field in comparable
            if comparable_value(old, field) != comparable_value(new, field)
        }
        if delta:
            changed.append({"announcement_id": aid, "delta": delta})
            if aid not in EXPECTED_RECOVERIES:
                regressions.append(aid)

    changed_ids = {row["announcement_id"] for row in changed}
    if changed_ids != set(EXPECTED_RECOVERIES):
        errors.append(
            f"full-basis document delta mismatch expected={sorted(EXPECTED_RECOVERIES)} "
            f"actual={sorted(changed_ids)}"
        )
    if regressions:
        errors.append(f"unexpected non-target document changes {regressions[:20]}")

    for aid, expected_sha in EXPECTED_RECOVERIES.items():
        old = previous.get(aid) or {}
        new = current.get(aid) or {}
        if old.get("document_status") == "PASS":
            errors.append(f"previous full basis already passed expected recovery {aid}")
        if new.get("document_status") != "PASS":
            errors.append(f"V17.25 full basis did not pass expected recovery {aid}")
        if new.get("document_error"):
            errors.append(f"V17.25 recovery retained document error {aid}")
        if not new.get("selected_source_sha256"):
            errors.append(f"V17.25 recovery missing selected source SHA {aid}")
        if expected_sha and new.get("selected_source_sha256") != expected_sha:
            errors.append(
                f"V17.25 target source SHA mismatch {aid} "
                f"expected={expected_sha} actual={new.get('selected_source_sha256')}"
            )
        if int(new.get("numeric_observations") or 0) <= int(
            old.get("numeric_observations") or 0
        ):
            errors.append(f"V17.25 recovery did not add numeric observations {aid}")

    previous_errors = int(previous_audit.get("document_error_count", -1))
    current_errors = int(current_audit.get("document_error_count", -1))
    previous_ties = int(previous_audit.get("unresolved_tie_count", -1))
    current_ties = int(current_audit.get("unresolved_tie_count", -1))
    if previous_errors != 1380:
        errors.append(f"previous error count changed {previous_errors}")
    if current_errors != 1378:
        errors.append(f"current error count expected 1378 got {current_errors}")
    if current_errors != previous_errors - 2:
        errors.append(
            f"error count delta mismatch previous={previous_errors} current={current_errors}"
        )
    if previous_ties != 1297:
        errors.append(f"previous unresolved tie count changed {previous_ties}")
    if current_ties != 1295:
        errors.append(f"current unresolved tie count expected 1295 got {current_ties}")

    if current_audit.get("runtime_generation") != "V17.25":
        errors.append("current audit runtime generation is not V17.25")
    if current_audit.get("shard_gate") != (
        "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_25"
    ):
        errors.append("current audit shard gate is not V17.25")
    if current_audit.get("parser_method") != (
        "CNINFO_ORIGINAL_PDF_PYMUPDF_V15_V17_25_EXACT_SOURCE_GENERIC_GROUP_WITNESS_PRODUCTION"
    ):
        errors.append("current audit parser/extractor method is not V17.25")
    if current_audit.get("methodology_version") != "V3.3.5-V17.25":
        errors.append("current audit methodology is not V17.25")
    if current_audit.get("canonical_version_count") != 121354:
        errors.append("current canonical count changed")
    if current_audit.get("document_count") != 121354:
        errors.append("current document count changed")
    if current_audit.get("authority") != "CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256":
        errors.append("current PDF authority changed")
    if current_audit.get("historical_current_f10_used_as_truth") is not False:
        errors.append("historical current F10 became truth")
    if current_audit.get("stage4_alpha_locked") is not True:
        errors.append("Stage4/Alpha lock changed")

    report = {
        "gate": "S3G1J_V17_25_FULL_BASIS_NON_REGRESSION",
        "pass": not errors,
        "previous_document_count": len(previous),
        "current_document_count": len(current),
        "expected_changed_announcement_ids": sorted(EXPECTED_RECOVERIES),
        "actual_changed_announcement_ids": sorted(changed_ids),
        "changed_documents": changed,
        "previous_document_error_count": previous_errors,
        "current_document_error_count": current_errors,
        "previous_unresolved_tie_count": previous_ties,
        "current_unresolved_tie_count": current_ties,
        "unexpected_regression_count": len(regressions),
        "unexpected_regression_announcement_ids": regressions,
        "stage3_final_pass": current_audit.get("pass") is True,
        "expected_stage3_final_verdict": "FAIL_CLOSED"
        if current_audit.get("pass") is not True
        else "PASS",
        "errors": errors,
    }
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
