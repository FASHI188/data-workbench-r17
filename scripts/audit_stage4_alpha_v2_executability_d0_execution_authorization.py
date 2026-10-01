#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
FP="119b5fe4016c001e0fdaf4fa68b40cbf4ece92c2e37de5c4ee3d5d57ddfee27b"
P_FP="5407c8293c678287596abe2bc6cced8c83d6a2f997eb6ff8720b7790d59c8e6a"
I_FP="33e142142a2a5b3f225f2ef831186eb476eed4ceb7cecbf23159ccd22d76546f"
A_FP="9282c6e34235e93a07b8c4ee35d84dee99ae4748c2d112dd1a3690374c92402f"
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
 a=load("governance/stage4_alpha_v2_executability_d0_execution_authorization.json")
 p=load("governance/stage4_alpha_v2_executability_d0_preregistration.json")
 i=load("governance/stage4_alpha_v2_executability_d0_implementation_contract.json")
 ac=load("governance/stage4_alpha_v2_executability_d0_implementation_acceptance.json")
 s=load("governance/accepted_project_state.json")
 m=load("governance/project_module_index.json")
 b=a["fingerprint_basis"];c={}
 def ck(k,v):c[k]=bool(v)
 ck("fingerprint",a["fingerprint"]==FP and canon(b)==FP and a["status"]=="AUTHORIZED_SINGLE_USE_DEVELOPMENT_LABEL_STRUCTURE_DIAGNOSTIC")
 ck("chain",b["preregistration_fingerprint"]==p["fingerprint"]==P_FP and b["implementation_fingerprint"]==i["fingerprint"]==I_FP and b["implementation_acceptance_fingerprint"]==ac["fingerprint"]==A_FP)
 ck("exact_head",b["authorized_execution_head"]=="3155f715176505bede34a605776c97071af2198c" and b["implementation_pr"]==182)
 ck("input",b["input"]["development_labels_artifact_id"]==9216418323 and b["input"]["labels_sha256"]=="092061da5666215dcc1f4fa75ec0b1cdbcc43969560755e7cdae6de55e64d673" and b["input"]["expected_rows"]==5197648 and b["input"]["expected_valid_20d_rows"]==5103016)
 ck("single_use",b["single_use"]["max_runs"]==1 and b["single_use"]["armed_runs_remaining"]==1 and b["single_use"]["after_consumption_reexecution_forbidden"] is True)
 perm=b["permissions"]
 ck("narrow_permission",perm["development_label_structural_diagnostic_allowed"] is True and all(perm[k] is False for k in ["model_fit_allowed","prediction_allowed","feature_matrix_access_allowed","return_value_read_allowed","oos_access_allowed","final_lockbox_access_allowed","live_signal_allowed","main_merge_allowed","authoritative_output_allowed"]))
 sp=s["permissions"]
 ck("state",sp["model_fit_allowed"] is False and sp["oos_label_access_allowed"] is False and sp["oos_label_bearing_execution_runs_remaining"]==0 and sp["lockbox_label_access_allowed"] is False and sp["live_signal_allowed"] is False and sp["main_merge_allowed"] is False and sp["authoritative_model_output_allowed"] is False and sp["development_label_diagnostic_access_allowed"] is False and sp["development_label_diagnostic_runs_remaining"]==1)
 mm=next(x for x in m["modules"] if x["id"]=="STAGE4_ALPHA_V2_EXECUTABILITY_D0")
 ck("module",m["index_version"]=="V2.7" and mm["status"]=="AUTHORIZATION_ARMED_SINGLE_USE_EXECUTION_NOT_STARTED" and mm["authorization_fingerprint"]==FP and mm["authorized_execution_head"]=="3155f715176505bede34a605776c97071af2198c" and mm["armed_runs_remaining"]==1)
 failed=[k for k,v in c.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V2_EXECUTABILITY_D0_EXECUTION_AUTHORIZATION","pass":not failed,"authorization_fingerprint":FP,"armed_runs_remaining":1,"checks":c,"failed_checks":failed,"real_development_label_read":False,"model_fit":False,"prediction":False,"oos_access":False,"lockbox_access":False},indent=2))
 return 0 if not failed else 2
if __name__=="__main__":raise SystemExit(main())
