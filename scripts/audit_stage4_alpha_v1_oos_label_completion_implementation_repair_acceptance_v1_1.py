#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
FP="1b6e05dd16911f9234c1ed4ee19918d30c37943dbb4be6b6490adb24b099849b"
REPAIR="45d25e1627b3c1b8d95371fd49997dc8c818e086915f85850274986d1a08adfd"
PRE="e6f6fac81f6f1b3394b84a93bb5f41c67782b2e7dae9f6e37f7aa8eb11e29394"
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def sha(p): return hashlib.sha256((R/p).read_bytes()).hexdigest()
def main():
 a=load("governance/stage4_alpha_v1_oos_label_completion_implementation_repair_acceptance_v1_1.json")
 c=load("governance/stage4_alpha_v1_oos_label_completion_implementation_repair_v1_1.json")
 p=load("governance/stage4_alpha_v1_oos_label_completion_preregistration_v1_4_supersession.json")
 s=load("governance/accepted_project_state.json")
 e1=load("governance/stage4_alpha_v1_oos_validation_consumed_incomplete_evidence.json")
 e2=load("governance/stage4_alpha_v1_oos_label_completion_consumed_incomplete_evidence.json")
 b=a["fingerprint_basis"]; checks={}
 def ck(k,v): checks[k]=bool(v)
 ck("acceptance_fp",a["fingerprint"]==FP and canon(b)==FP)
 ck("repair_contract",c["fingerprint"]==REPAIR and canon(c["fingerprint_basis"])==REPAIR)
 ck("prereg",p["fingerprint"]==PRE and canon(p["fingerprint_basis"])==PRE)
 ck("pr173_binding",b["implementation_pr"]==173 and b["accepted_implementation_head"]=="1c34c514a5ed33180e3d376f4988de49ffc73198" and b["implementation_merge_sha"]=="446f51b9c5f8199b9289c3cbd850d7bc146cd297")
 ck("ci_all_success",all(x["conclusion"]=="success" for x in b["ci"].values()) and {x["run_id"] for x in b["ci"].values()}=={35741070630,35741070764,35741070408,35741070445})
 ck("marker_tests",b["production_marker_synthetic_test_pass"] is True and b["unchanged_end_to_end_synthetic_completion_pass"] is True)
 ck("sources",all(sha(k)==v for k,v in b["source_sha256"].items()))
 ck("consumed_history",e1["execution"]["workflow_run_id"]==34454575970 and e1["authorization"]["consumed"] is True and e2["fingerprint_basis"]["execution"]["workflow_run_id"]==35736766602 and e2["fingerprint_basis"]["authorization_consumed"] is True)
 perm=s["permissions"]
 ck("state_closed",s["accepted_progress"]["oos_label_completion_implementation_repair_v1_1"].startswith("MERGED_ACCEPTED_PR173_FP_") and perm["oos_execution_pr_creation_allowed"] is False and perm["oos_label_access_allowed"] is False and perm["oos_label_bearing_execution_runs_remaining"]==0 and perm["model_fit_allowed"] is False and perm["lockbox_label_access_allowed"] is False and perm["live_signal_allowed"] is False and perm["main_merge_allowed"] is False and perm["authoritative_model_output_allowed"] is False)
 ck("no_new_authority",b["acceptance_grants_oos_access"] is False and b["acceptance_grants_execution_authority"] is False and b["prediction_recomputation_allowed"] is False and b["model_load_allowed"] is False and b["fit_retrain_tune_reselect_allowed"] is False and b["final_lockbox_access_allowed"] is False)
 failed=[k for k,v in checks.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V1_OOS_LABEL_COMPLETION_REPAIR_ACCEPTANCE_V1_1","pass":not failed,"acceptance_fingerprint":FP,"checks":checks,"failed_checks":failed,"remaining_runs":0,"oos_access":False,"next_gate":b["next_gate"]},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
