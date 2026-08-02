#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

EXPECTED_GENERIC_IDS = (
    "1200907104",
    "1201708762",
    "1202195310",
    "1202774611",
    "1203358200",
    "1204077386",
    "1205543437",
)
EXPECTED_IDENTITY_IDS = EXPECTED_GENERIC_IDS[:5]
EXPECTED_PERIOD_OR_ROLE_IDS = EXPECTED_GENERIC_IDS[5:]
EXPECTED_PROMOTED_PATTERNS = {
    '{"TOTAL_ASSETS":0,"TOTAL_EQUITY":0,"TOTAL_LIABILITIES":0}': 2,
    '{"TOTAL_ASSETS":3,"TOTAL_EQUITY":1,"TOTAL_LIABILITIES":1}': 5,
}
EXPECTED_FAILURE_STAGES = {
    "IDENTITY_PRESENT_BUT_DOWNSTREAM_COLUMN_GATE_FAILED": 5,
    "PERIOD_OR_ROLE_GATE_REMOVED_ALE_CANDIDATES": 2,
}


def _eligible(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in row.get("identity_combinations") or []
        if item.get("eligible_identity") is True
    ]


def _candidate_by_index(
    row: dict[str, Any], concept: str, index: int
) -> dict[str, Any]:
    candidates = (row.get("candidates") or {}).get(concept) or []
    if index < 0 or index >= len(candidates):
        raise ValueError(
            f"candidate index out of range aid={row.get('announcement_id')} "
            f"concept={concept} index={index} count={len(candidates)}"
        )
    return dict(candidates[index])


def validate_and_summarize(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("gate") != "S3G1J_V17_26_CURRENT_P0_GENERIC_CANDIDATE_SPATIAL_V2":
        raise ValueError(f"unexpected raw gate {raw.get('gate')}")
    if raw.get("pass") is not False:
        raise ValueError("V2 falsified-hypothesis report must remain pass=false")
    if raw.get("errors") != [] or raw.get("execution_failures") != []:
        raise ValueError("raw diagnostic contains execution failures")
    if raw.get("target_count") != 21 or raw.get("processed_count") != 21:
        raise ValueError("raw diagnostic population changed")
    if raw.get("source_sha_match_count") != 21:
        raise ValueError("not all source identities matched")
    if raw.get("generic_group_witness_promoted_announcement_ids") != list(
        EXPECTED_GENERIC_IDS
    ):
        raise ValueError("generic witness population changed")
    if raw.get("promoted_candidate_count_patterns") != EXPECTED_PROMOTED_PATTERNS:
        raise ValueError("promoted candidate patterns changed")
    if raw.get("promoted_candidate_failure_stage_counts") != EXPECTED_FAILURE_STAGES:
        raise ValueError("promoted failure-stage distribution changed")
    if raw.get("eligible_identity_combination_announcement_ids") != list(
        EXPECTED_IDENTITY_IDS
    ):
        raise ValueError("eligible identity population changed")
    if raw.get("eligible_identity_combination_count") != 5:
        raise ValueError("eligible identity count changed")
    if raw.get("identity_recovered_before_column_gate_count") != 0:
        raise ValueError("public diagnostic unexpectedly accepted an identity")
    if raw.get("candidate_recovered_count") != 0:
        raise ValueError("candidate diagnostic unexpectedly recovered a document")
    if raw.get("formal_runtime_changed") is not False:
        raise ValueError("formal runtime boundary changed")

    rows = {
        str(row.get("announcement_id")): row for row in raw.get("results") or []
    }
    if len(rows) != 21:
        raise ValueError(f"result identity count changed {len(rows)}")

    identity_details: list[dict[str, Any]] = []
    for aid in EXPECTED_IDENTITY_IDS:
        row = rows.get(aid)
        if row is None:
            raise ValueError(f"missing identity candidate row {aid}")
        if row.get("candidate_failure_stage") != (
            "IDENTITY_PRESENT_BUT_DOWNSTREAM_COLUMN_GATE_FAILED"
        ):
            raise ValueError(f"unexpected candidate stage {aid}")
        eligible = _eligible(row)
        if not eligible:
            raise ValueError(f"eligible identity absent {aid}")
        eligible.sort(
            key=lambda item: (
                Decimal(str(item["identity_relative_error"])),
                Decimal(str(item["identity_absolute_residual_cny"])),
                int(item["page_span"]),
                int(item["anchor_span"]),
            )
        )
        best = dict(eligible[0])
        indexes = best["candidate_indexes"]
        selected = {
            concept: _candidate_by_index(row, concept, int(indexes[concept]))
            for concept in (
                "TOTAL_ASSETS",
                "TOTAL_LIABILITIES",
                "TOTAL_EQUITY",
            )
        }
        if best.get("identity_tolerance_pass") is not True:
            raise ValueError(f"best identity outside tolerance {aid}")
        if Decimal(str(best["identity_relative_error"])) > Decimal("0.005"):
            raise ValueError(f"identity exceeds frozen tolerance {aid}")
        if row.get("identity_recovered_before_column_gate") is not False:
            raise ValueError(f"public diagnostic accepted identity {aid}")
        if row.get("candidate_recovered") is not False:
            raise ValueError(f"candidate recovery unexpectedly passed {aid}")
        identity_details.append(
            {
                "announcement_id": aid,
                "source_code": row.get("source_code"),
                "report_family": row.get("report_family"),
                "economic_date": row.get("economic_date"),
                "eligible_identity_combination_count": len(eligible),
                "best_identity": best,
                "selected_candidates": selected,
                "public_diagnostic_identity_recovered_before_column_gate": False,
                "public_diagnostic_recovered": False,
                "public_column_gate": row.get("column_role_gate") or {},
            }
        )

    period_or_role_details: list[dict[str, Any]] = []
    for aid in EXPECTED_PERIOD_OR_ROLE_IDS:
        row = rows.get(aid)
        if row is None:
            raise ValueError(f"missing period/role row {aid}")
        if row.get("candidate_failure_stage") != (
            "PERIOD_OR_ROLE_GATE_REMOVED_ALE_CANDIDATES"
        ):
            raise ValueError(f"unexpected period/role stage {aid}")
        counts = row.get("candidate_counts") or {}
        if any(int(counts.get(concept) or 0) != 0 for concept in counts):
            raise ValueError(f"period/role row retained candidates {aid}")
        period_or_role_details.append(
            {
                "announcement_id": aid,
                "source_code": row.get("source_code"),
                "report_family": row.get("report_family"),
                "economic_date": row.get("economic_date"),
                "candidate_counts": counts,
                "candidate_diagnostic": row.get("candidate_diagnostic") or {},
            }
        )

    return {
        "gate": "S3G1J_V17_26_CURRENT_P0_CANDIDATE_DETAIL_ACCEPTANCE_V3",
        "source_raw_gate": raw["gate"],
        "source_classifier_run": raw.get("source_classifier_run"),
        "source_full_basis_run": raw.get("source_full_basis_run"),
        "runtime_generation": "V17.26",
        "prior_hypothesis": "FIVE_000708_DOCUMENTS_HAVE_NO_IDENTITY_WITHIN_TOLERANCE",
        "prior_hypothesis_rejected": True,
        "accepted_observation": (
            "Five 000708 documents contain at least one role/page/anchor-eligible "
            "A=L+E identity within the frozen 0.005 tolerance, while the public "
            "candidate diagnostic still rejects them because its selected-equity "
            "source constraint is not satisfied. Two other generic-witness "
            "documents lose all A/L/E candidates at period-or-role gates."
        ),
        "generic_group_witness_count": 7,
        "identity_present_but_public_gate_rejected_count": 5,
        "identity_present_but_public_gate_rejected_announcement_ids": list(
            EXPECTED_IDENTITY_IDS
        ),
        "period_or_role_gate_removed_candidates_count": 2,
        "period_or_role_gate_removed_candidates_announcement_ids": list(
            EXPECTED_PERIOD_OR_ROLE_IDS
        ),
        "formal_public_candidate_recovered_count": 0,
        "identity_details": identity_details,
        "period_or_role_details": period_or_role_details,
        "parser_changed": False,
        "runtime_authority_changed": False,
        "production_data_changed": False,
        "trained_model_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_locked": True,
        "candidate_safety_required_before_recovery": True,
        "pass": True,
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-report", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    raw = json.loads(Path(args.raw_report).read_text(encoding="utf-8"))
    accepted = validate_and_summarize(raw)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(accepted, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(accepted, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
