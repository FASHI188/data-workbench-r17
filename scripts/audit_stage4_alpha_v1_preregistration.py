#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V10 = ROOT / "governance/stage4_alpha_v1_preregistration.json"
V11 = ROOT / "governance/stage4_alpha_v1_preregistration_v1_1_supersession.json"


def main() -> int:
    c = json.loads(V10.read_text(encoding="utf-8"))
    b = c["fingerprint_basis"]
    s = json.loads(V11.read_text(encoding="utf-8"))
    sb = s["fingerprint_basis"]
    checks: dict[str, bool] = {}

    checks["v1_0_fingerprint_exact"] = hashlib.sha256(
        json.dumps(b, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest() == c["fingerprint"] == "9cac700cd1043ee153bbc224de67725be3ce357dd9d25d6da02978c98a088589"
    checks["v1_1_fingerprint_exact"] = hashlib.sha256(
        json.dumps(sb, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest() == s["fingerprint"] == "e17875e4936ee957f30b7fa61282a107d41bc8ae9e52d4a7d8a17b61e0969853"
    checks["v1_1_supersedes_exact_v1_0"] = (
        sb["supersedes"]["version"] == c["version"] == "V1.0"
        and sb["supersedes"]["fingerprint"] == c["fingerprint"]
        and sb["version"] == "V1.1"
    )
    checks["status_no_label_no_training"] = (
        c["status"] == "FROZEN_NO_LABEL_ACCESS_NO_TRAINING"
        and s["status"] == "FROZEN_NO_LABEL_ACCESS_NO_TRAINING"
    )

    a = b["authority"]
    checks["feature_authority_exact"] = (
        a["feature_set_version"] == "V1.2"
        and a["feature_set_fingerprint"] == "d319ea1c236d580d0d032a055e4cdc07bf45e586ecbef664c6f4b3a8be98f9ff"
        and a["feature_matrix_artifact_id"] == 9168728086
        and a["feature_matrix_sha256"] == "c5fca80bc0f35c008590fe8f6cd7b8a16ab22e13b4978314a812f1ecb60b391c"
        and a["feature_matrix_rows"] == 7924181
        and sb["authority"]["feature_matrix_artifact_id"] == a["feature_matrix_artifact_id"]
        and sb["authority"]["feature_matrix_sha256"] == a["feature_matrix_sha256"]
    )

    label = b["label_specification"]
    checks["label_time_is_post_decision_only"] = (
        label["decision_information_cut"] == "SESSION_T_CLOSE"
        and label["entry_reference"] == "NEXT_TRADING_SESSION_OPEN"
        and label["horizons_sessions"] == [5, 20]
        and label["primary_horizon_sessions"] == 20
        and label["future_data_is_label_only"] is True
        and label["no_forward_fill"] is True
        and "SEPARATE_ARTIFACT" in label["label_feature_separation"]
    )

    x = sb["boundary_semantics"]
    checks["development_boundary_sealed"] = (
        x["development"]["latest_labelable_decision"] == "2022-12-02"
        and x["development"]["corresponding_entry"] == "2022-12-05"
        and x["development"]["corresponding_20d_exit"] == "2022-12-30"
        and x["development"]["next_sealed_partition_start"] == "2023-01-03"
        and x["development"]["corresponding_20d_exit"] < x["development"]["next_sealed_partition_start"]
    )
    checks["oos_boundary_sealed"] = (
        x["oos_validation"]["latest_labelable_decision"] == "2024-12-03"
        and x["oos_validation"]["corresponding_entry"] == "2024-12-04"
        and x["oos_validation"]["corresponding_20d_exit"] == "2024-12-31"
        and x["oos_validation"]["next_sealed_partition_start"] == "2025-01-02"
        and x["oos_validation"]["corresponding_20d_exit"] < x["oos_validation"]["next_sealed_partition_start"]
    )
    checks["lockbox_current_cutoff_sealed"] = (
        x["final_lockbox_as_of_current_data"]["latest_fully_labelable_decision"] == "2026-07-15"
        and x["final_lockbox_as_of_current_data"]["corresponding_entry"] == "2026-07-16"
        and x["final_lockbox_as_of_current_data"]["corresponding_20d_exit"] == "2026-08-12"
        and x["final_lockbox_as_of_current_data"]["data_cutoff"] == "2026-08-12"
        and x["final_lockbox_as_of_current_data"]["later_decisions_status"] == "UNSCORABLE_AS_OF_DATA_CUTOFF_NOT_FAILURE"
    )

    cv = b["development_cross_validation"]
    checks["purged_cv_exact"] = (
        cv["method"] == "COMBINATORIAL_PURGED_BLOCK_CV"
        and cv["calendar_blocks"] == 6
        and cv["test_blocks_per_split"] == 2
        and cv["expected_combinations"] == 15
        and cv["purge_sessions"] == 20
        and cv["embargo_sessions"] == 20
        and cv["random_kfold_forbidden"] is True
        and cv["future_train_to_past_test_forbidden"] is True
    )

    budget = b["model_search_budget"]
    checks["candidate_budget_exact"] = (
        sum(v["candidate_count"] for v in budget["candidate_families"]) == 11
        and budget["total_candidate_configurations"] == 11
        and budget["candidate_budget_hard_cap"] == 11
        and budget["posthoc_grid_expansion_forbidden"] is True
    )

    perms = b["promotion_and_permissions"]
    hb = sb["hard_boundaries"]
    checks["permissions_fail_closed"] = (
        perms["challenger_only"] is True
        and perms["label_materialization_allowed"] is False
        and perms["alpha_training_allowed"] is False
        and perms["oos_label_access_allowed"] is False
        and perms["final_lockbox_access_allowed"] is False
        and perms["live_signal_allowed"] is False
        and perms["authoritative_model_output"] is False
        and hb["development_label_builder_must_not_read_market_rows_on_or_after_2023_01_03"] is True
        and hb["oos_label_builder_must_not_read_market_rows_on_or_after_2025_01_02"] is True
        and hb["no_training_in_this_supersession"] is True
        and hb["no_oos_label_access_in_this_supersession"] is True
        and hb["no_lockbox_label_access_in_this_supersession"] is True
    )

    failed = [k for k, ok in checks.items() if not ok]
    out = {
        "gate": "STAGE4_ALPHA_V1_PREREGISTRATION_V1_1_CONTRACT",
        "pass": not failed,
        "effective_version": "V1.1",
        "v1_0_fingerprint": c["fingerprint"],
        "v1_1_fingerprint": s["fingerprint"],
        "checks": checks,
        "failed_checks": failed,
        "label_materialization_allowed": False,
        "alpha_training_allowed": False,
        "oos_label_access_allowed": False,
        "final_lockbox_access_allowed": False,
        "live_signal_allowed": False,
        "next_gate": s["next_gate"]
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
