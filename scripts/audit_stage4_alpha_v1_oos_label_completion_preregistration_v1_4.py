#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
P=R/"governance/stage4_alpha_v1_oos_label_completion_preregistration_v1_4_supersession.json"
V13=R/"governance/stage4_alpha_v1_oos_label_completion_preregistration_v1_3_supersession.json"
EV1=R/"governance/stage4_alpha_v1_oos_validation_consumed_incomplete_evidence.json"
EV2=R/"governance/stage4_alpha_v1_oos_label_completion_consumed_incomplete_evidence.json"
STATE=R/"governance/accepted_project_state.json"
FP="e6f6fac81f6f1b3394b84a93bb5f41c67782b2e7dae9f6e37f7aa8eb11e29394"
V13FP="0e9b79a406e3a7789ade5b93878cd4276c5f424b0f0e9e4906048b9254e4cac3"
EV2FP="2d41c39d4400b80bdd8d3f3cd6c6e0e85838b0531878cc0e10baf25070b993b6"
def load(p): return json.loads(p.read_text(encoding="utf-8"))
def h(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
 d,v13,e1,e2,s=map(load,[P,V13,EV1,EV2,STATE]); b=d["fingerprint_basis"]; c={}
 def ck(k,v): c[k]=bool(v)
 ck("fingerprint",d["status"]=="FROZEN_SUPERSEDING_PREREGISTRATION_V1_4_NO_OOS_ACCESS_NO_NEW_AUTHORITY" and d["fingerprint"]==FP and h(b)==FP)
 ck("supersedes_v13",b["supersedes_effective_preregistration"]=={"version":"V1.3","fingerprint":V13FP} and v13["fingerprint"]==V13FP and h(v13["fingerprint_basis"])==V13FP)
 p=s["permissions"]
 ck("state_closed",s["schema_version"]==14 and s["status"]=="RESEARCH_ONLY" and p["oos_execution_pr_creation_allowed"] is False and p["oos_label_access_allowed"] is False and p["oos_label_bearing_execution_runs_remaining"]==0 and p["model_fit_allowed"] is False and p["lockbox_label_access_allowed"] is False and p["live_signal_allowed"] is False and p["main_merge_allowed"] is False and p["authoritative_model_output_allowed"] is False)
 ck("first_failure_preserved",e1["status"]=="CONSUMED_INCOMPLETE_EXECUTION_NO_PROMOTION" and e1["authorization"]["consumed"] is True and e1["authorization"]["reusable"] is False and e1["execution"]["workflow_run_id"]==34454575970)
 ck("second_failure_preserved",e2["status"]=="CONSUMED_INCOMPLETE_EXECUTION_NO_PROMOTION" and e2["fingerprint"]==EV2FP and h(e2["fingerprint_basis"])==EV2FP and e2["fingerprint_basis"]["execution"]["workflow_run_id"]==35736766602 and e2["fingerprint_basis"]["authorization_consumed"] is True and e2["fingerprint_basis"]["authorization_reusable"] is False)
 fs=b["consumed_failures_preservation"]
 ck("two_failures_exact",len(fs)==2 and fs[0]["workflow_run_id"]==34454575970 and fs[1]["workflow_run_id"]==35736766602 and all(x["failure_must_remain_recorded"] is True and x["rerun_under_consumed_authorization_forbidden"] is True for x in fs))
 for sec in ["immutable_prediction_input","immutable_physical_boundary_input","preserved_oos_partition","preserved_label_semantics","preserved_metric_semantics","preserved_gate","outcome_semantics"]:
  ck("preserved_"+sec,b[sec]==v13["fingerprint_basis"][sec])
 r=b["implementation_repair_scope"]
 ck("repair_narrow",r["allowed_repair_class"].startswith("CONSUMPTION_MARKER_SYMBOL_BINDING") and r["write_consumption_marker_must_be_executed_in_synthetic_test"] is True and r["synthetic_marker_test_must_prove_second_write_fails"] is True and all(r[k] is True for k in ["label_formula_change_forbidden","score_change_forbidden","ranking_change_forbidden","selection_rule_change_forbidden","coverage_change_forbidden","cost_model_change_forbidden","bootstrap_change_forbidden","gate_threshold_change_forbidden","runtime_veto_semantic_change_forbidden","backfill_forbidden","post_selection_drop_forbidden"]))
 f=b["future_authorization_constraints"]
 ck("zero_authority_now",f["this_preregistration_grants_oos_label_access"] is False and f["this_preregistration_grants_execution_authority"] is False and f["this_preregistration_grants_prediction_authority"] is False and f["repair_implementation_pr_must_be_static_and_synthetic_only"] is True and f["future_max_label_completion_runs"]==1 and f["future_prediction_computation_allowed"] is False and f["future_model_load_allowed"] is False and f["future_fit_retraining_tuning_reselection_allowed"] is False)
 ck("lockbox_sealed",b["hard_boundaries"]["final_lockbox_access_forbidden"] is True and b["outcome_semantics"]["final_lockbox_remains_sealed_regardless_of_completion_result_until_separate_later_authority"] is True)
 failed=[k for k,v in c.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V1_OOS_LABEL_COMPLETION_PREREGISTRATION_V1_4","pass":not failed,"fingerprint":FP,"checks":c,"failed_checks":failed,"oos_artifact_download_executed":False,"oos_market_value_read":False,"oos_label_value_read":False,"prediction_computation_executed":False,"model_loaded":False,"new_authorization_created":False,"final_lockbox_accessed":False,"next_gate":d["next_gate"]},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
