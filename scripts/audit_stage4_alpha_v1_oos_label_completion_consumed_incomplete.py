#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
EVIDENCE_FP="2d41c39d4400b80bdd8d3f3cd6c6e0e85838b0531878cc0e10baf25070b993b6"
AUTH_FP="b6413b67ace2601bb03f2d45e7656ab3776ee3b9e90ecfe3ed32b92626eba16b"
RUN_ID=35736766602
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
    ev=load("governance/stage4_alpha_v1_oos_label_completion_consumed_incomplete_evidence.json")
    auth=load("governance/stage4_alpha_v1_oos_label_completion_authorization_v1.json")
    state=load("governance/accepted_project_state.json")
    modules=load("governance/project_module_index.json")
    src=(R/"scripts/stage4_alpha_v1_label_materialization.py").read_text(encoding="utf-8")
    b=ev["fingerprint_basis"]; checks={}
    def ck(k,v): checks[k]=bool(v)
    ck("evidence_fingerprint",ev["fingerprint"]==EVIDENCE_FP and canon(b)==EVIDENCE_FP)
    ck("authorization_binding",b["authorization_fingerprint"]==AUTH_FP==auth["fingerprint"])
    ck("single_use_consumed",b["authorization_consumed"] is True and b["authorization_reusable"] is False and b["authorization_runs_remaining_after_event"]==0)
    ck("run_binding",b["execution"]["workflow_run_id"]==RUN_ID and b["execution"]["run_attempt"]==1 and b["execution"]["workflow_event"]=="workflow_dispatch" and b["execution"]["rerun_allowed"] is False)
    ck("exact_head",b["execution"]["authorized_execution_head"]=="f5eb7df2e287d1a6b922eac7d4ef60f6bb08fdc0")
    probe='probe = con.execute(f\'SELECT CAST("close" AS DOUBLE) FROM read_parquet({q(str(market))}) LIMIT 1\').fetchone()'
    none='if probe is None:'
    callback='consume_callback()'
    ck("source_consumption_order",probe in src and none in src and callback in src and src.index(probe)<src.index(none)<src.index(callback))
    ck("undefined_marker_symbol","\"consumption_event\": CONSUMPTION_EVENT" in src and "CONSUMPTION_EVENT =" not in src)
    ck("failure_identity",b["failure"]["exception"]=="NameError" and b["failure"]["undefined_symbol"]=="CONSUMPTION_EVENT" and b["failure"]["marker_write_completed"] is False)
    ck("no_result_claim",b["failure"]["label_materialization_completed"] is False and b["failure"]["alpha_gate_evaluated"] is False and b["failure"]["runtime_veto_evaluated"] is False)
    ck("immutable_inputs",b["immutable_inputs"]["prediction_artifact_id"]==10142949262 and b["immutable_inputs"]["physical_boundary_artifact_id"]==10142948546 and b["immutable_inputs"]["prediction_recomputed"] is False)
    ck("run_artifact",b["run_output_evidence"]["result_artifact_id"]==10697048461 and b["run_output_evidence"]["artifact_digest"]=="sha256:e32cbde7269803f11697a0364ca546ec883979f24ca6ed29877aff7aac53578b")
    p=state["permissions"]
    ck("state_closed",state["schema_version"]==14 and state["status"]=="RESEARCH_ONLY" and p["oos_label_access_allowed"] is False and p["oos_label_bearing_execution_runs_remaining"]==0)
    ck("sensitive_permissions_closed",p["model_fit_allowed"] is False and p["lockbox_label_access_allowed"] is False and p["live_signal_allowed"] is False and p["main_merge_allowed"] is False and p["authoritative_model_output_allowed"] is False)
    mod=next(x for x in modules["modules"] if x["id"]=="OOS_LABEL_COMPLETION_V1")
    ck("module_closed",modules["index_version"]=="V2.1" and mod["status"]=="CONSUMED_INCOMPLETE_NO_PROMOTION" and mod["consuming_run_id"]==RUN_ID and mod["armed_runs_remaining"]==0 and mod["reusable"] is False)
    failed=[k for k,v in checks.items() if not v]
    print(json.dumps({"gate":"STAGE4_ALPHA_V1_OOS_LABEL_COMPLETION_CONSUMED_INCOMPLETE_ACCEPTANCE","pass":not failed,"evidence_fingerprint":EVIDENCE_FP,"workflow_run_id":RUN_ID,"authorization_status":"CONSUMED_NON_REUSABLE","remaining_runs":0,"alpha_gate":"NOT_EVALUATED","runtime_veto":"NOT_EVALUATED","promotion":"NO_PROMOTION_NOT_ESTABLISHED_FAIL_CLOSED","checks":checks,"failed_checks":failed},indent=2))
    return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
