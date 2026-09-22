#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path

R=Path(__file__).resolve().parents[1]
FP="964a023e675dd04c0f8df312da373a2b5c1058512105599bf7acb2803152dd6e"
OLD_FP="4c91f96fee0970a25ecaef673419a7c5e02c02b72591e2aafeac6ee594f38558"
PREREG="0e9b79a406e3a7789ade5b93878cd4276c5f424b0f0e9e4906048b9254e4cac3"
IMPL="a9addd6eefc82737e5a39c7828dc9b68a5d4336e2ee3e8ebeaeee1d628014045"
ACCEPT="60522faad23985ffd5aa643be8af528673b6db8026874ef0565d2a8d30fcdaa3"
ORIG="d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d"
PRED="66a039aa76e4b1962049e3e0d41a43fb1f6c626d934a552f871f91bd27fe01da"
CONSUME="FIRST_SUCCESSFUL_READ_OF_ANY_OOS_MARKET_VALUE_USED_FOR_LABEL_MATERIALIZATION_OR_FIRST_SUCCESSFUL_READ_OF_ANY_OOS_LABEL_VALUE_WHICHEVER_OCCURS_FIRST"

def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def main():
    new=load("governance/stage4_alpha_v1_oos_label_completion_authorization_reservation_v1_1_supersession.json")
    old=load("governance/stage4_alpha_v1_oos_label_completion_authorization_reservation_v1.json")
    audit=load("governance/stage4_alpha_v1_oos_label_completion_authorization_reservation_v1_1_audit.json")
    state=load("governance/accepted_project_state.json")
    modules=load("governance/project_module_index.json")
    consumed=load("governance/stage4_alpha_v1_oos_validation_consumed_incomplete_evidence.json")
    b=new["fingerprint_basis"]; checks={}
    def ck(k,v): checks[k]=bool(v)
    ck("fingerprint",new["fingerprint"]==FP and canon(b)==FP)
    ck("status",new["status"]=="FROZEN_SUPERSEDING_AUTHORIZATION_RESERVATION_V1_1_UNARMED_NO_OOS_ACCESS")
    ck("supersedes_v1",old["fingerprint"]==OLD_FP and b["supersedes_reservation_fingerprint"]==OLD_FP)
    ck("authority_chain",b["preregistration_fingerprint"]==PREREG and b["implementation_fingerprint"]==IMPL and b["implementation_acceptance_fingerprint"]==ACCEPT)
    ck("consumed_history",consumed["authorization"]["fingerprint"]==ORIG and consumed["authorization"]["consumed"] is True and consumed["authorization"]["reusable"] is False and b["original_oos_authorization_fingerprint"]==ORIG and b["original_authorization_consumed"] is True and b["original_authorization_reusable"] is False)
    ck("prediction_frozen",b["prediction_artifact_id"]==10142949262 and b["predictions_sha256"]==PRED and b["prediction_rows"]==1515811)
    ck("boundary_frozen",b["physical_boundary_artifact_id"]==10142948546 and b["physical_boundary_artifact_digest"]=="sha256:76711c8bd5277bfe569868a0be7bba5dd074cac92fde88c92e4c0ce7e127a86c")
    ck("single_use",b["max_label_completion_runs"]==1 and b["consumption_event"]==CONSUME and b["after_consumption_reexecution_forbidden"] is True)
    ck("unarmed",b["authorization_armed"] is False and b["armed_runs_remaining"]==0 and b["authorized_execution_head"] is None)
    ck("zero_access",b["authorization_pr_oos_artifact_download_allowed"] is False and b["authorization_pr_oos_market_value_read_allowed"] is False and b["authorization_pr_oos_label_value_read_allowed"] is False)
    ck("model_boundaries",b["future_prediction_computation_allowed"] is False and b["model_load_allowed"] is False and b["fit_retrain_tune_reselect_allowed"] is False)
    ck("lockbox_live_main_closed",b["final_lockbox_access_allowed"] is False and b["live_signal_allowed"] is False and b["main_merge_allowed"] is False and b["authoritative_output_allowed"] is False)
    t=b["execution_transport"]
    ck("transport_exact",t["mode"]=="PRECOMPUTED_EXACT_HEAD_PUSH_AFTER_ARMING" and t["execution_branch"]=="agent/stage4-alpha-v1-oos-label-completion-execution" and t["pull_request_phase_static_only"] is True and t["pull_request_label_bearing_execution_forbidden"] is True and t["trigger_commit_must_be_created_before_arming_but_not_referenced"] is True and t["arming_authorization_must_bind_trigger_commit_sha"] is True and t["execution_branch_ref_update_to_trigger_commit_before_arming_forbidden"] is True and t["execution_branch_ref_update_to_trigger_commit_after_arming_allowed_once"] is True)
    ck("platform_reason",b["platform_constraint"]["repository_default_branch"]=="main" and b["platform_constraint"]["workflow_dispatch_requires_workflow_file_on_default_branch"] is True and b["platform_constraint"]["main_merge_allowed"] is False)
    p=state["permissions"]
    ck("state_unarmed",state["schema_version"]==13 and state["status"]=="RESEARCH_ONLY" and p["oos_execution_pr_creation_allowed"] is True and p["oos_label_access_allowed"] is False and p["oos_label_bearing_execution_runs_remaining"]==0)
    ck("state_sensitive_closed",p["model_fit_allowed"] is False and p["lockbox_label_access_allowed"] is False and p["live_signal_allowed"] is False and p["main_merge_allowed"] is False and p["authoritative_model_output_allowed"] is False)
    mod=next(x for x in modules["modules"] if x["id"]=="OOS_LABEL_COMPLETION_V1")
    ck("module_index",modules["index_version"]=="V1.10" and mod["authorization_reservation_fingerprint"]==FP and mod["status"]=="AUTHORIZATION_RESERVED_V1_1_UNARMED_NO_OOS_ACCESS" and mod["authorized_execution_head"] is None and mod["armed_runs_remaining"]==0)
    ck("audit_manifest",audit["authorization_fingerprint_expected"]==FP and audit["status"]=="PASS_FOR_GOVERNANCE_ACCEPTANCE_UNARMED_NO_OOS_ACCESS")
    failed=[k for k,v in checks.items() if not v]
    out={"gate":"STAGE4_ALPHA_V1_OOS_LABEL_COMPLETION_AUTHORIZATION_RESERVATION_V1_1","pass":not failed,"fingerprint":FP,"checks":checks,"failed_checks":failed,"oos_artifact_download_executed":False,"oos_market_value_read":False,"oos_label_value_read":False,"prediction_computation_executed":False,"model_loaded":False,"authorization_armed":False,"armed_runs_remaining":0,"final_lockbox_accessed":False,"next_gate":new["next_gate"]}
    print(json.dumps(out,indent=2))
    return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
