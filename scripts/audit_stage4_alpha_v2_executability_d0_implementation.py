#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
FP="33e142142a2a5b3f225f2ef831186eb476eed4ceb7cecbf23159ccd22d76546f"
PREREG_FP="5407c8293c678287596abe2bc6cced8c83d6a2f997eb6ff8720b7790d59c8e6a"
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
 c=load("governance/stage4_alpha_v2_executability_d0_implementation_contract.json")
 p=load("governance/stage4_alpha_v2_executability_d0_preregistration.json")
 s=load("governance/accepted_project_state.json")
 src=(R/"scripts/run_stage4_alpha_v2_executability_d0.py").read_text(encoding="utf-8")
 b=c["fingerprint_basis"]; checks={}
 def ck(k,v): checks[k]=bool(v)
 ck("fingerprint",c["fingerprint"]==FP and canon(b)==FP)
 ck("prereg_bound",b["preregistration_fingerprint"]==p["fingerprint"]==PREREG_FP)
 ck("input_bound",b["input"]["development_labels_artifact_id"]==9216418323 and b["input"]["labels_sha256"]=="092061da5666215dcc1f4fa75ec0b1cdbcc43969560755e7cdae6de55e64d673")
 ck("no_model_path",".fit(" not in src and ".predict(" not in src and "sklearn" not in src)
 ck("production_guards","sha256_file(labels)!=LABELS_SHA" in src and "rows!=EXPECTED_ROWS" in src and "trade_date>=DATE '2023-01-03'" in src)
 ck("diagnostic_only",b["diagnostics"]["return_metrics"] is False and b["diagnostics"]["prediction_metrics"] is False and b["diagnostics"]["policy_score"] is False and b["diagnostics"]["threshold_selection"] is False)
 perm=s["permissions"]
 ck("live_state_closed",perm["model_fit_allowed"] is False and perm["oos_label_access_allowed"] is False and perm["oos_label_bearing_execution_runs_remaining"]==0 and perm["lockbox_label_access_allowed"] is False and perm["live_signal_allowed"] is False and perm["main_merge_allowed"] is False and perm["authoritative_model_output_allowed"] is False)
 failed=[k for k,v in checks.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V2_EXECUTABILITY_D0_IMPLEMENTATION","pass":not failed,"fingerprint":FP,"checks":checks,"failed_checks":failed,"real_development_labels_read":False,"model_fit":False,"oos_access":False,"lockbox_access":False},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
