#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
A_FP="9282c6e34235e93a07b8c4ee35d84dee99ae4748c2d112dd1a3690374c92402f"
P_FP="5407c8293c678287596abe2bc6cced8c83d6a2f997eb6ff8720b7790d59c8e6a"
I_FP="33e142142a2a5b3f225f2ef831186eb476eed4ceb7cecbf23159ccd22d76546f"
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
 a=load("governance/stage4_alpha_v2_executability_d0_implementation_acceptance.json")
 p=load("governance/stage4_alpha_v2_executability_d0_preregistration.json")
 i=load("governance/stage4_alpha_v2_executability_d0_implementation_contract.json")
 s=load("governance/accepted_project_state.json")
 m=load("governance/project_module_index.json")
 src=(R/"scripts/run_stage4_alpha_v2_executability_d0.py").read_text(encoding="utf-8")
 c={}
 def ck(k,v): c[k]=bool(v)
 ck("acceptance_fp",a["fingerprint"]==A_FP and canon(a["fingerprint_basis"])==A_FP and a["status"]=="ACCEPTED_STATIC_SYNTHETIC_IMPLEMENTATION_NO_EXECUTION_AUTHORITY")
 ck("prereg_bound",p["fingerprint"]==P_FP and a["fingerprint_basis"]["preregistration_fingerprint"]==P_FP)
 ck("implementation_bound",i["fingerprint"]==I_FP and a["fingerprint_basis"]["implementation_fingerprint"]==I_FP)
 ck("exact_head",a["fingerprint_basis"]["implementation_pr"]==182 and a["fingerprint_basis"]["implementation_head"]=="3155f715176505bede34a605776c97071af2198c" and a["fingerprint_basis"]["implementation_merge_sha"]=="c4c9bab1591dd8c26cbe4efce5071d52a0bca318")
 ck("ci_exact",a["fingerprint_basis"]["ci"]=={"implementation_run_id":36809655020,"repository_safety_run_id":36809655014,"runtime_reproducibility_run_id":36809654987,"all_success":True})
 ck("zero_authority",all(v is False for v in a["fingerprint_basis"]["authority_granted"].values()))
 fit_token="."+"fit("; predict_token="."+"predict("
 ck("no_model_or_prediction_path",fit_token not in src and predict_token not in src and "sklearn" not in src)
 sp=s["permissions"]
 ck("state_closed",s["status"]=="RESEARCH_ONLY" and sp["model_fit_allowed"] is False and sp["model_fit_scope"]=="NONE" and sp["oos_label_access_allowed"] is False and sp["oos_label_bearing_execution_runs_remaining"]==0 and sp["lockbox_label_access_allowed"] is False and sp["live_signal_allowed"] is False and sp["main_merge_allowed"] is False and sp["authoritative_model_output_allowed"] is False)
 ck("state_progress",s["accepted_progress"]["stage4_alpha_v2_executability_d0_implementation"].startswith("MERGED_ACCEPTED_PR182") and s["accepted_progress"]["stage4_alpha_v2_executability_d0_implementation_acceptance"]=="ACCEPTED_FP_9282C6E3_NO_EXECUTION_AUTHORITY")
 mm=next(x for x in m["modules"] if x["id"]=="STAGE4_ALPHA_V2_EXECUTABILITY_D0")
 ck("module",m["index_version"]=="V2.6" and mm["status"]=="IMPLEMENTATION_ACCEPTED_EXECUTION_NOT_AUTHORIZED" and mm["preregistration_fingerprint"]==P_FP and mm["implementation_fingerprint"]==I_FP and mm["implementation_acceptance_fingerprint"]==A_FP and mm["development_label_execution_allowed"] is False and mm["model_fit_allowed"] is False and mm["prediction_allowed"] is False and mm["oos_access_allowed"] is False and mm["final_lockbox_status"]=="SEALED_NO_ACCESS")
 failed=[k for k,v in c.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V2_EXECUTABILITY_D0_IMPLEMENTATION_ACCEPTANCE","pass":not failed,"acceptance_fingerprint":A_FP,"implementation_fingerprint":I_FP,"checks":c,"failed_checks":failed,"development_label_execution_allowed":False,"model_fit":False,"prediction":False,"oos_access":False,"lockbox_access":False},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
