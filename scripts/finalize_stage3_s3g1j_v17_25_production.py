#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

TARGET = "1207035181"
EXPECTED_V17_24 = {
    "1212731093",
    "1219311356",
    "1221568845",
    "1225153907",
}
EXPECTED_V17_25 = EXPECTED_V17_24 | {TARGET}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    paths = sorted(glob.glob(str(Path(args.root) / "shard-*" / "report.json")))
    errors: list[str] = []
    if len(paths) != 8:
        errors.append(f"expected 8 shard reports got {len(paths)}: {paths}")
    reports = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
    reports.sort(key=lambda row: int(row.get("shard", -1)))
    if [int(row.get("shard", -1)) for row in reports] != list(range(8)):
        errors.append("shard identity mismatch")
    if any(int(row.get("shards", -1)) != 8 for row in reports):
        errors.append("mixed shard geometry")
    if any(row.get("pass") is not True or row.get("errors") for row in reports):
        errors.append("one or more production shards failed")

    rows: dict[str, dict] = {}
    selected: set[str] = set()
    source_sha_matches = 0
    for report in reports:
        ids = {str(value) for value in report.get("selected_announcement_ids") or []}
        if selected & ids:
            errors.append("overlapping shard selected IDs")
        selected |= ids
        source_sha_matches += int(report.get("source_sha_match_count", 0))
        if int(report.get("input_count_exact83", -1)) != len(ids):
            errors.append(f"input count mismatch shard {report.get('shard')}")
        for row in report.get("results") or []:
            aid = str(row["announcement_id"])
            if aid not in ids:
                errors.append(f"result outside selected IDs {aid}")
            if aid in rows:
                errors.append(f"duplicate exact83 result {aid}")
            rows[aid] = row

    if len(selected) != 83 or len(rows) != 83 or set(rows) != selected:
        errors.append(
            f"exact83 identity mismatch selected={len(selected)} rows={len(rows)}"
        )
    if source_sha_matches != 83:
        errors.append(f"source SHA match count {source_sha_matches} != 83")

    recovered = {
        aid
        for aid, row in rows.items()
        if row.get("production_balance_sheet_recovered") is True
    }
    if recovered != EXPECTED_V17_25:
        errors.append(
            f"V17.25 recovery set mismatch expected={sorted(EXPECTED_V17_25)} actual={sorted(recovered)}"
        )
    legacy_rows = {
        aid: row for aid, row in rows.items() if row.get("was_v17_24_exact82") is True
    }
    if len(legacy_rows) != 82:
        errors.append(f"expected 82 legacy rows got {len(legacy_rows)}")
    legacy_recovered = {
        aid
        for aid, row in legacy_rows.items()
        if row.get("production_balance_sheet_recovered") is True
    }
    if legacy_recovered != EXPECTED_V17_24:
        errors.append("V17.24 legacy recovery set changed")

    target = rows.get(TARGET)
    if not target:
        errors.append("V17.25 target missing")
        target = {}
    block = target.get("balance_sheet_block") or {}
    if target.get("was_v17_24_exact82") is not False:
        errors.append("V17.25 target legacy flag changed")
    if target.get("v17_24_recovered") is not False:
        errors.append("V17.24 unexpectedly recovered V17.25 target")
    if target.get("production_balance_sheet_recovered") is not True:
        errors.append("V17.25 target did not recover")
    if target.get("validation_errors") != []:
        errors.append("V17.25 target retained validation errors")
    if block.get("arbitration") != (
        "V17_25_EXACT_SOURCE_GENERIC_GROUP_WITNESS_A_EQUALS_L_PLUS_E"
    ):
        errors.append("V17.25 target arbitration mismatch")
    if block.get("candidate_only") is not False:
        errors.append("V17.25 target remains candidate-only")
    if block.get("production_runtime_generation") != "V17.25":
        errors.append("V17.25 target production generation mismatch")
    if block.get("identity_tolerance") != "0.005":
        errors.append("V17.25 target tolerance mismatch")
    if block.get("column_role_gate_pass") is not True:
        errors.append("V17.25 target column-role gate failed")
    if block.get("e_equals_a_minus_l_inference") is not False:
        errors.append("V17.25 target inference gate failed")
    if block.get("global_row_tolerance_changed") is not False:
        errors.append("V17.25 target global tolerance gate failed")

    nonrecovered = [
        row
        for row in rows.values()
        if row.get("production_balance_sheet_recovered") is not True
    ]
    if len(nonrecovered) != 78:
        errors.append(f"remaining fail-closed count {len(nonrecovered)} != 78")
    if any(not list(row.get("validation_errors") or []) for row in nonrecovered):
        errors.append("nonrecovered exact83 row lost validation errors")

    report = {
        "gate": "S3G1J_V17_25_PRODUCTION_ACCEPTANCE",
        "pass": not errors,
        "input_count_exact83": 83,
        "source_sha_match_count": source_sha_matches,
        "production_recovered_announcement_ids": sorted(recovered),
        "previous_v17_24_recovery_announcement_ids": sorted(legacy_recovered),
        "incremental_v17_25_recovery_announcement_ids": [TARGET]
        if TARGET in recovered
        else [],
        "remaining_fail_closed_count": len(nonrecovered),
        "previous_82_results_required_equal_v17_24": True,
        "accounting_tolerance": "0.005",
        "global_row_tolerance_changed": False,
        "source_policy_changed": False,
        "fuzzy_alias_matching_enabled": False,
        "ocr_enabled": False,
        "e_equals_a_minus_l_inference": False,
        "production_data_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_locked": True,
        "target_result": target,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
