#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[1]
AUTH_FP="0a7c2e5ed7777bc84ad4db22b91c5e84da5dc819a186d743d19bb603b158f10a"
RES_FP="f038c7857da733207be7cb9c3df76bd0e189054b6763b3d3c70aca017afda889"
EXEC_FP="1ca647475bf57ca544b68aa535456fecb0469fcd8a999a58a3288f699f8cc469"
EXEC_HEAD="303dcc9bbfbef5dcbbf1027ebc8aff442f14fc18"
CONSUMPTION="FIRST_SUCCESSFUL_READ_OF_ANY_OOS_MARKET_VALUE_USED_FOR_LABEL_MATERIALIZATION_OR_FIRST_SUCCESSFUL_READ_OF_ANY_OOS_LABEL_VALUE_WHICHEVER_OCCURS_FIRST"
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
 a=load("governance/stage4_alpha_v1_oos_label_completion_authorization_v1_2.json")
 au=load("governance/stage4_alpha_v1_oos_label_completion_authorization_audit_v1_2.json")
 r=load("governance/stage4_alpha_v1_oos_label_completion_authorization_reservation_v1_2.json")
 e=load("governance/stage4_alpha_v1_oos_label_completion_execution_contract_v1_2.json")
 s=load("governance/accepted_project_state.json");m=load("governance/project_module_index.json")
 ev=load("governance/stage4_alpha_v1_oos_label_completion_consumed_incomplete_evidence.json")
 b=a["fingerprint_basis"];checks={}
 def ck(k,v): checks[k]=bool(v)
 ck("authorization_fingerprint",a["status"]=="AUTHORIZED_SINGLE_USE_OOS_LABEL_COMPLETION_V1" and a["fingerprint"]==AUTH_FP and canon(b)==AUTH_FP)
 ck("reservation_bound",r["fingerprint"]==RES_FP and b["authorization_reservation_fingerprint"]==RES_FP and r["fingerprint_basis"]["authorization_armed"] is False)
 ck("execution_contract_bound",e["fingerprint"]==EXEC_FP and canon(e["fingerprint_basis"])==EXEC_FP and b["execution_contract_fingerprint"]==EXEC_FP)
 ck("exact_execution_head",b["execution_pr"]==176 and b["authorized_execution_head"]==EXEC_HEAD and b["execution_merge_sha"]=="b068aed179bf47994296db963d9ee5d7f2787c1c")
 subprocess.run(["git","merge-base","--is-ancestor",EXEC_HEAD,"HEAD"],check=True);ck("execution_head_is_ancestor",True)
 ci=b["execution_ci"];ck("execution_ci_success",ci=={"carrier_run_id":35814481911,"repository_safety_run_id":35814481945,"runtime_reproducibility_run_id":35814481785,"all_success":True})
 ck("prior_consumed_preserved",b["original_oos_authorization_fingerprint"]=="d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d" and b["prior_label_completion_authorization_fingerprint"]=="b6413b67ace2601bb03f2d45e7656ab3776ee3b9e90ecfe3ed32b92626eba16b" and b["prior_label_completion_consumed_evidence_fingerprint"]==ev["fingerprint"]=="2d41c39d4400b80bdd8d3f3cd6c6e0e85838b0531878cc0e10baf25070b993b6")
 ck("immutable_inputs",b["prediction_artifact_id"]==10142949262 and b["predictions_sha256"]=="66a039aa76e4b1962049e3e0d41a43fb1f6c626d934a552f871f91bd27fe01da" and b["physical_boundary_artifact_id"]==10142948546)
 ck("single_use",b["authorization_armed"] is True and b["max_label_completion_runs"]==1 and b["armed_runs_remaining"]==1 and b["consumption_event"]==CONSUMPTION and b["after_consumption_reexecution_forbidden"] is True)
 ck("forbidden_closed",b["future_prediction_computation_allowed"] is False and b["model_load_allowed"] is False and b["fit_retrain_tune_reselect_allowed"] is False and b["final_lockbox_access_allowed"] is False and b["live_signal_allowed"] is False and b["main_merge_allowed"] is False and b["authoritative_output_allowed"] is False)
 p=s["permissions"];ck("state",s["schema_version"]==14 and s["status"]=="RESEARCH_ONLY" and p["oos_execution_pr_creation_allowed"] is False and p["oos_label_access_allowed"] is False and p["oos_label_bearing_execution_runs_remaining"]==1)
 ck("state_sensitive_closed",p["model_fit_allowed"] is False and p["lockbox_label_access_allowed"] is False and p["live_signal_allowed"] is False and p["main_merge_allowed"] is False and p["authoritative_model_output_allowed"] is False)
 mod=next(x for x in m["modules"] if x["id"]=="OOS_LABEL_COMPLETION_V1")
 ck("module",m["index_version"]=="V2.3" and mod["status"]=="AUTHORIZATION_ARMED_V1_2_SINGLE_USE_EXECUTION_NOT_STARTED" and mod["authorization_fingerprint"]==AUTH_FP and mod["authorized_execution_head"]==EXEC_HEAD and mod["armed_runs_remaining"]==1)
 ck("audit_manifest",au["authorization_fingerprint_expected"]==AUTH_FP and au["status"]=="PASS_FOR_GOVERNANCE_ARMING_V1_2_NO_OOS_ACCESS_IN_THIS_PR")
 failed=[k for k,v in checks.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V1_OOS_LABEL_COMPLETION_AUTHORIZATION_V1_2","pass":not failed,"authorization_fingerprint":AUTH_FP,"authorized_execution_head":EXEC_HEAD,"armed_runs_remaining":1,"oos_artifact_downloaded":False,"oos_market_value_read":False,"oos_label_value_read":False,"prediction_recomputed":False,"model_loaded":False,"final_lockbox_accessed":False,"checks":checks,"failed_checks":failed},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
