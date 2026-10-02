#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json
from pathlib import Path

R=Path(__file__).resolve().parents[1]
P=R/"governance/stage4_alpha_v1_oos_label_completion_preregistration_v1_3_supersession.json"
V12=R/"governance/stage4_alpha_v1_preregistration_v1_2_supersession.json"
AUTH=R/"governance/stage4_alpha_v1_oos_validation_authorization.json"
EV=R/"governance/stage4_alpha_v1_oos_validation_consumed_incomplete_evidence.json"
STATE=R/"governance/accepted_project_state.json"

FP="0e9b79a406e3a7789ade5b93878cd4276c5f424b0f0e9e4906048b9254e4cac3"
V12FP="b73f9b55efb04fac5416f6fdd39c17780b3f9e46c82d0da6b111547e3d258cf8"
AUTHFP="d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d"
EXECFP="224d9144d1989f021c29bb17ce13a6d2644b2d8992d604738b4e596a6907d177"
BOUNDARYFP="67e8555d3a9212a003a8293dc381cce0f7294917ef72875fed3218f240e0c255"
RUNTIMEFP="727e5d1496f1a79240d5c4f874e6b956a9539b80c104169268b9c80d26d45676"
MODEL="e85aabf694799a16f8c5a1dea017e3489a9025ecf3d484d7a4f3fd931b0d702c"
PRE="4b7833e4c4bdba9b956dba190f7337003ae944a624b59ddad7654b1457608330"
PRED="66a039aa76e4b1962049e3e0d41a43fb1f6c626d934a552f871f91bd27fe01da"
SECTION={
"preserved_oos_partition":"9f1bb8cc6f4f697048cad55dfa271d972de49c95b8d4098fc2c64ec063a94473",
"preserved_label_semantics":"8747889935c9e1e25393817b3758394c34f52dbd472c34be344b6edc0be4b94b",
"preserved_metric_semantics":"6ab1009e5514c651cebc56298c82f800ea8ca578d9155c78562150d0f1db7fe3",
"preserved_gate":"7c6f07acf82d798672cc4ef73f7221dfb736c1a0857ed71552cea71ed1a827fc",
"label_completion_implementation_scope":"8f20dbdcfeb8a6cc8d478faa38d4020df2b220d0ffd2660b6289d3ff7362ab5a",
"future_authorization_constraints":"48d2c3170d459bc4395677d6e0970d1370ab5d5adb62deebd969ca78d20a81be",
"hard_boundaries":"67532ead3a9edab2d94ce28e6ea783acf136c296ffd661cfa39991fd8574ef15",
"outcome_semantics":"315f7b4274aea744ab733f2ef5d8f5830223a6aa9104d5d20ecd9c17fd4fc3ff"}

def load(p): return json.loads(p.read_text(encoding="utf-8"))
def h(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def main():
 d,v12,auth,ev,state=map(load,[P,V12,AUTH,EV,STATE]); b=d["fingerprint_basis"]; c={}
 def ck(n,x): c.__setitem__(n,bool(x))
 ck("fingerprint",d["status"]=="FROZEN_SUPERSEDING_PREREGISTRATION_V1_3_NO_OOS_ACCESS_NO_NEW_AUTHORITY" and d["fingerprint"]==FP and h(b)==FP)
 ck("v12",v12["fingerprint"]==V12FP and h(v12["fingerprint_basis"])==V12FP and b["supersedes_effective_preregistration"]=={"version":"V1.2","fingerprint":V12FP})
 a=auth["fingerprint_basis"]; ac=a["access_semantics"]
 ck("old_authorization_consumed_path",auth["fingerprint"]==AUTHFP and h(a)==AUTHFP and ac["open_once"] is True and ac["max_label_bearing_execution_runs"]==1 and ac["after_consumption_reexecution_forbidden"] is True and a["failure_action"]["research_may_continue_only_via"]=="SUPERSEDING_PREREGISTRATION_WITH_OOS_CONSUMED_AND_NO_ERASURE_OF_FAILURE")
 p=state["permissions"]
 ck("state_closed",state["schema_version"]==9 and state["status"]=="RESEARCH_ONLY" and state["accepted_progress"]["oos_consumed_incomplete_acceptance_v1"]=="MERGED_ACCEPTED_PR160_NO_PROMOTION" and p["oos_execution_pr_creation_allowed"] is False and p["oos_label_access_allowed"] is False and p["oos_label_bearing_execution_runs_remaining"]==0 and p["lockbox_label_access_allowed"] is False and p["model_fit_allowed"] is False and p["live_signal_allowed"] is False and p["main_merge_allowed"] is False and p["authoritative_model_output_allowed"] is False)
 ck("evidence_consumed",ev["status"]=="CONSUMED_INCOMPLETE_EXECUTION_NO_PROMOTION" and ev["authorization"]["fingerprint"]==AUTHFP and ev["authorization"]["consumed"] is True and ev["authorization"]["reusable"] is False and ev["execution"]["workflow_run_id"]==34454575970 and ev["execution"]["execution_head"]=="3b91203693fb1dcc4c6e649747f89b1ca7be622e" and ev["execution"]["rerun_allowed"] is False and ev["failure"]["stage"]=="POST_PREDICTION_LABEL_MATERIALIZATION" and ev["failure"]["prediction_completed_before_failure"] is True and ev["failure"]["label_materialization_completed"] is False and ev["disposition"]["current_authorization_runs_remaining"]==0)
 x=b["authority"]; fi=ev["frozen_identity"]
 ck("authority",x["integration_base_sha"]=="4823ebdcc283203aee3c4b5508278b1e6d0d59ff" and x["original_oos_authorization_fingerprint"]==AUTHFP and x["historical_execution_contract_fingerprint"]==fi["execution_contract_fingerprint"]==EXECFP and x["physical_boundary_contract_fingerprint"]==fi["physical_boundary_contract_fingerprint"]==BOUNDARYFP and x["runtime_veto_v1_1_fingerprint"]==fi["runtime_veto_v1_1_fingerprint"]==RUNTIMEFP and x["candidate_id"]=="C007" and x["model_sha256"]==fi["model_sha256"]==MODEL and x["preprocess_sha256"]==fi["preprocess_sha256"]==PRE)
 f=b["consumed_failure_preservation"]
 ck("failure_preserved",f["workflow_run_id"]==34454575970 and f["execution_head"]==ev["execution"]["execution_head"] and f["original_authorization_consumed"] is True and f["original_authorization_reusable"] is False and f["failure_stage"]==ev["failure"]["stage"] and f["failure_root_cause_class"]==ev["failure"]["root_cause_class"] and f["original_failure_must_remain_recorded"] is True and f["failure_must_not_be_reclassified_as_alpha_result"] is True and f["rerun_original_run_forbidden"] is True and f["reuse_original_authorization_forbidden"] is True)
 q=b["immutable_prediction_input"]; eq=ev["partial_oos_output"]
 ck("predictions_frozen",q["artifact_id"]==eq["artifact_id"]==10142949262 and q["artifact_digest"]==eq["artifact_digest"] and q["files_exact"]==eq["files_exact"]==["authorization_consumption.json","oos_predictions.parquet"] and q["predictions_sha256"]==eq["oos_predictions_parquet_sha256"]==PRED and q["prediction_rows"]==eq["oos_predictions_rows_from_parquet_footer"]==1515811 and q["sole_score_input_for_any_future_completion"] is True and all(q[k] is True for k in ["model_artifact_download_forbidden","model_load_forbidden","prediction_recomputation_forbidden","predict_call_forbidden","predict_proba_call_forbidden","feature_retransform_forbidden","preprocessing_reexecution_forbidden","score_mutation_forbidden","ranking_mutation_forbidden","bucket_membership_mutation_forbidden"]))
 z=b["immutable_physical_boundary_input"]; ez=ev["physical_boundary"]
 ck("boundary_frozen",z["artifact_id"]==ez["artifact_id"]==10142948546 and z["artifact_digest"]==ez["artifact_digest"] and z["candidate_rows"]==ez["candidate_rows"]==1453359 and z["entry_lifecycle_inactive_rows"]==52 and z["exit_lifecycle_inactive_rows"]==1217 and z["active_lifecycle_integrity_failures"]==0 and z["post_oos_rows_observed"]==0 and z["independent_audit_pass"] is True and z["sole_oos_market_lifecycle_execution_state_source_for_future_completion"] is True and z["broad_source_redownload_forbidden"] is True and z["physical_boundary_rebuild_forbidden"] is True)
 for k,v in SECTION.items(): ck("section_"+k,h(b[k])==v)
 fa=b["future_authorization_constraints"]; hb=b["hard_boundaries"]; out=b["outcome_semantics"]
 ck("zero_authority_now",fa["this_preregistration_grants_oos_label_access"] is False and fa["this_preregistration_grants_execution_authority"] is False and fa["this_preregistration_grants_prediction_authority"] is False and fa["implementation_pr_must_be_static_and_synthetic_only"] is True and fa["separate_label_completion_authorization_required_after_implementation_acceptance"] is True and fa["future_max_label_completion_runs"]==1 and fa["future_prediction_computation_allowed"] is False)
 ck("hard_fail_closed",all(hb.values()))
 ck("no_auto_promotion",out["both_pass_does_not_auto_promote"] is True and out["separate_post_result_governance_acceptance_required"] is True and out["failure_action"]=="NO_PROMOTION_NO_RETUNING_ON_OOS" and out["final_lockbox_remains_sealed_regardless_of_completion_result_until_separate_later_authority"] is True)
 ck("next_gate",d["next_gate"]=="SEPARATE_LABEL_COMPLETION_IMPLEMENTATION_PR_STATIC_AND_SYNTHETIC_ONLY_NO_OOS_ACCESS_AFTER_V1_3_ACCEPTANCE")
 failed=[k for k,v in c.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V1_OOS_LABEL_COMPLETION_PREREGISTRATION_V1_3","pass":not failed,"fingerprint":d["fingerprint"],"checks":c,"failed_checks":failed,"oos_artifact_download_executed":False,"oos_market_value_read":False,"oos_label_value_read":False,"prediction_computation_executed":False,"model_downloaded":False,"model_loaded":False,"new_authorization_created":False,"final_lockbox_accessed":False,"next_gate":d["next_gate"]},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
