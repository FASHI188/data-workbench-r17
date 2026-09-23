#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V10 = ROOT / "governance/stage4_alpha_v1_preregistration.json"
V11 = ROOT / "governance/stage4_alpha_v1_preregistration_v1_1_supersession.json"
V12 = ROOT / "governance/stage4_alpha_v1_preregistration_v1_2_supersession.json"


def fp(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc["fingerprint_basis"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    v10 = json.loads(V10.read_text(encoding="utf-8"))
    v11 = json.loads(V11.read_text(encoding="utf-8"))
    v12 = json.loads(V12.read_text(encoding="utf-8"))
    b10, b11, b12 = v10["fingerprint_basis"], v11["fingerprint_basis"], v12["fingerprint_basis"]
    checks: dict[str, bool] = {}

    checks["fingerprints_exact"] = (
        fp(v10) == v10["fingerprint"] == "9cac700cd1043ee153bbc224de67725be3ce357dd9d25d6da02978c98a088589"
        and fp(v11) == v11["fingerprint"] == "e17875e4936ee957f30b7fa61282a107d41bc8ae9e52d4a7d8a17b61e0969853"
        and fp(v12) == v12["fingerprint"] == "b73f9b55efb04fac5416f6fdd39c17780b3f9e46c82d0da6b111547e3d258cf8"
    )
    checks["supersession_chain_exact"] = (
        b11["supersedes"] == {"version": "V1.0", "fingerprint": v10["fingerprint"]}
        and b12["supersedes"] == {"version": "V1.1", "fingerprint": v11["fingerprint"]}
        and b12["version"] == "V1.2"
    )
    checks["all_prereg_versions_no_label_no_training"] = all(
        d["status"] == "FROZEN_NO_LABEL_ACCESS_NO_TRAINING" for d in (v10, v11, v12)
    )

    a = b10["authority"]
    a12 = b12["authority"]
    checks["feature_authority_exact"] = (
        a["feature_set_version"] == "V1.2"
        and a["feature_set_fingerprint"] == "d319ea1c236d580d0d032a055e4cdc07bf45e586ecbef664c6f4b3a8be98f9ff"
        and a["feature_matrix_artifact_id"] == a12["feature_matrix_artifact_id"] == 9168728086
        and a["feature_matrix_sha256"] == a12["feature_matrix_sha256"] == "c5fca80bc0f35c008590fe8f6cd7b8a16ab22e13b4978314a812f1ecb60b391c"
        and a["feature_matrix_rows"] == 7924181
        and a12["historical_ohlcv_artifact_id"] == 8651700277
        and a12["historical_g5_adjustment_artifact_id"] == 8651976824
    )

    label = b10["label_specification"]
    checks["label_specification_unchanged"] = (
        label["decision_information_cut"] == "SESSION_T_CLOSE"
        and label["entry_reference"] == "NEXT_TRADING_SESSION_OPEN"
        and label["horizons_sessions"] == [5, 20]
        and label["primary_horizon_sessions"] == 20
        and label["future_data_is_label_only"] is True
        and label["no_forward_fill"] is True
        and "SEPARATE_ARTIFACT" in label["label_feature_separation"]
    )

    x = b11["boundary_semantics"]
    checks["v1_1_horizon_boundary_seal_preserved"] = (
        x["development"]["latest_labelable_decision"] == "2022-12-02"
        and x["development"]["corresponding_entry"] == "2022-12-05"
        and x["development"]["corresponding_20d_exit"] == "2022-12-30"
        and x["development"]["next_sealed_partition_start"] == "2023-01-03"
        and x["oos_validation"]["latest_labelable_decision"] == "2024-12-03"
        and x["final_lockbox_as_of_current_data"]["latest_fully_labelable_decision"] == "2026-07-15"
    )

    old_cv = b10["development_cross_validation"]
    defect = b12["defect_being_corrected"]
    checks["v1_1_cv_contradiction_explicitly_frozen_as_defect"] = (
        old_cv["method"] == defect["v1_1_cv_method"] == "COMBINATORIAL_PURGED_BLOCK_CV"
        and old_cv["calendar_blocks"] == defect["calendar_blocks"] == 6
        and old_cv["test_blocks_per_split"] == defect["test_blocks_per_split"] == 2
        and old_cv["expected_combinations"] == defect["expected_combinations"] == 15
        and old_cv["future_train_to_past_test_forbidden"] is defect["future_train_to_past_test_forbidden"] is True
        and defect["detected_before_development_label_materialization"] is True
        and defect["detected_before_any_model_fit"] is True
    )

    cv = b12["causal_development_cross_validation"]
    checks["causal_cv_executable"] = (
        cv["method"] == "ANCHORED_PURGED_EXPANDING_WINDOW_BLOCK_CV"
        and cv["calendar_blocks"] == 6
        and cv["initial_train_blocks"] == 1
        and cv["evaluation_splits"] == 5
        and cv["block_order"] == "STRICT_CHRONOLOGICAL_CONTIGUOUS"
        and cv["training_sets_expand_monotonically"] is True
        and cv["test_set_is_single_next_block"] is True
        and cv["purge_sessions_before_test"] == 20
        and cv["post_test_embargo_sessions"] == 20
        and cv["future_train_to_past_test_forbidden"] is True
        and cv["random_kfold_forbidden"] is True
        and cv["split_seal_must_freeze_exact_block_boundaries_before_fit"] is True
        and cv["split_seal_must_be_label_value_blind"] is True
    )

    pbo = b12["pbo_semantics"]
    checks["pbo_uses_only_causal_forward_oof_performance"] = (
        pbo["threshold_max"] == 0.2
        and pbo["method"] == "CSCV_ON_CAUSAL_FORWARD_OOF_CANDIDATE_PERFORMANCE_SERIES"
        and pbo["model_refit_inside_pbo_forbidden"] is True
        and pbo["future_trained_predictions_inside_pbo_forbidden"] is True
        and pbo["pbo_does_not_define_or_modify_cv_splits"] is True
    )

    budget = b10["model_search_budget"]
    checks["candidate_budget_unchanged"] = (
        sum(v["candidate_count"] for v in budget["candidate_families"]) == 11
        and budget["total_candidate_configurations"] == 11
        and budget["candidate_budget_hard_cap"] == 11
        and budget["posthoc_grid_expansion_forbidden"] is True
    )

    perms = b10["promotion_and_permissions"]
    hb11, hb12 = b11["hard_boundaries"], b12["hard_boundaries"]
    checks["permissions_fail_closed"] = (
        perms["challenger_only"] is True
        and perms["label_materialization_allowed"] is False
        and perms["alpha_training_allowed"] is False
        and perms["oos_label_access_allowed"] is False
        and perms["final_lockbox_access_allowed"] is False
        and perms["live_signal_allowed"] is False
        and hb11["development_label_builder_must_not_read_market_rows_on_or_after_2023_01_03"] is True
        and hb12["no_label_materialization_in_this_supersession"] is True
        and hb12["no_model_fit_in_this_supersession"] is True
        and hb12["no_oos_label_access"] is True
        and hb12["no_lockbox_label_access"] is True
        and hb12["main_unchanged"] is True
    )

    failed = [k for k, ok in checks.items() if not ok]
    out = {
        "gate": "STAGE4_ALPHA_V1_PREREGISTRATION_V1_2_CAUSAL_CV_CONTRACT",
        "pass": not failed,
        "effective_version": "V1.2",
        "v1_0_fingerprint": v10["fingerprint"],
        "v1_1_fingerprint": v11["fingerprint"],
        "v1_2_fingerprint": v12["fingerprint"],
        "checks": checks,
        "failed_checks": failed,
        "label_materialization_allowed": False,
        "alpha_training_allowed": False,
        "oos_label_access_allowed": False,
        "final_lockbox_access_allowed": False,
        "live_signal_allowed": False,
        "next_gate": v12["next_gate"]
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
