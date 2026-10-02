#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[1]
AUTH_FP="b6413b67ace2601bb03f2d45e7656ab3776ee3b9e90ecfe3ed32b92626eba16b"
RES_FP="4c91f96fee0970a25ecaef673419a7c5e02c02b72591e2aafeac6ee594f38558"
EXEC_FP="a1795f38cea7254924dd0d3ae4e905f40e7660f0c3eee5c7ad7857b5f95c760f"
EXEC_HEAD="f5eb7df2e287d1a6b922eac7d4ef60f6bb08fdc0"
CONSUMPTION="FIRST_SUCCESSFUL_READ_OF_ANY_OOS_MARKET_VALUE_USED_FOR_LABEL_MATERIALIZATION_OR_FIRST_SUCCESSFUL_READ_OF_ANY_OOS_LABEL_VALUE_WHICHEVER_OCCURS_FIRST"
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
    a=load("governance/stage4_alpha_v1_oos_label_completion_authorization_v1.json")
    au=load("governance/stage4_alpha_v1_oos_label_completion_authorization_audit_v1.json")
    r=load("governance/stage4_alpha_v1_oos_label_completion_authorization_reservation_v1.json")
    e=load("governance/stage4_alpha_v1_oos_label_completion_execution_contract_v1.json")
    s=load("governance/accepted_project_state.json")
    m=load("governance/project_module_index.json")
    b=a["fingerprint_basis"]; checks={}
    def ck(k,v): checks[k]=bool(v)
    ck("authorization_fingerprint",a["status"]=="AUTHORIZED_SINGLE_USE_OOS_LABEL_COMPLETION_V1" and a["fingerprint"]==AUTH_FP and canon(b)==AUTH_FP)
    ck("reservation_bound",r["fingerprint"]==RES_FP and b["authorization_reservation_fingerprint"]==RES_FP)
    ck("execution_contract_bound",e["fingerprint"]==EXEC_FP and b["execution_contract_fingerprint"]==EXEC_FP)
    ck("exact_execution_head",b["execution_pr"]==168 and b["authorized_execution_head"]==EXEC_HEAD and b["execution_merge_sha"]=="06c7b304bc37bbafc6dd1cc5d4ed4029e7a1f025")
    subprocess.run(["git","merge-base","--is-ancestor",EXEC_HEAD,"HEAD"],check=True)
    ck("execution_head_is_ancestor",True)
    ci=b["execution_ci"]
    ck("execution_ci_success",all(x["conclusion"]=="success" and x["head_sha"]==EXEC_HEAD for x in ci.values()))
    ck("immutable_prediction",b["prediction_artifact_id"]==10142949262 and b["predictions_sha256"]=="66a039aa76e4b1962049e3e0d41a43fb1f6c626d934a552f871f91bd27fe01da" and b["prediction_rows"]==1515811 and b["sole_score_input"] is True)
    ck("immutable_boundary",b["physical_boundary_artifact_id"]==10142948546 and b["physical_boundary_candidate_rows"]==1453359 and b["broad_source_redownload_forbidden"] is True and b["physical_boundary_rebuild_forbidden"] is True)
    ck("single_use",b["authorization_armed"] is True and b["max_label_completion_runs"]==1 and b["armed_runs_remaining"]==1 and b["consumption_event"]==CONSUMPTION and b["after_consumption_reexecution_forbidden"] is True)
    ck("forbidden_stays_forbidden",b["future_prediction_computation_allowed"] is False and b["model_load_allowed"] is False and b["fit_retrain_tune_reselect_allowed"] is False and b["final_lockbox_access_allowed"] is False and b["live_signal_allowed"] is False and b["main_merge_allowed"] is False and b["authoritative_output_allowed"] is False)
    p=s["permissions"]
    ck("state_research_only",s["schema_version"]==13 and s["status"]=="RESEARCH_ONLY")
    ck("state_armed_one_run",p["oos_execution_pr_creation_allowed"] is False and p["oos_label_access_allowed"] is False and p["oos_label_bearing_execution_runs_remaining"]==1)
    ck("state_sensitive_closed",p["model_fit_allowed"] is False and p["development_final_refit_allowed"] is False and p["lockbox_label_access_allowed"] is False and p["live_signal_allowed"] is False and p["main_merge_allowed"] is False and p["authoritative_model_output_allowed"] is False)
    mod=next(x for x in m["modules"] if x["id"]=="OOS_LABEL_COMPLETION_V1")
    ck("module_index",m["index_version"]=="V2.0" and mod["status"]=="AUTHORIZATION_ARMED_SINGLE_USE_EXECUTION_NOT_STARTED" and mod["authorization_fingerprint"]==AUTH_FP and mod["authorized_execution_head"]==EXEC_HEAD and mod["armed_runs_remaining"]==1)
    ck("audit_manifest",au["authorization_fingerprint_expected"]==AUTH_FP and au["status"]=="PASS_FOR_GOVERNANCE_ARMING_NO_OOS_ACCESS_IN_THIS_PR")
    failed=[k for k,v in checks.items() if not v]
    print(json.dumps({"gate":"STAGE4_ALPHA_V1_OOS_LABEL_COMPLETION_AUTHORIZATION_V1","pass":not failed,"authorization_fingerprint":AUTH_FP,"authorized_execution_head":EXEC_HEAD,"armed_runs_remaining":1,"oos_artifact_downloaded":False,"oos_market_value_read":False,"oos_label_value_read":False,"prediction_recomputed":False,"model_loaded":False,"final_lockbox_accessed":False,"checks":checks,"failed_checks":failed},indent=2))
    return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
