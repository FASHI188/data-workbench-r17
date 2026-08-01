#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

EXPECTED_WITNESS_IDS = {
    "1200907104",
    "1201708762",
    "1202195310",
    "1202774611",
    "1203358200",
    "1204077386",
    "1205543437",
    "1207035181",
}
EXPECTED_NEGATIVE_IDS = {
    "1202799494",
    "1209806910",
    "1219834247",
}
EXPECTED_EXACT82_RECOVERED = {
    "1212731093",
    "1219311356",
    "1221568845",
    "1225153907",
}


def load_reports(root: Path, pattern: str, expected_count: int) -> list[dict]:
    paths = sorted(glob.glob(str(root / pattern)))
    if len(paths) != expected_count:
        raise ValueError(
            f"expected {expected_count} reports for {pattern}, got {len(paths)}: {paths}"
        )
    reports = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
    for report in reports:
        if report.get("pass") is not True or report.get("errors"):
            raise ValueError(
                f"shard not pass scope={report.get('scope')} index={report.get('shard_index')}"
            )
    geometry = sorted(int(report["shard_index"]) for report in reports)
    if geometry != list(range(expected_count)):
        raise ValueError(f"shard identity mismatch {geometry}")
    if any(int(report["shard_count"]) != expected_count for report in reports):
        raise ValueError("mixed shard_count")
    return reports


def unique_rows(reports: list[dict], expected_count: int, scope: str) -> list[dict]:
    rows: dict[str, dict] = {}
    selected: set[str] = set()
    for report in reports:
        if report.get("scope") != scope:
            raise ValueError(f"wrong scope {report.get('scope')} expected={scope}")
        selected_ids = {str(value) for value in report.get("selected_announcement_ids") or []}
        if selected & selected_ids:
            raise ValueError(f"overlapping selected IDs scope={scope}")
        selected |= selected_ids
        if int(report.get("selected_count", -1)) != len(selected_ids):
            raise ValueError(f"selected count mismatch scope={scope}")
        if int(report.get("processed_count", -1)) != len(report.get("results") or []):
            raise ValueError(f"processed count mismatch scope={scope}")
        if int(report.get("source_sha_match_count", -1)) != len(selected_ids):
            raise ValueError(f"source SHA count mismatch scope={scope}")
        for row in report.get("results") or []:
            aid = str(row["announcement_id"])
            if aid not in selected_ids:
                raise ValueError(f"row outside selected shard scope={scope} aid={aid}")
            if aid in rows:
                raise ValueError(f"duplicate row scope={scope} aid={aid}")
            rows[aid] = row
    if len(rows) != expected_count or len(selected) != expected_count:
        raise ValueError(
            f"combined count mismatch scope={scope} rows={len(rows)} selected={len(selected)}"
        )
    if set(rows) != selected:
        raise ValueError(f"selected/result identity mismatch scope={scope}")
    return [rows[aid] for aid in sorted(rows)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    p0_reports = load_reports(root, "p0-*/report.json", 2)
    exact82_reports = load_reports(root, "exact82-*/report.json", 8)
    p0_results = unique_rows(p0_reports, 22, "p0")
    exact82_results = unique_rows(exact82_reports, 82, "exact82")

    promoted_ids = sorted(
        str(row["announcement_id"])
        for row in p0_results
        if int(row["group_witness_diagnostic"]["promoted_generic_group_count"]) == 1
    )
    candidate_recovered_ids = sorted(
        str(row["announcement_id"])
        for row in p0_results
        if row["candidate_v17_25_recovered"]
    )
    negative_rows = {
        str(row["announcement_id"]): row
        for row in p0_results
        if str(row["announcement_id"]) in EXPECTED_NEGATIVE_IDS
    }
    missing_equity_ids = {
        str(row["announcement_id"])
        for row in p0_results
        if row["diagnostic_signature"] == "MISSING_CANDIDATES_TOTAL_EQUITY"
    }
    exact82_recovered = {
        str(row["announcement_id"])
        for row in exact82_results
        if row["recovered"]
    }

    errors: list[str] = []
    if set(promoted_ids) != EXPECTED_WITNESS_IDS:
        errors.append(
            f"witness promotion mismatch expected={sorted(EXPECTED_WITNESS_IDS)} actual={promoted_ids}"
        )
    if not set(candidate_recovered_ids).issubset(EXPECTED_WITNESS_IDS):
        errors.append(f"candidate recovery outside witness population {candidate_recovered_ids}")
    if len(negative_rows) != len(EXPECTED_NEGATIVE_IDS):
        errors.append("missing required negative rows")
    for aid, row in negative_rows.items():
        if int(row["group_witness_diagnostic"]["promoted_generic_group_count"]) != 0:
            errors.append(f"required negative promoted {aid}")
        if row["candidate_v17_25_recovered"]:
            errors.append(f"required negative recovered {aid}")
    if len(missing_equity_ids) != 11:
        errors.append(f"expected 11 missing-equity rows got {len(missing_equity_ids)}")
    overlap = set(candidate_recovered_ids) & missing_equity_ids
    if overlap:
        errors.append(f"missing-equity rows recovered {sorted(overlap)}")
    if exact82_recovered != EXPECTED_EXACT82_RECOVERED:
        errors.append(
            f"exact82 recovery set changed expected={sorted(EXPECTED_EXACT82_RECOVERED)} actual={sorted(exact82_recovered)}"
        )
    if any(not row.get("block_equal") for row in exact82_results):
        errors.append("exact82 block equality failed")
    if any(not row.get("validation_errors_equal") for row in exact82_results):
        errors.append("exact82 validation-error equality failed")

    source_sha_matches = sum(
        int(report["source_sha_match_count"])
        for report in p0_reports + exact82_reports
    )
    report = {
        "gate": "S3G1J_V17_25_GENERIC_GROUP_WITNESS_CANDIDATE_SAFETY_SHARDED",
        "source_p0_diagnostic_run": 30687837626,
        "source_v17_24_authority_run": 30685830808,
        "p0_shard_count": 2,
        "exact82_shard_count": 8,
        "p0_input_count": 22,
        "exact82_input_count": 82,
        "processed_p0_count": len(p0_results),
        "processed_exact82_count": len(exact82_results),
        "source_sha_match_count": source_sha_matches,
        "expected_group_witness_announcement_ids": sorted(EXPECTED_WITNESS_IDS),
        "promoted_group_witness_announcement_ids": promoted_ids,
        "candidate_recovered_announcement_ids": candidate_recovered_ids,
        "candidate_recovered_count": len(candidate_recovered_ids),
        "candidate_remaining_p0_fail_closed_count": 22 - len(candidate_recovered_ids),
        "required_negative_announcement_ids": sorted(EXPECTED_NEGATIVE_IDS),
        "missing_equity_population_count": len(missing_equity_ids),
        "exact82_recovery_announcement_ids": sorted(exact82_recovered),
        "p0_results": p0_results,
        "exact82_results": exact82_results,
        "execution_failures": [],
        "candidate_only": True,
        "parser_changed": True,
        "production_runtime_changed": False,
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "source_policy_changed": False,
        "fuzzy_alias_matching_enabled": False,
        "e_equals_a_minus_l_inference": False,
        "production_data_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_locked": True,
        "pass": not errors and source_sha_matches == 104,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in ("p0_results", "exact82_results")},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
