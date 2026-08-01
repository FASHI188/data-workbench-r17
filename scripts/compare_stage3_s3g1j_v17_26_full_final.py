#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

EXPECTED_RECOVERIES = {
    "1207035181": "320e3a950a4768e73766d57a09bcf34d893d4da949b8ed5a1b2f887852e76229",
    "1221568845": "fa72059d35715f20df620691538528f720fe3ae42581c172c853f26799befb93",
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
    return canonical_document_error(value) if field == "document_error" else value


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

    comparable = (
        "document_status",
        "document_error",
        "tie_resolution",
        "selected_source_sha256",
        "selected_source_url",
        "numeric_observations",
    )
    changed: list[dict] = []
    regressions: list[str] = []
    for aid in sorted(set(previous) & set(current)):
        old = previous[aid]
        new = current[aid]
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
            errors.append(f"V17.26 full basis did not pass expected recovery {aid}")
        if new.get("document_error"):
            errors.append(f"V17.26 recovery retained document error {aid}")
        if new.get("selected_source_sha256") != expected_sha:
            errors.append(
                f"V17.26 target source SHA mismatch {aid} "
                f"expected={expected_sha} actual={new.get('selected_source_sha256')}"
            )
        if new.get("numeric_observations") != "3":
            errors.append(
                f"V17.26 target must expose exactly three observations {aid}: "
                f"{new.get('numeric_observations')}"
            )
        if new.get("tier1_found") != "0" or new.get("tier2_found") != "3":
            errors.append(f"V17.26 target tier scope changed {aid}")

    previous_errors = int(previous_audit.get("document_error_count", -1))
    current_errors = int(current_audit.get("document_error_count", -1))
    previous_ties = int(previous_audit.get("unresolved_tie_count", -1))
    current_ties = int(current_audit.get("unresolved_tie_count", -1))
    if previous_errors != 1380:
        errors.append(f"previous error count changed {previous_errors}")
    if current_errors != 1378 or current_errors != previous_errors - 2:
        errors.append(
            f"current error count mismatch previous={previous_errors} current={current_errors}"
        )
    if previous_ties != 1297 or current_ties != 1295:
        errors.append(
            f"unresolved tie count mismatch previous={previous_ties} current={current_ties}"
        )

    expected_identity = {
        "runtime_generation": "V17.26",
        "shard_gate": "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_26",
        "parser_method": "CNINFO_ORIGINAL_PDF_PYMUPDF_V16_V17_26_EXACT_SOURCE_BALANCE_ONLY_PRODUCTION",
        "methodology_version": "V3.3.6-V17.26",
        "canonical_version_count": 121354,
        "document_count": 121354,
        "numeric_observation_count": 1051778,
        "authority": "CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256",
        "historical_current_f10_used_as_truth": False,
        "stage4_alpha_locked": True,
    }
    for field, expected in expected_identity.items():
        if current_audit.get(field) != expected:
            errors.append(
                f"current audit {field} expected={expected!r} "
                f"actual={current_audit.get(field)!r}"
            )

    report = {
        "gate": "S3G1J_V17_26_FULL_BASIS_NON_REGRESSION",
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
        "target_numeric_observations": 3,
        "non_balance_target_concepts_allowed": False,
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
