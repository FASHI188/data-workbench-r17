#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

AUTH_PATH = Path('governance/stage4_alpha_v1_c007_final_refit_authorization.json')
SOURCE_AUTH_PATH = Path('governance/stage4_alpha_v1_training_execution_authorization.json')
CV_EVIDENCE_PATH = Path('governance/stage4_alpha_v1_development_cv_evidence.json')
LABEL_EVIDENCE_PATH = Path('governance/stage4_alpha_v1_development_labels_evidence.json')
STATE_PATH = Path('governance/accepted_project_state.json')
EXPECTED_FP = '7d5f88013329973c6c446d9210adbb9e60ba04a9fb615098e21318f1ab053295'
SOURCE_AUTH_FP = '2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c'


def canonical_hash(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def close(a: object, b: float, tol: float = 1e-12) -> bool:
    try:
        return math.isfinite(float(a)) and abs(float(a) - b) <= tol
    except Exception:
        return False


def main() -> int:
    auth = json.loads(AUTH_PATH.read_text(encoding='utf-8'))
    source = json.loads(SOURCE_AUTH_PATH.read_text(encoding='utf-8'))
    cv = json.loads(CV_EVIDENCE_PATH.read_text(encoding='utf-8'))
    labels = json.loads(LABEL_EVIDENCE_PATH.read_text(encoding='utf-8'))
    state = json.loads(STATE_PATH.read_text(encoding='utf-8'))
    b = auth['fingerprint_basis']
    checks: dict[str, bool] = {}

    checks['authorization_fingerprint_exact'] = (
        auth['status'] == 'FROZEN_AUTHORIZATION_NO_FIT_IN_THIS_GATE'
        and auth['fingerprint'] == EXPECTED_FP
        and canonical_hash(b) == EXPECTED_FP
        and auth['next_gate'] == 'SEPARATE_EXACT_HEAD_C007_FINAL_DEVELOPMENT_REFIT_EXECUTION_PR'
    )

    authority = b['authority']
    checks['authority_chain_exact'] = (
        authority['integration_base_sha'] == '0d4ee71b0a8f81111178c31d77d21a4fbf4704c3'
        and authority['effective_preregistration']['version'] == 'V1.2'
        and authority['effective_preregistration']['fingerprint'] == 'b73f9b55efb04fac5416f6fdd39c17780b3f9e46c82d0da6b111547e3d258cf8'
        and authority['source_development_cv_authorization_fingerprint'] == SOURCE_AUTH_FP
        and authority['source_development_cv_evidence'] == str(CV_EVIDENCE_PATH)
        and authority['source_development_cv_evidence_git_blob_sha'] == git_blob_sha(CV_EVIDENCE_PATH)
        and authority['development_cv_exact_head'] == 'c733d455d1f61723f0783c1809aa52ec4b0078b3'
        and authority['development_cv_run_id'] == 31898964450
        and authority['development_cv_aggregate_artifact_id'] == 9250847700
        and authority['development_cv_aggregate_artifact_digest'] == 'sha256:01eb4bd2e5e2a461e6cef09e4576b4b189622f52a70b210cee8b87887f2c80e1'
        and authority['candidate_selection_sha256'] == '1c6ea217913b28dcb5c84eed5862dff8d2cc05b7c344b90993afb31091e1418f'
    )

    checks['source_cv_authorization_exact'] = (
        source['fingerprint'] == SOURCE_AUTH_FP
        and canonical_hash(source['fingerprint_basis']) == SOURCE_AUTH_FP
        and source['fingerprint_basis']['post_selection']['development_final_refit_in_same_execution_allowed'] is False
        and source['fingerprint_basis']['post_selection']['final_refit_requires_separate_gate_after_candidate_selection'] is True
        and source['fingerprint_basis']['post_selection']['oos_access_still_forbidden'] is True
    )

    cv_auth = cv['authorization']
    cv_sel = cv['selection']
    cv_ctl = cv['overfit_controls']
    cv_seal = cv['sealed_scope']
    checks['development_cv_evidence_exact'] = (
        cv['status'] == 'COMPLETE_IMMUTABLE_EVIDENCE'
        and cv_auth['fingerprint'] == SOURCE_AUTH_FP
        and cv['implementation_head'] == 'c733d455d1f61723f0783c1809aa52ec4b0078b3'
        and cv['workflow']['run_id'] == 31898964450
        and cv['workflow']['artifact_id'] == 9250847700
        and cv['workflow']['artifact_digest'] == 'sha256:01eb4bd2e5e2a461e6cef09e4576b4b189622f52a70b210cee8b87887f2c80e1'
        and cv['development_cv']['candidate_count'] == 11
        and cv['development_cv']['required_trial_records'] == 55
        and cv['development_cv']['successful_trial_records'] == 55
        and cv['development_cv']['all_candidates_valid'] is True
        and cv_sel['selected_candidate'] == 'C007'
        and close(cv_sel['primary_median_split_mean_daily_ic_20d'], 0.09414053237378939)
        and close(cv_sel['worst_split_mean_daily_ic_20d'], 0.05311070572623114)
        and cv_ctl['pbo']['score_weighting'] == 'DAILY_OBSERVATION_WEIGHTED_ACROSS_SELECTED_BLOCKS'
        and close(cv_ctl['pbo']['value'], 0.11904761904761904)
        and cv_ctl['pbo']['pass'] is True
        and close(cv_ctl['dsr']['probability'], 0.9999989891602007)
        and cv_ctl['dsr']['pass'] is True
        and cv_ctl['independent_aggregate_audit']['pass'] is True
        and cv_ctl['research_gate_pass'] is True
        and cv_seal['final_development_refit_executed'] is False
        and cv_seal['oos_accessed'] is False
        and cv_seal['lockbox_accessed'] is False
        and cv_seal['live_signal_allowed'] is False
        and cv_seal['authoritative_model_output'] is False
    )

    source_c007 = next(c for c in source['fingerprint_basis']['candidate_catalog'] if c['candidate_id'] == 'C007')
    selected = b['selected_candidate']
    checks['selected_candidate_frozen_exact'] = (
        selected['candidate_id'] == 'C007'
        and selected['family'] == source_c007['family']
        and selected['ordinal'] == source_c007['ordinal'] == 7
        and selected['params'] == source_c007['params']
        and selected['selection_metric'] == source['fingerprint_basis']['metrics']['primary_selection']
        and selected['selection_frozen'] is True
        and selected['posthoc_parameter_changes_forbidden'] is True
    )

    pop = b['training_population']
    checks['development_population_exact'] = (
        pop['partition'] == 'DEVELOPMENT_ONLY'
        and pop['feature_date_start'] == '2015-01-05'
        and pop['feature_date_end'] == '2022-12-30'
        and pop['fit_filter'] == 'valid_label_20d == true'
        and pop['expected_fit_rows'] == labels['population']['valid_20d_rows'] == 5103016
        and pop['expected_latest_valid_20d_decision'] == labels['population']['latest_valid_20d_decision'] == '2022-12-02'
        and pop['join_key'] == source['fingerprint_basis']['keys']['join_key'] == ['trade_date', 'exchange', 'code']
        and pop['target'] == source['fingerprint_basis']['keys']['target'] == 'excess_return_20d'
        and pop['use_oos_rows'] is False
        and pop['use_lockbox_rows'] is False
    )

    checks['immutable_inputs_exact'] = (
        labels['status'] == 'COMPLETE_IMMUTABLE_EVIDENCE'
        and labels['workflow']['artifact_id'] == authority['development_labels_artifact_id'] == 9216418323
        and labels['workflow']['artifact_digest'] == authority['development_labels_artifact_digest']
        and labels['hashes']['development_labels_sha256'] == authority['development_labels_sha256'] == '092061da5666215dcc1f4fa75ec0b1cdbcc43969560755e7cdae6de55e64d673'
        and labels['independent_audit']['pass'] is True
        and authority['feature_matrix_artifact_id'] == 9168728086
        and authority['feature_matrix_sha256'] == 'c5fca80bc0f35c008590fe8f6cd7b8a16ab22e13b4978314a812f1ecb60b391c'
    )

    prep = b['preprocessing']
    checks['preprocessing_scope_exact'] = (
        prep['fit_scope'] == 'ALL_VALID20_DEVELOPMENT_FIT_ROWS_ONLY'
        and prep['financial_absolute_cny_transform'] == 'SIGNED_LOG1P'
        and prep['continuous_clip'] == 'FIT_0_001_AND_0_999_QUANTILES_ON_ALL_FINAL_FIT_ROWS_ONLY'
        and prep['continuous_missing'] == 'LEAVE_NAN_NATIVE_FOR_HIST_GRADIENT_BOOSTING'
        and prep['binary_missing_indicators'] == 'PASS_THROUGH_0_1'
        and prep['regime_state'] == 'ONE_HOT_LEXICOGRAPHIC_LEVELS_SEEN_IN_ALL_FINAL_FIT_ROWS_PLUS_EXPLICIT_UNKNOWN_FLAG'
        and prep['scaling'] == 'NONE'
        and prep['dynamic_feature_selection_forbidden'] is True
        and prep['oos_fitted_preprocessor_forbidden'] is True
    )

    runtime = b['runtime']
    source_runtime = source['fingerprint_basis']['runtime']
    checks['runtime_exact'] = all(runtime[k] == source_runtime[k] for k in ['os', 'python', 'numpy', 'scipy', 'scikit_learn', 'pyarrow', 'duckdb']) and runtime['thread_env'] == source_runtime['thread_env']

    fit = b['fit_execution']
    checks['single_use_fit_scope_exact'] = (
        fit['fit_count_exact'] == 1
        and fit['estimator'] == 'sklearn.ensemble.HistGradientBoostingRegressor'
        and fit['candidate_id'] == 'C007'
        and fit['final_development_refit_only'] is True
        and fit['candidate_reselection_forbidden'] is True
        and fit['hyperparameter_search_forbidden'] is True
        and fit['performance_metric_used_to_change_model_forbidden'] is True
        and fit['execution_must_be_separate_exact_head_pr'] is True
        and fit['authorization_single_use'] is True
    )

    out = b['output_contract']
    hard = b['hard_boundaries']
    checks['research_only_output_and_seals_exact'] = (
        out['research_model_weights_allowed'] is True
        and out['model_output_status'] == 'RESEARCH_ONLY_NON_AUTHORITATIVE'
        and out['training_prediction_performance_report_forbidden'] is True
        and out['oos_predictions_forbidden'] is True
        and out['lockbox_predictions_forbidden'] is True
        and hard['no_fit_in_authorization_gate'] is True
        and hard['oos_label_access_allowed'] is False
        and hard['lockbox_label_access_allowed'] is False
        and hard['live_signal_allowed'] is False
        and hard['main_merge_allowed'] is False
        and hard['authoritative_model_output_allowed'] is False
        and hard['current_champion_unchanged'] is True
    )

    p = state['permissions']
    checks['current_state_still_blocks_fit'] = (
        state['status'] == 'RESEARCH_ONLY'
        and p['model_fit_allowed'] is False
        and p['development_final_refit_allowed'] is False
        and p['oos_label_access_allowed'] is False
        and p['lockbox_label_access_allowed'] is False
        and p['live_signal_allowed'] is False
        and p['main_merge_allowed'] is False
        and p['authoritative_model_output_allowed'] is False
        and 'final development refit authorization' in state['next_business_gate'].lower()
    )

    failed = [k for k, v in checks.items() if not v]
    report = {
        'gate': 'STAGE4_ALPHA_V1_C007_FINAL_DEVELOPMENT_REFIT_AUTHORIZATION_INDEPENDENT_AUDIT',
        'pass': not failed,
        'authorization_fingerprint': auth['fingerprint'],
        'selected_candidate': selected['candidate_id'],
        'expected_fit_rows': pop['expected_fit_rows'],
        'checks': checks,
        'failed_checks': failed,
        'model_fit_executed': False,
        'oos_accessed': False,
        'lockbox_accessed': False,
        'live_signal_allowed': False,
        'authoritative_model_output': False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['pass'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
