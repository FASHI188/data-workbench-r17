#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re,tempfile
from pathlib import Path
import sys
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/"scripts"))
from stage4_alpha_v1_label_materialization import PREREG_FP,IMPLEMENTATION_FP,CONSUMPTION_EVENT,write_consumption_marker
FP="45d25e1627b3c1b8d95371fd49997dc8c818e086915f85850274986d1a08adfd"
PRE="e6f6fac81f6f1b3394b84a93bb5f41c67782b2e7dae9f6e37f7aa8eb11e29394"
OLD="a9addd6eefc82737e5a39c7828dc9b68a5d4336e2ee3e8ebeaeee1d628014045"
EVENT="FIRST_SUCCESSFUL_READ_OF_ANY_OOS_MARKET_VALUE_USED_FOR_LABEL_MATERIALIZATION_OR_FIRST_SUCCESSFUL_READ_OF_ANY_OOS_LABEL_VALUE_WHICHEVER_OCCURS_FIRST"
LAB_SHA="07481bb2c20837b945b8a6deba06b76459c363d0c91e054b8a1029476881c18a"
RUN_SHA="7fe790864be6d324f4571f57ed23213920605a48d9b4415849e12c37cdb8f2d6"
ALPHA_SHA="4c4e7e1674ef64dd6e68fde65ba58d3954f2b4262e476863a21ac600fa8b68a3"
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def sha(p): return hashlib.sha256((R/p).read_bytes()).hexdigest()
def main():
 c=load("governance/stage4_alpha_v1_oos_label_completion_implementation_repair_v1_1.json")
 p=load("governance/stage4_alpha_v1_oos_label_completion_preregistration_v1_4_supersession.json")
 s=load("governance/accepted_project_state.json")
 e1=load("governance/stage4_alpha_v1_oos_validation_consumed_incomplete_evidence.json")
 e2=load("governance/stage4_alpha_v1_oos_label_completion_consumed_incomplete_evidence.json")
 old=load("governance/stage4_alpha_v1_oos_label_completion_implementation_contract_v1.json")
 checks={}
 def ck(k,v): checks[k]=bool(v)
 ck("contract",c["fingerprint"]==FP and canon(c["fingerprint_basis"])==FP)
 ck("v14",p["fingerprint"]==PRE and canon(p["fingerprint_basis"])==PRE and s["accepted_progress"]["oos_label_completion_prereg_v1_4"]=="MERGED_ACCEPTED_PR171_FP_E6F6FAC8_NO_NEW_AUTHORITY")
 perm=s["permissions"]; ck("state_closed",s["status"]=="RESEARCH_ONLY" and perm["oos_label_access_allowed"] is False and perm["oos_label_bearing_execution_runs_remaining"]==0 and perm["model_fit_allowed"] is False and perm["lockbox_label_access_allowed"] is False)
 ck("both_failures",e1["authorization"]["consumed"] is True and e1["authorization"]["reusable"] is False and e1["execution"]["workflow_run_id"]==34454575970 and e2["fingerprint"]=="2d41c39d4400b80bdd8d3f3cd6c6e0e85838b0531878cc0e10baf25070b993b6" and e2["fingerprint_basis"]["authorization_consumed"] is True and e2["fingerprint_basis"]["authorization_reusable"] is False and e2["fingerprint_basis"]["execution"]["workflow_run_id"]==35736766602)
 ck("supersedes_old_impl",c["fingerprint_basis"]["supersedes_implementation_fingerprint"]==OLD and old["fingerprint"]==OLD)
 ck("identity_binding",PREREG_FP==PRE and IMPLEMENTATION_FP==FP and CONSUMPTION_EVENT==EVENT)
 ck("source_hashes",c["implementation_sources"]=={"scripts/run_stage4_alpha_v1_oos_label_completion.py":RUN_SHA,"scripts/stage4_alpha_v1_label_materialization.py":LAB_SHA,"scripts/stage4_alpha_v1_alpha_evaluation.py":ALPHA_SHA} and sha("scripts/run_stage4_alpha_v1_oos_label_completion.py")==RUN_SHA and sha("scripts/stage4_alpha_v1_label_materialization.py")==LAB_SHA and sha("scripts/stage4_alpha_v1_alpha_evaluation.py")==ALPHA_SHA)
 src=(R/"scripts/stage4_alpha_v1_label_materialization.py").read_text()
 ck("parser_fix",'CAST("open" AS DOUBLE) AS open_px' in src and 'CAST("close" AS DOUBLE) AS close_px' in src and re.search(r"CAST\(open AS DOUBLE\)|CAST\(close AS DOUBLE\)",src) is None)
 with tempfile.TemporaryDirectory(prefix="marker-synth-") as td:
  out=Path(td); auth={"fingerprint":"synthetic-auth-fingerprint"}; head="a"*40
  marker=write_consumption_marker(out,auth,head)
  payload=json.loads(marker.read_text())
  ck("marker_status",payload["status"]=="CONSUMED")
  ck("marker_auth",payload["authorization_fingerprint"]==auth["fingerprint"])
  ck("marker_head",payload["execution_head"]==head)
  ck("marker_event",payload["consumption_event"]==EVENT)
  ck("marker_identity",payload["preregistration_fingerprint"]==PRE and payload["implementation_fingerprint"]==FP)
  ck("marker_no_prediction_model",payload["prediction_computation_executed"] is False and payload["model_loaded"] is False and payload["fit_executed"] is False and payload["final_lockbox_accessed"] is False)
  failed_second=False
  try: write_consumption_marker(out,auth,head)
  except ValueError: failed_second=True
  ck("second_write_fail_closed",failed_second)
 r=c["fingerprint_basis"]["repair"]
 ck("repair_narrow",r["label_formula_change"] is False and r["score_change"] is False and r["ranking_change"] is False and r["selection_rule_change"] is False and r["coverage_change"] is False and r["cost_model_change"] is False and r["bootstrap_change"] is False and r["gate_threshold_change"] is False and r["runtime_veto_semantic_change"] is False and r["backfill"] is False and r["post_selection_drop"] is False)
 scope=c["fingerprint_basis"]["implementation_pr_scope"]
 ck("zero_oos_access",all(scope[k] is False for k in ["oos_artifact_download","oos_market_value_read","oos_label_value_read","prediction_computation","model_download","model_load","fit_retraining_tuning_reselection","final_lockbox_access","live_signal","authoritative_output","main_merge"]))
 failed=[k for k,v in checks.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V1_OOS_LABEL_COMPLETION_IMPLEMENTATION_REPAIR_V1_1","pass":not failed,"implementation_fingerprint":FP,"checks":checks,"failed_checks":failed,"production_marker_synthetic_test":checks.get("marker_status",False) and checks.get("second_write_fail_closed",False),"oos_artifact_download_executed":False,"oos_market_value_read":False,"oos_label_value_read":False,"prediction_computation_executed":False,"model_loaded":False,"final_lockbox_accessed":False,"next_gate":c["next_gate"]},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
