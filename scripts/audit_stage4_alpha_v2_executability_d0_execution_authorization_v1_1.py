#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[1]
FP="050b5f3d2b292e1da4c38cf60ba6b39fcbe1973ada7f3f77c055fc02f02ac920"
OLD_FP="119b5fe4016c001e0fdaf4fa68b40cbf4ece92c2e37de5c4ee3d5d57ddfee27b"
BRIDGE_FP="d76ae08d493f8a0c6746a9c90120399ccbfb16919550cfc25d3ad7f0a1c64de9"
BRIDGE_HEAD="a1bea4c3d6983761ff28fe840b28c990d97d8572"
BRIDGE_REF="agent/stage4-alpha-v2-d0-dispatch-bridge-v1"
WF=".github/workflows/stage2-baostock-all-stock-probe.yml"
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def git(*args): return subprocess.check_output(["git",*args],text=True).strip()
def main():
 a=load("governance/stage4_alpha_v2_executability_d0_execution_authorization_v1_1.json")
 old=load("governance/stage4_alpha_v2_executability_d0_execution_authorization.json")
 s=load("governance/accepted_project_state.json")
 m=load("governance/project_module_index.json")
 b=a["fingerprint_basis"];checks={}
 def ck(k,v): checks[k]=bool(v)
 ck("fingerprint",a["fingerprint"]==FP and canon(b)==FP and a["status"]=="AUTHORIZED_SINGLE_USE_D0_DIAGNOSTIC_V1_1_DISPATCH_BRIDGE")
 ck("supersedes_unconsumed_v1",old["fingerprint"]==OLD_FP and b["supersedes_authorization_fingerprint"]==OLD_FP and b["superseded_authorization_dispatch_count"]==0 and b["single_use_authority_transfer"]["additive_authority"] is False and b["single_use_authority_transfer"]["from_v1_runs_remaining"]==1 and b["single_use_authority_transfer"]["to_v1_1_runs_remaining"]==1)
 ck("bridge_binding",b["bridge"]["contract_fingerprint"]==BRIDGE_FP and b["bridge"]["review_pr"]==185 and b["bridge"]["reviewed_head"]==BRIDGE_HEAD and b["bridge"]["reviewed_branch"]==BRIDGE_REF and b["bridge"]["ci"]["all_success"] is True)
 bridge_contract=json.loads(git("show",f"{BRIDGE_HEAD}:governance/stage4_alpha_v2_d0_dispatch_bridge_contract.json"))
 ck("bridge_contract",bridge_contract["fingerprint"]==BRIDGE_FP and canon(bridge_contract["fingerprint_basis"])==BRIDGE_FP and git("rev-parse",f"{BRIDGE_HEAD}:{WF}")=="ce761c8c152a07fcd07fd39afb26224fdd9b97fe")
 ck("main_unchanged",git("rev-parse",f"origin/main:{WF}")=="b4d067aaaa995daf98b8019634c2bce50e7b8559")
 ck("workflow",b["workflow"]["dispatch_ref"]==BRIDGE_REF and b["workflow"]["exact_bridge_head_required"]==BRIDGE_HEAD and b["workflow"]["dispatch_inputs"]==[] and b["workflow"]["workflow_dispatch_only"] is True)
 ck("single_use",b["single_use"]["max_runs"]==1 and b["single_use"]["armed_runs_remaining"]==1 and b["single_use"]["after_consumption_reexecution_forbidden"] is True)
 perm=b["permissions"]
 ck("narrow_permissions",perm["development_label_structural_diagnostic_allowed"] is True and all(perm[k] is False for k in ["return_value_read_allowed","model_fit_allowed","prediction_allowed","feature_matrix_access_allowed","oos_access_allowed","final_lockbox_access_allowed","live_signal_allowed","main_merge_allowed","authoritative_output_allowed"]))
 p=s["permissions"]
 ck("state_closed",p["development_label_diagnostic_access_allowed"] is False and p["development_label_diagnostic_runs_remaining"]==1 and p["model_fit_allowed"] is False and p["oos_label_access_allowed"] is False and p["oos_label_bearing_execution_runs_remaining"]==0 and p["lockbox_label_access_allowed"] is False and p["live_signal_allowed"] is False and p["main_merge_allowed"] is False and p["authoritative_model_output_allowed"] is False)
 mm=next(x for x in m["modules"] if x["id"]=="STAGE4_ALPHA_V2_EXECUTABILITY_D0")
 ck("module",m["index_version"]=="V2.8" and mm["status"]=="AUTHORIZATION_V1_1_BRIDGE_ARMED_SINGLE_USE_EXECUTION_NOT_STARTED" and mm["authorization_fingerprint"]==FP and mm["authorized_bridge_head"]==BRIDGE_HEAD and mm["authorized_bridge_ref"]==BRIDGE_REF and mm["armed_runs_remaining"]==1)
 failed=[k for k,v in checks.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V2_D0_AUTHORIZATION_V1_1_DISPATCH_BRIDGE","pass":not failed,"authorization_fingerprint":FP,"bridge_head":BRIDGE_HEAD,"remaining_runs":1,"checks":checks,"failed_checks":failed,"old_v1_superseded":True,"main_modified":False,"oos_access":False,"lockbox_access":False},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
