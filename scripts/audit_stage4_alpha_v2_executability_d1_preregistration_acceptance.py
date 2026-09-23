#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
A_FP="6cf8b17249cff6889de8c6bff5952f5293987ed16cfc203e1cf8f55924b48dd5"
P_FP="a469999d0bcee95bcc140ebf72727e36efc449ca048d693063ecc9bfb8e87c8d"
def load(p):return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
 a=load("governance/stage4_alpha_v2_executability_d1_preregistration_acceptance.json")
 p=load("governance/stage4_alpha_v2_executability_d1_preregistration.json")
 s=load("governance/accepted_project_state.json")
 m=load("governance/project_module_index.json")
 c={}
 def ck(k,v):c[k]=bool(v)
 ck("acceptance_fp",a["fingerprint"]==A_FP and canon(a["fingerprint_basis"])==A_FP and a["status"]=="ACCEPTED_PREREGISTRATION_NO_EXECUTION_AUTHORITY")
 ck("prereg_bound",p["fingerprint"]==P_FP and a["fingerprint_basis"]["preregistration_fingerprint"]==P_FP)
 ck("ci_exact",a["fingerprint_basis"]["ci"]=={"preregistration_run_id":35838702686,"repository_safety_run_id":35838702660,"runtime_reproducibility_run_id":35838702798,"all_success":True})
 g=a["fingerprint_basis"]["authority_granted"]
 ck("zero_authority",all(g[k] is False for k in g))
 sp=s["permissions"]
 ck("state_closed",s["status"]=="RESEARCH_ONLY" and sp["model_fit_allowed"] is False and sp["model_fit_scope"]=="NONE" and sp["oos_label_access_allowed"] is False and sp["oos_label_bearing_execution_runs_remaining"]==0 and sp["lockbox_label_access_allowed"] is False and sp["live_signal_allowed"] is False and sp["main_merge_allowed"] is False and sp["authoritative_model_output_allowed"] is False)
 ck("state_progress",s["accepted_progress"]["stage4_alpha_v2_executability_d1_prereg"].startswith("MERGED_ACCEPTED_PR179") and s["business_evidence"]["stage4_alpha_v2_executability_d1_preregistration_acceptance" if False else "stage4_alpha_v2_executability_d1_prereg_acceptance"]=="governance/stage4_alpha_v2_executability_d1_preregistration_acceptance.json")
 mm=next(x for x in m["modules"] if x["id"]=="STAGE4_ALPHA_V2_EXECUTABILITY_D1")
 ck("module",m["index_version"]=="V2.5" and mm["status"]=="PREREG_ACCEPTED_IMPLEMENTATION_NOT_AUTHORIZED" and mm["preregistration_fingerprint"]==P_FP and mm["acceptance_fingerprint"]==A_FP and mm["model_fit_allowed"] is False and mm["oos_2023_2024_status"]=="QUARANTINED_NOT_FRESH_FOR_V2" and mm["final_lockbox_status"]=="SEALED_NO_ACCESS")
 failed=[k for k,v in c.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V2_EXECUTABILITY_D1_PREREG_ACCEPTANCE","pass":not failed,"acceptance_fingerprint":A_FP,"preregistration_fingerprint":P_FP,"checks":c,"failed_checks":failed,"model_fit_allowed":False,"oos_access":False,"lockbox_access":False},indent=2))
 return 0 if not failed else 2
if __name__=="__main__":raise SystemExit(main())
