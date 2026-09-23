#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[1]
FP="f038c7857da733207be7cb9c3df76bd0e189054b6763b3d3c70aca017afda889"
PRE="e6f6fac81f6f1b3394b84a93bb5f41c67782b2e7dae9f6e37f7aa8eb11e29394"
REPAIR="45d25e1627b3c1b8d95371fd49997dc8c818e086915f85850274986d1a08adfd"
ACCEPT="1b6e05dd16911f9234c1ed4ee19918d30c37943dbb4be6b6490adb24b099849b"
EVENT="FIRST_SUCCESSFUL_READ_OF_ANY_OOS_MARKET_VALUE_USED_FOR_LABEL_MATERIALIZATION_OR_FIRST_SUCCESSFUL_READ_OF_ANY_OOS_LABEL_VALUE_WHICHEVER_OCCURS_FIRST"
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def sha(p): return hashlib.sha256((R/p).read_bytes()).hexdigest()
def blob(p): return subprocess.check_output(["git","hash-object",str(R/p)],text=True).strip()
def main():
 a=load("governance/stage4_alpha_v1_oos_label_completion_authorization_reservation_v1_2.json")
 au=load("governance/stage4_alpha_v1_oos_label_completion_authorization_reservation_audit_v1_2.json")
 p=load("governance/stage4_alpha_v1_oos_label_completion_preregistration_v1_4_supersession.json")
 r=load("governance/stage4_alpha_v1_oos_label_completion_implementation_repair_v1_1.json")
 ac=load("governance/stage4_alpha_v1_oos_label_completion_implementation_repair_acceptance_v1_1.json")
 e1=load("governance/stage4_alpha_v1_oos_validation_consumed_incomplete_evidence.json")
 e2=load("governance/stage4_alpha_v1_oos_label_completion_consumed_incomplete_evidence.json")
 s=load("governance/accepted_project_state.json"); m=load("governance/project_module_index.json")
 b=a["fingerprint_basis"]; checks={}
 def ck(k,v): checks[k]=bool(v)
 ck("reservation_fp",a["fingerprint"]==FP and canon(b)==FP and a["status"]=="FROZEN_SINGLE_USE_OOS_LABEL_COMPLETION_AUTHORIZATION_RESERVATION_V1_2_UNARMED_NO_OOS_ACCESS")
 ck("v14",p["fingerprint"]==PRE and b["preregistration_v1_4_fingerprint"]==PRE)
 ck("repair",r["fingerprint"]==REPAIR and b["repair_implementation_fingerprint"]==REPAIR)
 ck("acceptance",ac["fingerprint"]==ACCEPT and b["repair_implementation_acceptance_fingerprint"]==ACCEPT)
 ck("pr167_rejected",b["stale_unmerged_transport_pr"]["pr"]==167 and b["stale_unmerged_transport_pr"]["state"]=="CLOSED_SUPERSEDED_NOT_AUTHORITY")
 ck("consumed_history",e1["execution"]["workflow_run_id"]==34454575970 and e1["authorization"]["consumed"] is True and e2["fingerprint_basis"]["execution"]["workflow_run_id"]==35736766602 and e2["fingerprint_basis"]["authorization_consumed"] is True and all(x["consumed"] is True and x["reusable"] is False for x in b["consumed_authorizations"]))
 ck("inputs",b["prediction_artifact_id"]==10142949262 and b["predictions_sha256"]=="66a039aa76e4b1962049e3e0d41a43fb1f6c626d934a552f871f91bd27fe01da" and b["prediction_rows"]==1515811 and b["physical_boundary_artifact_id"]==10142948546)
 ck("sources",all(sha(k)==v for k,v in b["implementation_sources"].items()))
 ck("runtime_blobs",all(blob(k)==v for k,v in b["frozen_runtime_dependencies"].items()))
 ck("unarmed",b["authorized_execution_head"] is None and b["authorization_armed"] is False and b["armed_runs_remaining"]==0 and b["max_label_completion_runs"]==1)
 ck("consumption",b["consumption_event"]==EVENT and b["after_consumption_reexecution_forbidden"] is True)
 ck("no_access",b["reservation_pr_oos_artifact_download_allowed"] is False and b["reservation_pr_oos_market_value_read_allowed"] is False and b["reservation_pr_oos_label_value_read_allowed"] is False and b["reservation_pr_prediction_computation_allowed"] is False and b["reservation_pr_model_load_allowed"] is False)
 perm=s["permissions"]
 ck("state",s["schema_version"]==14 and s["status"]=="RESEARCH_ONLY" and perm["oos_execution_pr_creation_allowed"] is True and perm["oos_label_access_allowed"] is False and perm["oos_label_bearing_execution_runs_remaining"]==0 and perm["model_fit_allowed"] is False and perm["lockbox_label_access_allowed"] is False and perm["live_signal_allowed"] is False and perm["main_merge_allowed"] is False and perm["authoritative_model_output_allowed"] is False)
 mod=next(x for x in m["modules"] if x["id"]=="OOS_LABEL_COMPLETION_V1")
 ck("module",m["index_version"]=="V2.2" and mod["status"]=="REPAIR_ACCEPTED_AUTHORIZATION_RESERVED_V1_2_UNARMED_NO_OOS_ACCESS" and mod["authorization_reservation_fingerprint"]==FP and mod["authorized_execution_head"] is None and mod["armed_runs_remaining"]==0)
 ck("audit_manifest",au["authorization_fingerprint_expected"]==FP and au["status"]=="PASS_FOR_GOVERNANCE_ACCEPTANCE_UNARMED_NO_OOS_ACCESS")
 failed=[k for k,v in checks.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V1_OOS_LABEL_COMPLETION_AUTHORIZATION_RESERVATION_V1_2","pass":not failed,"reservation_fingerprint":FP,"checks":checks,"failed_checks":failed,"oos_artifact_downloaded":False,"oos_market_value_read":False,"oos_label_value_read":False,"authorization_armed":False,"armed_runs_remaining":0,"final_lockbox_accessed":False},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
