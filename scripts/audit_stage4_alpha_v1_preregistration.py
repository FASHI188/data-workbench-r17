#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "governance/stage4_alpha_v1_preregistration.json"


def main() -> int:
    c = json.loads(CONTRACT.read_text(encoding="utf-8"))
    b = c["fingerprint_basis"]
    checks: dict[str, bool] = {}

    canonical = json.dumps(b, sort_keys=True, separators=(",", ":")).encode()
    checks["fingerprint_exact"] = hashlib.sha256(canonical).hexdigest() == c["fingerprint"]
    checks["status_no_label_no_training"] = c["status"] == "FROZEN_NO_LABEL_ACCESS_NO_TRAINING"

    a = b["authority"]
    checks["feature_authority_exact"] = (
        a["integration_base_sha"] == "ed8119f6033e57ef0195ea82c88b4e987ee13a47"
        and a["feature_set_version"] == "V1.2"
        and a["feature_set_fingerprint"] == "d319ea1c236d580d0d032a055e4cdc07bf45e586ecbef664c6f4b3a8be98f9ff"
        and a["feature_matrix_artifact_id"] == 9168728086
        and a["feature_matrix_sha256"] == "c5fca80bc0f35c008590fe8f6cd7b8a16ab22e13b4978314a812f1ecb60b391c"
        and a["feature_matrix_rows"] == 7924181
    )

    label = b["label_specification"]
    checks["label_time_is_post_decision_only"] = (
        label["decision_information_cut"] == "SESSION_T_CLOSE"
        and label["entry_reference"] == "NEXT_TRADING_SESSION_OPEN"
        and label["horizons_sessions"] == [5, 20]
        and label["primary_horizon_sessions"] == 20
        and label["future_data_is_label_only"] is True
        and label["no_forward_fill"] is True
    )
    checks["labels_separate_from_features"] = "SEPARATE_ARTIFACT" in label["label_feature_separation"]

    p = b["time_partitions"]
    checks["partitions_strictly_ordered"] = (
        p["development"]["end"] < p["oos_validation"]["start"]
        and p["oos_validation"]["end"] < p["final_lockbox"]["start"]
        and p["max_label_horizon_sessions"] == 20
        and p["boundary_purge_sessions"] == 20
        and p["boundary_embargo_sessions"] == 20
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
    computed = sum(x["candidate_count"] for x in budget["candidate_families"])
    checks["candidate_budget_exact"] = (
        computed == budget["total_candidate_configurations"] == budget["candidate_budget_hard_cap"] == 11
        and budget["posthoc_grid_expansion_forbidden"] is True
        and budget["new_candidate_requires_preregistration_supersession"] is True
    )

    prep = b["preprocessing"]
    checks["preprocessing_training_only"] = (
        prep["fit_on_training_partition_only"] is True
        and prep["oos_fitted_preprocessor_forbidden"] is True
        and prep["dynamic_feature_selection_forbidden"] is True
    )

    selection = b["selection_metric"]
    checks["selection_locked_before_oos"] = (
        selection["primary"] == "MEDIAN_ACROSS_CV_SPLITS_OF_MEAN_DAILY_CROSS_SECTIONAL_SPEARMAN_IC_20D"
        and selection["oos_metrics_must_not_change_selection"] is True
    )

    overfit = b["overfit_controls"]
    checks["multiple_testing_controls_required"] = (
        overfit["probability_of_backtest_overfitting_required"] is True
        and overfit["pbo_promotion_ceiling"] == 0.20
        and overfit["deflated_sharpe_ratio_required"] is True
        and overfit["dsr_probability_floor"] == 0.95
        and overfit["trial_count_must_include_failed_or_discarded_configs"] is True
        and overfit["trial_deletion_forbidden"] is True
    )

    perms = b["promotion_and_permissions"]
    checks["permissions_fail_closed"] = (
        perms["challenger_only"] is True
        and perms["label_materialization_allowed"] is False
        and perms["alpha_training_allowed"] is False
        and perms["oos_label_access_allowed"] is False
        and perms["final_lockbox_access_allowed"] is False
        and perms["live_signal_allowed"] is False
        and perms["authoritative_model_output"] is False
        and perms["promotion_requires_separate_governance_acceptance"] is True
        and perms["rollback_required"] is True
    )

    inv = c["invariants"]
    checks["no_outcome_payload_in_contract"] = (
        inv["no_real_labels_in_this_preregistration"] is True
        and inv["no_training_results_in_this_preregistration"] is True
        and inv["oos_validation_sealed"] is True
        and inv["final_lockbox_sealed"] is True
    )

    failed = [k for k, ok in checks.items() if not ok]
    out = {
        "gate": "STAGE4_ALPHA_V1_PREREGISTRATION_CONTRACT",
        "pass": not failed,
        "fingerprint": c["fingerprint"],
        "checks": checks,
        "failed_checks": failed,
        "label_materialization_allowed": False,
        "alpha_training_allowed": False,
        "oos_label_access_allowed": False,
        "final_lockbox_access_allowed": False,
        "live_signal_allowed": False,
        "next_gate": c["next_gate"],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
