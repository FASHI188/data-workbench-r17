#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
FP="12ab8b1386bf6d3dfe59ab5d0e354736bfc90846f1aeb1e9f6983ab0d2c37d4b"
AUTH_FP="0a7c2e5ed7777bc84ad4db22b91c5e84da5dc819a186d743d19bb603b158f10a"
RUN_ID=35819638146
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
 e=load("governance/stage4_alpha_v1_oos_label_completion_result_v1_2.json"); a=load("governance/stage4_alpha_v1_oos_label_completion_authorization_v1_2.json")
 s=load("governance/accepted_project_state.json"); m=load("governance/project_module_index.json")
 b=e["fingerprint_basis"]; checks={}
 def ck(k,v): checks[k]=bool(v)
 ck("fingerprint",e["fingerprint"]==FP and canon(b)==FP)
 ck("run_binding",b["workflow_run_id"]==RUN_ID and b["workflow_run_attempt"]==1 and b["workflow_event"]=="workflow_dispatch" and b["execution_head"]=="303dcc9bbfbef5dcbbf1027ebc8aff442f14fc18")
 ck("authorization_consumed",b["authorization"]["fingerprint"]==AUTH_FP==a["fingerprint"] and b["authorization"]["consumed"] is True and b["authorization"]["reusable"] is False and b["authorization"]["runs_remaining_after_event"]==0 and b["authorization"]["marker_persisted"] is True)
 ck("immutable_inputs",b["immutable_inputs"]["prediction_artifact_id"]==10142949262 and b["immutable_inputs"]["predictions_sha256"]=="66a039aa76e4b1962049e3e0d41a43fb1f6c626d934a552f871f91bd27fe01da" and b["immutable_inputs"]["physical_boundary_artifact_id"]==10142948546 and b["immutable_inputs"]["prediction_recomputed"] is False and b["immutable_inputs"]["model_loaded"] is False)
 al=b["alpha"]
 ck("alpha_fail",al["evaluated"] is True and al["status"]=="FAIL" and al["gate_logic"]=="ALL_REQUIRED_MUST_PASS" and al["mean_daily_ic_20d"]>0 and al["bootstrap_95pct_ci_lower"]>0 and al["positive_quarters"]==8 and al["checks"]["top_10pct_net_excess_return_20d_at_15bps_per_side_gt_0"] is False and al["checks"]["no_sign_inversion_5pct_or_20pct_coverage"] is False)
 ck("coverage_fail_closed",all(al["coverage_fail_closed"][k]["coverage_valid"] is False for k in ["05pct","10pct","20pct"]))
 rv=b["runtime_veto"];src=(R/"scripts/run_stage4_alpha_v1_runtime_veto_v1_1.py").read_text(encoding="utf-8")
 ck("runtime_incomplete",rv["evaluated"] is False and rv["status"]=="NOT_EVALUATED_EXECUTION_INCOMPLETE" and rv["exception"]=="duckdb.duckdb.ParserException" and "::BIGINT rows" in src)
 d=b["disposition"]
 ck("terminal_no_promotion",d["alpha_gate_status"]=="FAIL" and d["combined_promotion_status"]=="NO_PROMOTION_ALPHA_FAIL_FAIL_CLOSED" and d["current_authorization_runs_remaining"]==0 and d["reexecution_under_current_authorization"]=="FORBIDDEN" and d["retuning_on_oos_forbidden"] is True and d["final_lockbox_open_allowed"] is False)
 p=s["permissions"]
 ck("state_closed",s["status"]=="RESEARCH_ONLY" and p["oos_execution_pr_creation_allowed"] is False and p["oos_label_access_allowed"] is False and p["oos_label_bearing_execution_runs_remaining"]==0 and p["model_fit_allowed"] is False and p["lockbox_label_access_allowed"] is False and p["live_signal_allowed"] is False and p["main_merge_allowed"] is False and p["authoritative_model_output_allowed"] is False)
 mod=next(x for x in m["modules"] if x["id"]=="OOS_LABEL_COMPLETION_V1")
 ck("module_closed",m["schema_version"]==1 and m["index_version"]=="V2.4" and mod["status"]=="ALPHA_FAIL_NO_PROMOTION_RUNTIME_VETO_INCOMPLETE_AUTH_CONSUMED" and mod["result_evidence_fingerprint"]==FP and mod["consuming_run_id"]==RUN_ID and mod["armed_runs_remaining"]==0 and mod["alpha_gate_status"]=="FAIL")
 lock=next(x for x in m["modules"] if x["id"]=="FINAL_LOCKBOX_V1")
 ck("lockbox_sealed",lock["status"]=="SEALED")
 failed=[k for k,v in checks.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V1_OOS_LABEL_COMPLETION_RESULT_V1_2","pass":not failed,"result_fingerprint":FP,"run_id":RUN_ID,"alpha_gate":"FAIL","runtime_veto":"NOT_EVALUATED_EXECUTION_INCOMPLETE","promotion":"NO_PROMOTION_ALPHA_FAIL_FAIL_CLOSED","authorization":"CONSUMED_NON_REUSABLE","remaining_runs":0,"checks":checks,"failed_checks":failed},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
