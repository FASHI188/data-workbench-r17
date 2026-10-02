#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[1]
FP="d76ae08d493f8a0c6746a9c90120399ccbfb16919550cfc25d3ad7f0a1c64de9"
WF=".github/workflows/stage2-baostock-all-stock-probe.yml"
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
def canon(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
 c=load("governance/stage4_alpha_v2_d0_dispatch_bridge_contract.json")
 s=load("governance/accepted_project_state.json")
 b=c["fingerprint_basis"];checks={}
 def ck(k,v): checks[k]=bool(v)
 ck("fingerprint",c["fingerprint"]==FP and canon(b)==FP and c["status"]=="REVIEW_ONLY_DISPATCH_BRIDGE_NO_EXECUTION_AUTHORITY")
 ck("main_identity",b["default_branch"]=="main" and b["default_branch_workflow_path"]==WF and b["default_branch_workflow_blob_sha"]=="b4d067aaaa995daf98b8019634c2bce50e7b8559")
 ck("bridge_blob",b["bridge_workflow_blob_sha"]==subprocess.check_output(["git","rev-parse",f"HEAD:{WF}"],text=True).strip())
 ck("bridge_ref",b["bridge_ref"]=="agent/stage4-alpha-v2-d0-dispatch-bridge-v1" and b["bridge_merge_policy"]=="REVIEWED_BRANCH_ONLY_DO_NOT_MERGE_TO_INTEGRATION_OR_MAIN")
 ck("d0_chain",b["d0_binding"]["preregistration_fingerprint"]=="5407c8293c678287596abe2bc6cced8c83d6a2f997eb6ff8720b7790d59c8e6a" and b["d0_binding"]["implementation_fingerprint"]=="33e142142a2a5b3f225f2ef831186eb476eed4ceb7cecbf23159ccd22d76546f" and b["d0_binding"]["implementation_acceptance_fingerprint"]=="9282c6e34235e93a07b8c4ee35d84dee99ae4748c2d112dd1a3690374c92402f")
 ck("no_authority",all(v is False for v in b["permissions"].values()))
 p=s["permissions"]
 ck("canonical_state_closed",p["model_fit_allowed"] is False and p["oos_label_access_allowed"] is False and p["oos_label_bearing_execution_runs_remaining"]==0 and p["lockbox_label_access_allowed"] is False and p["live_signal_allowed"] is False and p["main_merge_allowed"] is False and p["authoritative_model_output_allowed"] is False and p["development_label_diagnostic_access_allowed"] is False and p["development_label_diagnostic_runs_remaining"]==1)
 w=(R/WF).read_text(encoding="utf-8")
 ck("dispatch_fail_closed","d0-bridge:" in w and "github.event_name == 'workflow_dispatch'" in w and "stage4_alpha_v2_executability_d0_execution_authorization_v1_1.json" in w and "FIRST_SUCCESSFUL_DOWNLOAD_AND_DIGEST_VERIFICATION_OF_DEVELOPMENT_LABELS_ARTIFACT_FOR_D0" in w)
 failed=[k for k,v in checks.items() if not v]
 print(json.dumps({"gate":"STAGE4_ALPHA_V2_D0_DISPATCH_BRIDGE_REVIEW","pass":not failed,"fingerprint":FP,"checks":checks,"failed_checks":failed,"execution_authority_granted":False,"main_modified":False,"oos_access":False,"lockbox_access":False},indent=2))
 return 0 if not failed else 2
if __name__=="__main__": raise SystemExit(main())
