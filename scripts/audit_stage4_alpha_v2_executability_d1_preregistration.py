#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
FP="a469999d0bcee95bcc140ebf72727e36efc449ca048d693063ecc9bfb8e87c8d"
V1_RESULT_FP="12ab8b1386bf6d3dfe59ab5d0e354736bfc90846f1aeb1e9f6983ab0d2c37d4b"
C007_OOF_DIGEST="sha256:3676beb6d637ca0bfa4a4676d9b83f0468ff2d30152e669fc5a8a4b20a761fd7"
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
 d=load("governance/stage4_alpha_v2_executability_d1_preregistration.json")
 v1=load("governance/stage4_alpha_v1_oos_label_completion_result_v1_2.json")
 p0=load("governance/stage4_alpha_v1_preregistration.json")
 pa=load("governance/stage4_alpha_v1_training_execution_authorization.json")
 labels=load("governance/stage4_alpha_v1_development_labels_evidence.json")
 state=load("governance/accepted_project_state.json")
 b=d["fingerprint_basis"];checks={}
 def ck(k,v):checks[k]=bool(v)
 ck("fingerprint",d["status"]=="FROZEN_DEVELOPMENT_ONLY_DIAGNOSTIC_NO_OOS_NO_LOCKBOX_NO_TRAINING" and d["fingerprint"]==FP and canon(b)==FP)
 ck("terminal_v1_bound",v1["fingerprint"]==V1_RESULT_FP and b["authority"]["v1_terminal_result_fingerprint"]==V1_RESULT_FP and v1["fingerprint_basis"]["disposition"]["alpha_gate_status"]=="FAIL")
 ck("oos_quarantined",b["authority"]["v1_oos_partition"]["v2_status"].startswith("CONTAMINATED_") and b["anti_oos_tuning"]["v1_oos_partition_raw_values_forbidden"] is True and b["future_research_boundary"]["v2_fresh_validation_must_not_use_2023_2024_as_fresh_oos"] is True)
 ck("lockbox_sealed",b["authority"]["v1_final_lockbox"]["status"]=="SEALED_NO_ACCESS_IN_D1" and b["permissions"]["final_lockbox_access_allowed"] is False)
 c7=next(x for x in pa["fingerprint_basis"]["candidate_catalog"] if x["candidate_id"]=="C007")
 ck("c007_frozen",c7["params"]==b["frozen_candidate"]["params"] and b["frozen_candidate"]["candidate_reselection_forbidden"] is True and b["frozen_candidate"]["hyperparameter_change_forbidden"] is True)
 ck("development_labels_bound",labels["workflow"]["artifact_id"]==9216418323 and labels["hashes"]["development_labels_sha256"]==b["authority"]["development_labels"]["labels_sha256"] and labels["hashes"]["split_seal_sha256"]==b["authority"]["development_labels"]["split_seal_sha256"])
 ck("coverages_pre_oos",p0["fingerprint_basis"]["abstention_and_coverage"]["operational_default_top_score_coverage"]==0.1 and p0["fingerprint_basis"]["abstention_and_coverage"]["sensitivity_coverages"]==[0.05,0.2] and b["fixed_diagnostic_coverages"]==[0.05,0.1,0.2])
 r=b["d1_replay"]
 ck("replay_narrow",r["fit_count_exact"]==5 and r["candidate_search_forbidden"] is True and r["final_development_refit_forbidden"] is True and r["test_prediction_population"].startswith("ALL_FEATURE_ROWS_") and r["prediction_must_be_frozen_before_joining_censor_fields"] is True)
 ck("no_returns_in_d1",b["required_diagnostics"]["no_economic_return_metric"] is True and b["required_diagnostics"]["no_policy_score"] is True and all(x in r["return_columns_forbidden_in_d1_outputs"] for x in ["stock_total_return_20d","benchmark_return_20d","excess_return_20d"]))
 perm=b["permissions"]; sp=state["permissions"]
 ck("no_authority_granted",perm["this_preregistration_grants_model_fit"] is False and perm["this_preregistration_grants_development_data_execution"] is False and perm["oos_access_allowed"] is False and perm["final_lockbox_access_allowed"] is False)
 ck("live_state_closed",sp["model_fit_allowed"] is False and sp["oos_label_access_allowed"] is False and sp["oos_label_bearing_execution_runs_remaining"]==0 and sp["lockbox_label_access_allowed"] is False and sp["live_signal_allowed"] is False and sp["main_merge_allowed"] is False and sp["authoritative_model_output_allowed"] is False)
 failed=[k for k,v in checks.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V2_EXECUTABILITY_D1_PREREGISTRATION","pass":not failed,"fingerprint":FP,"checks":checks,"failed_checks":failed,"model_fit_executed":False,"development_data_execution":False,"oos_accessed":False,"lockbox_accessed":False,"policy_selected":False,"next_gate":d["next_gate"]},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
