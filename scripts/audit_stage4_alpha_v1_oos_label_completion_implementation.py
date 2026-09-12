#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re,subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[1]
PREFP='0e9b79a406e3a7789ade5b93878cd4276c5f424b0f0e9e4906048b9254e4cac3'
IMPLFP='a9addd6eefc82737e5a39c7828dc9b68a5d4336e2ee3e8ebeaeee1d628014045'
PRED='66a039aa76e4b1962049e3e0d41a43fb1f6c626d934a552f871f91bd27fe01da'
SRC={
 'scripts/run_stage4_alpha_v1_oos_label_completion.py':'7fe790864be6d324f4571f57ed23213920605a48d9b4415849e12c37cdb8f2d6',
 'scripts/stage4_alpha_v1_label_materialization.py':'f1cfd8d47d1df7778f5ea98211d39a36774fa270e129b86beb769afb31373557',
 'scripts/stage4_alpha_v1_alpha_evaluation.py':'4c4e7e1674ef64dd6e68fde65ba58d3954f2b4262e476863a21ac600fa8b68a3'}
BLOBS={
 'scripts/run_stage4_alpha_v1_runtime_veto_v1_1.py':'26c7371fa886cc5031dddf031c7317c4ad9bdc57',
 'scripts/audit_stage4_alpha_v1_runtime_veto_v1_1.py':'35f6b388564993241e364ea3b332a9d16eca19c5',
 'governance/stage4_alpha_v1_runtime_veto_contract_v1_1.json':'b6668800143249ccf29d15a7f5c87f1a21905b98',
 'governance/stage4_alpha_v1_oos_physical_boundary_contract.json':'6b4e85cf495ff2f43b076309b10d100b369af140'}
def load(p): return json.loads((R/p).read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256((R/p).read_bytes()).hexdigest()
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def blob(p): return subprocess.check_output(['git','hash-object',str(R/p)],text=True).strip()
def main():
 c=load('governance/stage4_alpha_v1_oos_label_completion_implementation_contract_v1.json')
 p=load('governance/stage4_alpha_v1_oos_label_completion_preregistration_v1_3_supersession.json')
 s=load('governance/accepted_project_state.json')
 e=load('governance/stage4_alpha_v1_oos_validation_consumed_incomplete_evidence.json')
 checks={}
 def ck(k,v): checks[k]=bool(v)
 ck('prereg',p['fingerprint']==PREFP and canon(p['fingerprint_basis'])==PREFP)
 ck('contract',c['fingerprint']==IMPLFP and canon(c['fingerprint_basis'])==IMPLFP)
 perm=s['permissions']
 ck('state_closed',s['schema_version']==10 and s['status']=='RESEARCH_ONLY' and s['active_business_pr'] is None and perm['oos_label_access_allowed'] is False and perm['oos_label_bearing_execution_runs_remaining']==0 and perm['model_fit_allowed'] is False and perm['lockbox_label_access_allowed'] is False and perm['live_signal_allowed'] is False and perm['main_merge_allowed'] is False and perm['authoritative_model_output_allowed'] is False)
 ck('consumed_failure',e['status']=='CONSUMED_INCOMPLETE_EXECUTION_NO_PROMOTION' and e['authorization']['consumed'] is True and e['authorization']['reusable'] is False and e['execution']['workflow_run_id']==34454575970 and e['execution']['execution_head']=='3b91203693fb1dcc4c6e649747f89b1ca7be622e' and e['execution']['rerun_allowed'] is False)
 b=c['fingerprint_basis']; pb=p['fingerprint_basis']
 ip=b['immutable_prediction_input']; ib=b['immutable_physical_boundary_input']
 ck('prediction_frozen',ip['artifact_id']==10142949262 and ip['predictions_sha256']==PRED and ip['prediction_rows']==1515811 and ip['sole_score_input'] is True)
 ck('boundary_frozen',ib['artifact_id']==10142948546 and ib['candidate_rows']==1453359 and ib['entry_lifecycle_inactive_rows']==52 and ib['exit_lifecycle_inactive_rows']==1217 and ib['active_lifecycle_integrity_failures']==0 and ib['post_oos_rows_observed']==0 and ib['broad_source_redownload_forbidden'] is True and ib['physical_boundary_rebuild_forbidden'] is True)
 ck('gate_preserved',b['preserved_gate']==pb['preserved_gate'])
 m=b['preserved_metric_semantics']; pm=pb['preserved_metric_semantics']
 ck('metrics_preserved',m['daily_ic_20d']==pm['daily_ic_20d'] and m['daily_ic_aggregate']==pm['daily_ic_aggregate'] and m['expected_quarters']==pm['expected_quarters'] and m['coverage']==pm['coverage'] and m['bucket_order']==pm['bucket_order'] and m['bucket_size']==pm['bucket_size'] and m['rebalance_sessions']==20 and m['bootstrap']['block_length_sessions']==20 and m['bootstrap']['resamples']==10000 and m['bootstrap']['seed']==20260817 and m['selected_label_censoring']==pm['selected_label_censoring'])
 fa=b['future_authorization_interface']; pfa=pb['future_authorization_constraints']
 ck('future_auth_closed',fa['separate_authorization_required'] is True and fa['max_label_completion_runs']==1 and fa['consumption_event']==pfa['future_consumption_event'] and fa['after_consumption_reexecution_forbidden'] is True and fa['prediction_computation_allowed'] is False and fa['model_load_allowed'] is False and fa['fit_retrain_tune_reselect_allowed'] is False)
 scope=b['implementation_pr_scope']
 ck('zero_access',scope['static_and_synthetic_only'] is True and all(scope[k] is False for k in ['oos_artifact_download','oos_market_value_read','oos_label_value_read','prediction_computation','model_download','model_load','fit_retraining_tuning_reselection','final_lockbox_access','live_signal','authoritative_output','main_merge']))
 ck('source_hashes',c['implementation_sources']==SRC and all(sha(k)==v for k,v in SRC.items()))
 ck('frozen_blobs',c['frozen_git_blobs']==BLOBS and b['frozen_runtime_dependencies']==BLOBS and all(blob(k)==v for k,v in BLOBS.items()))
 mat=(R/'scripts/stage4_alpha_v1_label_materialization.py').read_text(encoding='utf-8'); new='\n'.join((R/k).read_text(encoding='utf-8') for k in SRC)
 ck('parser_fix','CAST("open" AS DOUBLE) AS open_px' in mat and 'CAST("close" AS DOUBLE) AS close_px' in mat and re.search(r'CAST\(open AS DOUBLE\)|CAST\(close AS DOUBLE\)',mat) is None)
 ck('no_model_api',re.search(r'model\s*\.\s*predict\s*\(|predict_proba\s*\(|pickle\s*\.\s*load\s*\(|joblib|\.fit\s*\(|fit_predict\s*\(|partial_fit\s*\(',new) is None)
 ck('selection_guards','PREDICTION_DESC_THEN_EXCHANGE_ASC_CODE_ASC' in new and 'FAIL_CLOSED_NO_BACKFILL_NO_POST_SELECTION_DROP' in new and 'NO_PROMOTION_NO_RETUNING_ON_OOS' in new)
 w=(R/'.github/workflows/stage4-alpha-v1-oos-label-completion-implementation.yml').read_text(encoding='utf-8')
 calls=[x.strip() for x in w.splitlines() if 'python scripts/run_stage4_alpha_v1_oos_label_completion.py' in x]
 ck('workflow_synthetic_only',calls==['run: python scripts/run_stage4_alpha_v1_oos_label_completion.py --synthetic-self-test'])
 ck('workflow_no_download','download-artifact' not in w and re.search(r'\b(curl|wget|gh\s+api|urllib|requests)\b',w) is None and 'contents: read' in w and 'contents: write' not in w and 'actions: write' not in w)
 failed=[k for k,v in checks.items() if not v]
 out={'gate':'STAGE4_ALPHA_V1_OOS_LABEL_COMPLETION_IMPLEMENTATION_V1','pass':not failed,'implementation_fingerprint':IMPLFP,'checks':checks,'failed_checks':failed,'oos_artifact_download_executed':False,'oos_market_value_read':False,'oos_label_value_read':False,'prediction_computation_executed':False,'model_loaded':False,'new_authorization_created':False,'final_lockbox_accessed':False,'next_gate':c['next_gate']}
 print(json.dumps(out,indent=2)); return 0 if not failed else 2
if __name__=='__main__': raise SystemExit(main())
