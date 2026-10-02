#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
FP="5407c8293c678287596abe2bc6cced8c83d6a2f997eb6ff8720b7790d59c8e6a"
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
 d=load("governance/stage4_alpha_v2_executability_d0_preregistration.json")
 d1=load("governance/stage4_alpha_v2_executability_d1_preregistration.json")
 acc=load("governance/stage4_alpha_v2_executability_d1_preregistration_acceptance.json")
 lab=load("governance/stage4_alpha_v1_development_labels_evidence.json")
 state=load("governance/accepted_project_state.json")
 b=d["fingerprint_basis"]; c={}
 def ck(k,v): c[k]=bool(v)
 ck("fingerprint",d["fingerprint"]==FP and canon(b)==FP)
 ck("d1_bound",b["authority"]["d1_preregistration_fingerprint"]==d1["fingerprint"]=="a469999d0bcee95bcc140ebf72727e36efc449ca048d693063ecc9bfb8e87c8d" and b["authority"]["d1_acceptance_fingerprint"]==acc["fingerprint"]=="6cf8b17249cff6889de8c6bff5952f5293987ed16cfc203e1cf8f55924b48dd5")
 ck("labels_bound",lab["workflow"]["artifact_id"]==9216418323 and lab["hashes"]["development_labels_sha256"]==b["authority"]["development_labels"]["labels_sha256"] and lab["population"]["label_rows"]==5197648 and lab["population"]["valid_20d_rows"]==5103016)
 s=b["scope"]
 ck("only_structure_fields",all(x not in s["fields_allowed"] for x in s["forbidden_input_fields"]) and s["model_fit_forbidden"] and s["prediction_forbidden"] and s["feature_matrix_access_forbidden"] and s["oos_access_forbidden"] and s["final_lockbox_access_forbidden"])
 rd=b["required_diagnostics"]
 ck("no_economic_or_policy",rd["no_return_metric"] and rd["no_prediction_rank"] and rd["no_policy_score"] and rd["no_threshold_selection"] and rd["no_candidate_comparison"])
 ck("d1_blocked",b["authority"]["expired_development_prepared_artifact"]["current_download_status"]=="NOT_FOUND_EXPIRED")
 p=state["permissions"]
 ck("live_state_closed",p["model_fit_allowed"] is False and p["oos_label_access_allowed"] is False and p["oos_label_bearing_execution_runs_remaining"]==0 and p["lockbox_label_access_allowed"] is False and p["live_signal_allowed"] is False and p["main_merge_allowed"] is False and p["authoritative_model_output_allowed"] is False)
 failed=[k for k,v in c.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V2_EXECUTABILITY_D0_PREREGISTRATION","pass":not failed,"fingerprint":FP,"checks":c,"failed_checks":failed,"development_label_values_read":False,"return_values_read":False,"model_fit":False,"oos_access":False,"lockbox_access":False},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
