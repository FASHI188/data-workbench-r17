#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V30_RUN = 31518370789
V30_HEAD = 'a18b81a9f38692533d0427f4a5b50767abf1a7c8'
V30_ARTIFACT_ID = 9112098872
V30_DIGEST = 'sha256:706c6dd7252a64fd5c2956df6c594b5c91de29f02ca7d0553fa932017e8867ba'
RET_RUN = 31555404674
RET_HEAD = 'bf32938fea81b6133592f7f3ba2456897e65bd1d'
RET_ARTIFACT_ID = 9125809076
RET_DIGEST = 'sha256:d0921e3069abb695de54de4d3ecec5a5394e831a820757d1b2e2fda02861722a'
RET_LEDGER = '706b5dd219e94f786674b549859dd4695b42a02bcceb42fae8f91d358eeb83ef'
S3G4_RUN = 31557811596
S3G4_HEAD = 'fe722f82f599489f4fcf86cefc47afe1c9235b64'
S3G4_ARTIFACT_ID = 9126607328
S3G4_DIGEST = 'sha256:b87e822278f044f8fd6dd5a8cf7bb2e342890b27086951d377d73ed70c7bd4b3'
S3G4_FORECAST_SHA = '6912b2297b01c97a91b764e96d4d586982517ec68b20e25a24606cdc67ff74d6'
S3G4_SURPRISE_SHA = '8c12874918139b159235f03e7071a1942f1d0888b4603a16c9858634bf65e072'


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def main() -> int:
    errors: list[str] = []

    def req(ok: bool, msg: str) -> None:
        if not ok:
            errors.append(msg)

    authority = load('governance/stage3_authority_map.json')
    runtime = load('governance/stage3_s3g1j_runtime_manifest.json')
    activation = load('governance/stage3_workflow_activation_manifest.json')
    lock = load('config/stage3_final_lock.json')
    project = load('data/project_status.json')
    promotion = load('governance/stage3_s3g1j_v17_30_runtime_promotion.json')
    wrapper = load('governance/stage3_s3g1j_v17_30_runtime_wrapper_acceptance.json')
    retention = load('governance/stage3_s3g1j_v17_30_residual_retention.json')

    # Current central state may be either component-gates-complete (PR133) or the
    # immediately following historical final freeze. Immutable raw/history facts
    # below must remain exact in both states.
    req(authority.get('schema_version') in {9, 10}, 'authority schema drift')
    req(authority.get('status') in {
        'ALL_COMPONENT_GATES_PASS_FINAL_FREEZE_PENDING',
        'STAGE3_HISTORICAL_FINAL_FREEZE_PASS',
    }, 'authority current status drift')
    req(runtime.get('schema_version') == 15, 'runtime schema drift')
    req(activation.get('schema_version') >= 17, 'activation schema drift')
    req(lock.get('version') in {
        'V3.3.16-stage3-component-gates-complete',
        'V3.3.17-stage3-historical-final-freeze',
    }, 'lock version drift')
    req(lock.get('status') in {'NOT_READY', 'PASS_FROZEN_HISTORICAL'}, 'lock status drift')
    req(project.get('schema_version') == 8, 'project schema drift')

    formal = runtime.get('formal_runtime') or {}
    current = runtime.get('current_production_authority') or {}
    latest = runtime.get('full_basis_last_completed_final') or {}
    next_basis = runtime.get('next_full_basis_required') or {}
    req(current.get('generation') == 'V17.30', 'current runtime must V17.30')
    req(formal.get('runtime_generation') == 'V17.30', 'formal runtime must V17.30')
    req(formal.get('parser_git_blob') == 'cc782817e5ee73fcae085d71f4896a0adc004dcd', 'parser blob drift')
    req(formal.get('extractor_git_blob') == 'd74a2b1f8f0ec3af8d89ce259e83392d7f8cc20c', 'extractor blob drift')
    req(
        latest.get('generation') == 'V17.30'
        and latest.get('run') == V30_RUN
        and latest.get('head_sha') == V30_HEAD
        and latest.get('artifact_id') == V30_ARTIFACT_ID
        and latest.get('artifact_digest') == V30_DIGEST,
        'raw latest V17.30 authority drift',
    )
    req(
        latest.get('document_rows') == 121354
        and latest.get('numeric_observations') == 1051826
        and latest.get('document_error_count') == 1362
        and latest.get('unresolved_tie_count') == 1279
        and latest.get('verdict') == 'FAIL_CLOSED',
        'raw V17.30 basis facts drift',
    )
    req(next_basis.get('generation') is None and next_basis.get('status') == 'NONE_CURRENT_RUNTIME_ACCEPTED', 'next basis drift')

    promo = promotion.get('next_full_basis') or {}
    req(promo.get('status') == 'REQUIRED_NOT_STARTED', 'historical promotion checkpoint drift')
    req((wrapper.get('execution_pr') or {}).get('closed_without_merge') is True, 'wrapper evidence drift')
    active = activation.get('accepted_production_runtime') or {}
    req(
        active.get('generation') == 'V17.30'
        and active.get('last_completed_full_basis_run') == V30_RUN
        and active.get('data_verdict') == 'FAIL_CLOSED',
        'activation raw authority drift',
    )

    req(
        retention.get('gate') == 'S3G1J_V17_30_RESIDUAL_RETENTION_GOVERNANCE'
        and retention.get('governance_pr') == 130,
        'retention governance identity drift',
    )
    rr = retention.get('accepted_run') or {}
    req(
        rr.get('run_id') == RET_RUN
        and rr.get('artifact_id') == RET_ARTIFACT_ID
        and rr.get('artifact_digest') == RET_DIGEST
        and rr.get('ledger_sha256') == RET_LEDGER,
        'retention artifact identity drift',
    )
    src = retention.get('source_full_basis') or {}
    req(
        src.get('document_error_count') == 1362
        and src.get('unresolved_tie_count') == 1279
        and src.get('raw_data_verdict') == 'FAIL_CLOSED',
        'retention raw source drift',
    )
    res = retention.get('retention_result') or {}
    req(
        res.get('retained_document_count') == 1362
        and res.get('retained_unresolved_tie_count') == 1279
        and res.get('raw_errors_removed') is False
        and res.get('raw_ties_removed') is False,
        'retention count semantics drift',
    )
    req(
        res.get('retained_rows_usable_as_numeric_truth') is False
        and res.get('retained_rows_must_be_excluded_from_numeric_feature_values') is True,
        'retention downstream semantics drift',
    )
    hard = retention.get('hard_boundaries') or {}
    req(all(hard.get(k) is False for k in [
        'OCR_allowed', 'fuzzy_alias_allowed', 'E_equals_A_minus_L_inference_allowed',
        'issuer_gate_relaxation_allowed', 'PIT_relaxation_allowed',
        'accounting_tolerance_relaxation_allowed', 'stage4_unlocked',
        'alpha_training_allowed', 'live_signal_allowed', 'main_changed',
    ]), 'retention hard boundary drift')

    comps = authority.get('authoritative_components') or {}
    g1j = comps.get('S3G1J_FINANCIAL_RAW_VALUES') or {}
    req(g1j.get('accepted_run_id') == V30_RUN and g1j.get('accepted_artifact_id') == V30_ARTIFACT_ID, 'authority raw basis pointer drift')
    req(g1j.get('document_error_count') == 1362 and g1j.get('unresolved_tie_count') == 1279 and g1j.get('raw_data_verdict') == 'FAIL_CLOSED', 'authority raw residual facts drift')
    req(
        g1j.get('residual_retention_run_id') == RET_RUN
        and g1j.get('residual_retention_artifact_id') == RET_ARTIFACT_ID
        and g1j.get('residual_retention_artifact_digest') == RET_DIGEST
        and g1j.get('residual_retention_ledger_sha256') == RET_LEDGER,
        'authority retention pointer drift',
    )
    req(g1j.get('data_verdict') == 'FAIL_CLOSED_WITH_FORMALLY_RETAINED_RESIDUALS' and g1j.get('residual_retention_gate_pass') is True and g1j.get('final_gate') is True, 'authority retention gate not closed')

    g4 = comps.get('S3G4_EARNINGS_SURPRISE') or {}
    req(g4.get('accepted_run_id') == S3G4_RUN and g4.get('acceptance_head_sha') == S3G4_HEAD, 'S3G4 accepted run/head drift')
    req(g4.get('accepted_artifact_id') == S3G4_ARTIFACT_ID and g4.get('accepted_artifact_digest') == S3G4_DIGEST, 'S3G4 artifact drift')
    req(g4.get('forecast_parse_ledger_sha256') == S3G4_FORECAST_SHA and g4.get('surprise_ledger_sha256') == S3G4_SURPRISE_SHA, 'S3G4 ledger hash drift')
    req(g4.get('forecast_population') == 51732 and g4.get('source_pdf_fetch_completeness') == 1.0, 'S3G4 source population/completeness drift')
    req(g4.get('surprise_observations') == 29139 and g4.get('actual_pit_exclusion_count') == 4, 'S3G4 result count drift')
    req(g4.get('identity_match_mode') == 'EXACT_ISSUER_ORG_ID_AND_ECONOMIC_DATE' and g4.get('expectation_is_strictly_prior') is True, 'S3G4 identity/PIT drift')
    req(g4.get('analyst_consensus_used') is False and g4.get('final_gate') is True, 'S3G4 final gate drift')

    lg = (lock.get('required_gates') or {}).get('S3G1J_FINANCIAL_RAW_VALUES') or {}
    req(lock.get('remaining_unlocked_gates') == [], 'component gate list must be empty after S3G4 acceptance')
    req(lg.get('run_id') == V30_RUN and lg.get('artifact_id') == V30_ARTIFACT_ID and lg.get('raw_data_verdict') == 'FAIL_CLOSED', 'lock raw basis drift')
    req(lg.get('residual_retention_run_id') == RET_RUN and lg.get('residual_retention_gate_pass') is True and lg.get('final_gate_pass') is True, 'lock retention gate drift')
    lock_g4 = (lock.get('required_gates') or {}).get('S3G4_EARNINGS_SURPRISE') or {}
    req(lock_g4.get('run_id') == S3G4_RUN and lock_g4.get('artifact_id') == S3G4_ARTIFACT_ID and lock_g4.get('final_gate_pass') is True, 'lock S3G4 gate drift')

    stage3 = project.get('stage3') or {}
    pg = stage3.get('s3g1j') or {}
    req(stage3.get('status') in {'NOT_READY', 'PASS_FROZEN_HISTORICAL'}, 'project Stage3 status drift')
    req(stage3.get('pending_final_gates') == [], 'project component pending gates must be empty')
    req('S3G1J_FINANCIAL_RAW_VALUES' in stage3.get('completed_final_gates_on_clean_integration', []), 'project missing completed S3G1J')
    req('S3G4_EARNINGS_SURPRISE' in stage3.get('completed_final_gates_on_clean_integration', []), 'project missing completed S3G4')
    req(pg.get('document_error_count') == 1362 and pg.get('unresolved_tie_count') == 1279 and pg.get('raw_data_verdict') == 'FAIL_CLOSED', 'project raw residual facts drift')
    req(pg.get('residual_retention_run_id') == RET_RUN and pg.get('residual_retention_gate_pass') is True and pg.get('final_gate_pass') is True, 'project retention gate drift')
    project_g4 = stage3.get('s3g4') or {}
    req(project_g4.get('accepted_run_id') == S3G4_RUN and project_g4.get('accepted_artifact_id') == S3G4_ARTIFACT_ID and project_g4.get('final_gate_pass') is True, 'project S3G4 gate drift')
    req(project.get('stage4_unlocked') is False and project.get('alpha_training_allowed') is False and project.get('live_signal_allowed') is False, 'downstream unexpectedly unlocked')
    req((project.get('freshness') or {}).get('status') == 'STALE', 'freshness must remain truthfully STALE')

    for name, path, run_id, aid, numeric, errs, ties in [
        ('V17.30', 'governance/stage3_s3g1j_v17_30_full_final.json', 31518370789, 9112098872, 1051826, 1362, 1279),
        ('V17.29', 'governance/stage3_s3g1j_v17_29_full_final.json', 31389854868, 9063271903, 1051820, 1364, 1281),
        ('V17.28', 'governance/stage3_s3g1j_v17_28_full_final.json', 30997260730, 8927455692, 1051799, 1371, 1288),
        ('V17.27', 'governance/stage3_s3g1j_v17_27_full_final.json', 30806818977, 8854139999, 1051793, 1373, 1290),
        ('V17.26', 'governance/stage3_s3g1j_v17_26_full_final.json', 30733013665, 8828600783, 1051778, 1378, 1295),
    ]:
        e = load(path)
        accepted = e.get('accepted_run') or {}
        result = e.get('full_basis_result') or {}
        req(accepted.get('run_id') == run_id and accepted.get('artifact_id') == aid, f'{name} historical authority drift')
        req(result.get('numeric_observation_count') == numeric and result.get('document_error_count') == errs and result.get('unresolved_tie_count') == ties and result.get('final_data_verdict') == 'FAIL_CLOSED', f'{name} historical result drift')

    if errors:
        for error in errors:
            print('ERROR:', error)
        return 1
    print('STAGE3_AUTHORITY_MAP_S3G4_COMPLETE_AND_HISTORY_PRESERVED_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
