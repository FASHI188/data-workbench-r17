#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "governance/stage4_alpha_v1_training_execution_authorization.json"
PREREG = ROOT / "governance/stage4_alpha_v1_preregistration_v1_2_supersession.json"
FEATURE = ROOT / "governance/stage4_v1_feature_set_contract.json"
MATRIX = ROOT / "config/stage4_v1_feature_matrix_contract.json"
LABEL_EVIDENCE = ROOT / "governance/stage4_alpha_v1_development_labels_evidence.json"
ACCEPTED = ROOT / "governance/accepted_project_state.json"

EXPECTED_FEATURES = [
    "close_unadjusted","total_return_1d","total_return_5d","total_return_20d","realized_volatility_20d",
    "amount_ratio_5d_20d_stock","volume_ratio_5d_20d_stock","relative_strength_vs_market_20d",
    "regime_state","advance_ratio","net_breadth","ew_return_5d","ew_return_20d","net_breadth_5d_mean",
    "ew_return_vol_20d","cross_sectional_return_std_1d","amount_ratio_5d_20d",
    "fin_total_assets_cny","fin_total_liabilities_cny","fin_total_equity_cny","fin_parent_equity_cny",
    "fin_operating_revenue_cny","fin_operating_cost_cny","fin_parent_net_profit_cny",
    "fin_parent_net_profit_ex_nonrecurring_cny","fin_operating_cash_flow_cny",
    "fin_total_assets_cny_missing","fin_total_liabilities_cny_missing","fin_total_equity_cny_missing",
    "fin_parent_equity_cny_missing","fin_operating_revenue_cny_missing","fin_operating_cost_cny_missing",
    "fin_parent_net_profit_cny_missing","fin_parent_net_profit_ex_nonrecurring_cny_missing",
    "fin_operating_cash_flow_cny_missing","financial_report_age_sessions",
    "official_guidance_surprise","official_guidance_surprise_missing","guidance_age_sessions",
]


def fingerprint(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc["fingerprint_basis"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    auth = json.loads(AUTH.read_text(encoding="utf-8"))
    b = auth["fingerprint_basis"]
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    feature = json.loads(FEATURE.read_text(encoding="utf-8"))
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    evidence = json.loads(LABEL_EVIDENCE.read_text(encoding="utf-8"))
    accepted = json.loads(ACCEPTED.read_text(encoding="utf-8"))
    checks: dict[str, bool] = {}

    checks["authorization_fingerprint_exact"] = fingerprint(auth) == auth["fingerprint"] == "2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c"
    a = b["authority"]
    checks["authority_chain_exact"] = (
        a["feature_set_version"] == feature["feature_set_version"] == "V1.2"
        and a["feature_set_fingerprint"] == feature["feature_set_fingerprint"] == "d319ea1c236d580d0d032a055e4cdc07bf45e586ecbef664c6f4b3a8be98f9ff"
        and a["feature_matrix_artifact_id"] == 9168728086
        and a["feature_matrix_sha256"] == "c5fca80bc0f35c008590fe8f6cd7b8a16ab22e13b4978314a812f1ecb60b391c"
        and matrix["matrix_version"] == "V1.2"
        and a["preregistration_version"] == "V1.2"
        and a["preregistration_fingerprint"] == prereg["fingerprint"] == "b73f9b55efb04fac5416f6fdd39c17780b3f9e46c82d0da6b111547e3d258cf8"
        and a["development_labels_artifact_id"] == evidence["workflow"]["artifact_id"] == 9216418323
        and a["development_labels_artifact_digest"] == evidence["workflow"]["artifact_digest"]
        and a["development_labels_sha256"] == evidence["hashes"]["development_labels_sha256"]
        and a["development_split_seal_sha256"] == evidence["hashes"]["split_seal_sha256"]
        and evidence["status"] == "COMPLETE_IMMUTABLE_EVIDENCE"
        and evidence["independent_audit"]["pass"] is True
    )

    cols = b["feature_columns"]
    roles = b["feature_roles"]
    checks["feature_columns_exact_39"] = cols == EXPECTED_FEATURES and len(cols) == len(set(cols)) == 39
    role_union = set(roles["categorical"]) | set(roles["binary_missing_indicators"]) | set(roles["continuous_clip_train_only"])
    checks["feature_roles_partition_exact"] = (
        role_union == set(EXPECTED_FEATURES)
        and set(roles["categorical"]) == {"regime_state"}
        and set(roles["financial_signed_log1p"]).issubset(set(roles["continuous_clip_train_only"]))
        and not (set(roles["categorical"]) & set(roles["binary_missing_indicators"]))
        and not (set(roles["categorical"]) & set(roles["continuous_clip_train_only"]))
        and not (set(roles["binary_missing_indicators"]) & set(roles["continuous_clip_train_only"]))
    )
    out = set(feature["fingerprint_basis"]["explicit_out"])
    checks["explicit_out_remains_out"] = all(x not in set(cols) for x in [
        "GENERAL_WEB_NEWS","SOCIAL_MEDIA","CURRENT_INDUSTRY_BACKFILL","ETF_PRIMARY_FLOW_WITHOUT_STRICT_PIT",
    ]) and "INDUSTRY_IDENTITY_UNTIL_NORMALIZED_PIT_PLUGIN" in out

    pp = b["preprocessing"]
    checks["preprocessing_train_only"] = (
        pp["continuous_clip_quantiles"] == [0.001, 0.999]
        and pp["clip_fit_scope"] == "TRAIN_ROWS_ONLY_PER_SPLIT"
        and pp["dynamic_feature_selection_forbidden"] is True
        and pp["ridge"]["continuous_missing"] == "TRAIN_MEDIAN_IMPUTE_AFTER_TRANSFORM_AND_CLIP"
        and "FIT_ON_TRAIN_ONLY" in pp["ridge"]["standard_scaler"]
        and pp["hist_gradient_boosting"]["continuous_missing"] == "LEAVE_NAN_NATIVE"
        and pp["hist_gradient_boosting"]["scaling"] == "NONE"
    )

    candidates = b["candidate_catalog"]
    ridges = [c for c in candidates if c["family"] == "RIDGE_V1"]
    hgbs = [c for c in candidates if c["family"] == "HIST_GRADIENT_BOOSTING_V1"]
    checks["candidate_catalog_exact_11"] = (
        len(candidates) == 11
        and [c["candidate_id"] for c in candidates] == [f"C{i:03d}" for i in range(1, 12)]
        and [c["ordinal"] for c in candidates] == list(range(1, 12))
        and [c["params"]["alpha"] for c in ridges] == [1.0, 10.0, 100.0]
        and all(c["params"]["solver"] == "lsqr" and c["params"]["tol"] == 0.0001 for c in ridges)
        and len(hgbs) == 8
        and {(c["params"]["learning_rate"], c["params"]["max_leaf_nodes"], c["params"]["l2_regularization"]) for c in hgbs}
            == {(lr, leaf, l2) for lr in (0.03,0.07) for leaf in (15,31) for l2 in (1.0,10.0)}
        and all(c["params"]["max_iter"] == 200 and c["params"]["early_stopping"] is False and c["params"]["random_state"] == 20260813 for c in hgbs)
    )

    cv = b["cross_validation"]
    checks["causal_cv_and_trial_accounting_exact"] = (
        cv["split_count"] == 5
        and cv["future_train_to_past_test_forbidden"] is True
        and cv["split_boundaries_may_not_be_recomputed_or_shifted"] is True
        and cv["target_values_may_not_define_splits"] is True
        and cv["all_55_candidate_split_trials_must_be_logged"] is True
        and cv["failed_trial_remains_in_trial_count"] is True
        and cv["candidate_with_any_failed_split_is_not_selectable"] is True
    )

    metrics = b["metrics"]
    checks["selection_metric_exact"] = (
        metrics["primary_selection"] == "MEDIAN_OF_FIVE_SPLIT_MEAN_DAILY_SPEARMAN_IC_20D"
        and metrics["daily_spearman_20d"]["min_cross_section_rows"] == 20
        and metrics["selection_uses_costs"] is False
        and metrics["secondary_5d"] == "SAME_20D_TRAINED_PREDICTIONS_VS_EXCESS_RETURN_5D_NO_SEPARATE_5D_MODEL"
    )

    pbo = b["pbo"]
    checks["pbo_diagnostic_only_on_causal_oof"] = (
        pbo["scope"] == "ALL_11_CANDIDATES_CAUSAL_FORWARD_OOF_DAILY_IC_20D_SERIES"
        and pbo["time_blocks"] == 10
        and pbo["symmetric_combinations"] == math.comb(10,5) == 252
        and pbo["in_sample_blocks_per_combination"] == 5
        and pbo["promotion_ceiling"] == 0.2
        and pbo["model_refit_inside_pbo_forbidden"] is True
    )

    dsr = b["dsr"]
    checks["dsr_fixed_and_not_selection"] = (
        dsr["candidate_trial_count"] == 11
        and dsr["probability_floor"] == 0.95
        and dsr["does_not_change_candidate_selection"] is True
        and dsr["gate_series"] == "GROSS"
        and dsr["sharpe_annualization"] == "sqrt(252/20)"
    )

    runtime = b["runtime"]
    checks["runtime_versions_exact"] = runtime == {
        "os":"ubuntu-24.04","python":"3.12.13","numpy":"2.5.1","scipy":"1.17.0","scikit_learn":"1.9.0",
        "pyarrow":"25.0.0","duckdb":"1.3.2",
        "thread_env":{"OMP_NUM_THREADS":"1","MKL_NUM_THREADS":"1","OPENBLAS_NUM_THREADS":"1","NUMEXPR_NUM_THREADS":"1"},
        "candidate_jobs_max_parallel":4,
    }

    sem = b["authorization_semantics"]
    post = b["post_selection"]
    checks["authorization_fail_closed_until_separate_execution"] = (
        auth["status"] == "FROZEN_AUTHORIZATION_NO_FIT_IN_THIS_GATE"
        and sem["this_authorization_pr_contains_no_model_fit"] is True
        and sem["this_authorization_pr_contains_no_model_weights"] is True
        and sem["after_acceptance_exact_development_cv_fit_may_run_in_separate_execution_pr"] is True
        and sem["authoritative_model_output"] is False
        and sem["live_signal_allowed"] is False
        and sem["oos_label_access_allowed"] is False
        and sem["lockbox_label_access_allowed"] is False
        and sem["main_merge_allowed"] is False
        and post["development_final_refit_in_same_execution_allowed"] is False
        and post["final_refit_requires_separate_gate_after_candidate_selection"] is True
        and post["oos_access_still_forbidden"] is True
    )
    checks["accepted_state_currently_still_no_fit"] = (
        accepted["permissions"]["model_fit_allowed"] is False
        and accepted["permissions"]["oos_label_access_allowed"] is False
        and accepted["permissions"]["lockbox_label_access_allowed"] is False
        and accepted["permissions"]["live_signal_allowed"] is False
    )

    failed = [k for k,v in checks.items() if not v]
    report = {
        "gate":"STAGE4_ALPHA_V1_DEVELOPMENT_TRAINING_EXECUTION_AUTHORIZATION_CONTRACT",
        "pass":not failed,
        "authorization_fingerprint":auth["fingerprint"],
        "checks":checks,
        "failed_checks":failed,
        "feature_count":len(cols),
        "candidate_count":len(candidates),
        "causal_split_count":cv["split_count"],
        "required_candidate_split_trials":55,
        "model_fit_executed_in_this_gate":False,
        "model_weights_created_in_this_gate":False,
        "oos_label_access_allowed":False,
        "lockbox_label_access_allowed":False,
        "live_signal_allowed":False,
        "next_gate":auth["next_gate"],
    }
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
