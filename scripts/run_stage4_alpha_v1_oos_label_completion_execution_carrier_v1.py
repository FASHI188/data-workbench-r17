#!/usr/bin/env python3
from __future__ import annotations
import argparse, base64, hashlib, json, os, shutil, subprocess, sys, urllib.parse, urllib.request, zipfile
from pathlib import Path
from typing import Any

R=Path(__file__).resolve().parents[1]
EXEC_FP="a1795f38cea7254924dd0d3ae4e905f40e7660f0c3eee5c7ad7857b5f95c760f"
RES_FP="4c91f96fee0970a25ecaef673419a7c5e02c02b72591e2aafeac6ee594f38558"
PREREG_FP="0e9b79a406e3a7789ade5b93878cd4276c5f424b0f0e9e4906048b9254e4cac3"
IMPL_FP="a9addd6eefc82737e5a39c7828dc9b68a5d4336e2ee3e8ebeaeee1d628014045"
IMPL_ACCEPT_FP="60522faad23985ffd5aa643be8af528673b6db8026874ef0565d2a8d30fcdaa3"
ORIG_AUTH_FP="d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d"
HIST_EXEC_FP="224d9144d1989f021c29bb17ce13a6d2644b2d8992d604738b4e596a6907d177"
BOUNDARY_FP="67e8555d3a9212a003a8293dc381cce0f7294917ef72875fed3218f240e0c255"
RUNTIME_FP="727e5d1496f1a79240d5c4f874e6b956a9539b80c104169268b9c80d26d45676"
PRED_AID=10142949262
PRED_DIGEST="068b451ecc21b05557334569e3af957e106087bf0839a3df01cbcf838536fe4c"
PRED_SHA="66a039aa76e4b1962049e3e0d41a43fb1f6c626d934a552f871f91bd27fe01da"
BOUNDARY_AID=10142948546
BOUNDARY_DIGEST="76711c8bd5277bfe569868a0be7bba5dd074cac92fde88c92e4c0ce7e127a86c"
CONFIRM="CONSUME_SINGLE_USE_OOS_LABEL_COMPLETION_V1"
CONSUMPTION="FIRST_SUCCESSFUL_READ_OF_ANY_OOS_MARKET_VALUE_USED_FOR_LABEL_MATERIALIZATION_OR_FIRST_SUCCESSFUL_READ_OF_ANY_OOS_LABEL_VALUE_WHICHEVER_OCCURS_FIRST"
WORKFLOW_FILE="stage4-alpha-v1-oos-label-completion-execution.yml"
AUTH_PATH="governance/stage4_alpha_v1_oos_label_completion_authorization_v1.json"
STATE_PATH="governance/accepted_project_state.json"
CONTRACT_PATH="governance/stage4_alpha_v1_oos_label_completion_execution_contract_v1.json"
RESERVATION_PATH="governance/stage4_alpha_v1_oos_label_completion_authorization_reservation_v1.json"
RUNNER="scripts/run_stage4_alpha_v1_oos_label_completion.py"

SRC={
 "scripts/run_stage4_alpha_v1_oos_label_completion.py":"7fe790864be6d324f4571f57ed23213920605a48d9b4415849e12c37cdb8f2d6",
 "scripts/stage4_alpha_v1_label_materialization.py":"97442670c4f5e86e541c4730549c454c07507d38459d56c742211cc4c2103ab0",
 "scripts/stage4_alpha_v1_alpha_evaluation.py":"4c4e7e1674ef64dd6e68fde65ba58d3954f2b4262e476863a21ac600fa8b68a3",
}
BLOBS={
 "scripts/run_stage4_alpha_v1_runtime_veto_v1_1.py":"26c7371fa886cc5031dddf031c7317c4ad9bdc57",
 "scripts/audit_stage4_alpha_v1_runtime_veto_v1_1.py":"35f6b388564993241e364ea3b332a9d16eca19c5",
 "governance/stage4_alpha_v1_runtime_veto_contract_v1_1.json":"b6668800143249ccf29d15a7f5c87f1a21905b98",
 "governance/stage4_alpha_v1_oos_physical_boundary_contract.json":"6b4e85cf495ff2f43b076309b10d100b369af140",
}

def load(path: str|Path)->dict[str,Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def canon(x: Any)->str:
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def sha256_file(path: Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def git_blob(path: str)->str:
    return subprocess.check_output(["git","hash-object",str(R/path)],text=True).strip()

def verify_static()->dict[str,bool]:
    c=load(R/CONTRACT_PATH); r=load(R/RESERVATION_PATH); s=load(R/STATE_PATH)
    wf=(R/".github/workflows"/WORKFLOW_FILE).read_text(encoding="utf-8")
    checks={}
    def ck(k,v): checks[k]=bool(v)
    ck("execution_contract",c.get("fingerprint")==EXEC_FP and canon(c.get("fingerprint_basis"))==EXEC_FP)
    ck("reservation",r.get("fingerprint")==RES_FP and canon(r.get("fingerprint_basis"))==RES_FP and r.get("status")=="FROZEN_SINGLE_USE_OOS_LABEL_COMPLETION_AUTHORIZATION_RESERVATION_UNARMED_NO_OOS_ACCESS")
    ck("state_allows_execution_pr_only",s["permissions"]["oos_execution_pr_creation_allowed"] is True and s["permissions"]["oos_label_access_allowed"] is False and s["permissions"]["oos_label_bearing_execution_runs_remaining"]==0)
    ck("source_hashes",c["fingerprint_basis"]["accepted_runner_sources"]==SRC and all(sha256_file(R/k)==v for k,v in SRC.items()))
    ck("runtime_blobs",c["fingerprint_basis"]["frozen_runtime_git_blobs"]==BLOBS and all(git_blob(k)==v for k,v in BLOBS.items()))
    ck("workflow_no_push_trigger","\n  push:" not in wf and "\npush:" not in wf)
    ck("workflow_has_static_pr","pull_request:" in wf and "if: github.event_name == 'pull_request'" in wf)
    ck("workflow_dispatch_only_execution","workflow_dispatch:" in wf and "if: github.event_name == 'workflow_dispatch'" in wf)
    ck("exact_head_checkout","ref: ${{ inputs.execution_head }}" in wf)
    ck("dispatch_inputs",all((x+":") in wf for x in ["execution_head","arming_merge_sha","confirmation"]))
    ck("preflight_before_install",wf.find("Preflight armed authorization and durable owner") < wf.find("Install frozen completion runtime"))
    ck("preflight_before_execute",wf.find("Preflight armed authorization and durable owner") < wf.find("Execute immutable-prediction label completion once"))
    ck("readonly_permissions","contents: read" in wf and "actions: read" in wf and "contents: write" not in wf and "actions: write" not in wf)
    ck("no_auto_promotion","separate_post_result_governance_acceptance_required" in json.dumps(c))
    failed=[k for k,v in checks.items() if not v]
    if failed: raise ValueError("static carrier audit failed: "+",".join(failed))
    return checks

class StripAuthOnCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        redirected=super().redirect_request(req,fp,code,msg,headers,newurl)
        if redirected is not None:
            if urllib.parse.urlparse(req.full_url).netloc != urllib.parse.urlparse(newurl).netloc:
                redirected.remove_header("Authorization")
        return redirected

def opener():
    return urllib.request.build_opener(StripAuthOnCrossHostRedirect())

def headers()->dict[str,str]:
    token=os.environ["GH_TOKEN"]
    return {
      "Accept":"application/vnd.github+json",
      "Authorization":"Bearer "+token,
      "X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"stage4-alpha-v1-label-completion-execution-carrier",
    }

def api_json(url:str)->dict[str,Any]:
    req=urllib.request.Request(url,headers=headers())
    with opener().open(req,timeout=60) as resp:
        return json.loads(resp.read().decode())

def fetch_repo_file(repo:str,path:str,ref:str)->bytes:
    q=urllib.parse.urlencode({"ref":ref})
    enc="/".join(urllib.parse.quote(x,safe="") for x in path.split("/"))
    data=api_json(f"https://api.github.com/repos/{repo}/contents/{enc}?{q}")
    if data.get("encoding")!="base64": raise ValueError("unexpected GitHub content encoding")
    return base64.b64decode(data["content"])

def verify_arming(execution_head:str,arming_sha:str)->dict[str,Any]:
    repo=os.environ["GITHUB_REPOSITORY"]
    if len(execution_head)!=40 or any(c not in "0123456789abcdef" for c in execution_head): raise ValueError("invalid execution head")
    if len(arming_sha)!=40 or any(c not in "0123456789abcdef" for c in arming_sha): raise ValueError("invalid arming sha")
    live="agent/stage3-clean-integration"
    comp=api_json(f"https://api.github.com/repos/{repo}/compare/{arming_sha}...{urllib.parse.quote(live,safe='')}")
    if comp.get("merge_base_commit",{}).get("sha")!=arming_sha or comp.get("status") not in {"ahead","identical"}:
        raise ValueError("arming sha is not an ancestor of live integration")
    auth=json.loads(fetch_repo_file(repo,AUTH_PATH,arming_sha).decode())
    state=json.loads(fetch_repo_file(repo,STATE_PATH,arming_sha).decode())
    b=auth.get("fingerprint_basis")
    if not isinstance(b,dict) or auth.get("fingerprint")!=canon(b): raise ValueError("armed authorization fingerprint mismatch")
    if auth.get("status")!="AUTHORIZED_SINGLE_USE_OOS_LABEL_COMPLETION_V1": raise ValueError("authorization not armed")
    expected={
      "authorization_reservation_fingerprint":RES_FP,
      "preregistration_fingerprint":PREREG_FP,
      "implementation_fingerprint":IMPL_FP,
      "implementation_acceptance_fingerprint":IMPL_ACCEPT_FP,
      "execution_contract_fingerprint":EXEC_FP,
      "original_oos_authorization_fingerprint":ORIG_AUTH_FP,
      "historical_execution_contract_fingerprint":HIST_EXEC_FP,
      "physical_boundary_contract_fingerprint":BOUNDARY_FP,
      "runtime_veto_v1_1_fingerprint":RUNTIME_FP,
      "prediction_artifact_id":PRED_AID,
      "prediction_artifact_digest":"sha256:"+PRED_DIGEST,
      "predictions_sha256":PRED_SHA,
      "physical_boundary_artifact_id":BOUNDARY_AID,
      "physical_boundary_artifact_digest":"sha256:"+BOUNDARY_DIGEST,
      "authorized_execution_head":execution_head,
      "max_label_completion_runs":1,
      "armed_runs_remaining":1,
      "consumption_event":CONSUMPTION,
      "after_consumption_reexecution_forbidden":True,
      "future_prediction_computation_allowed":False,
      "model_load_allowed":False,
      "fit_retrain_tune_reselect_allowed":False,
      "final_lockbox_access_allowed":False,
      "live_signal_allowed":False,
      "main_merge_allowed":False,
      "authoritative_output_allowed":False,
    }
    for k,v in expected.items():
        if b.get(k)!=v: raise ValueError("armed authorization drift: "+k)
    if b.get("authorization_armed") is not True: raise ValueError("authorization_armed must be true")
    p=state["permissions"]
    if state["status"]!="RESEARCH_ONLY" or p["oos_label_access_allowed"] is not False or p["oos_label_bearing_execution_runs_remaining"]!=1:
        raise ValueError("accepted state does not expose exactly one armed dispatch while keeping integration label access closed")
    if p["model_fit_allowed"] or p["lockbox_label_access_allowed"] or p["live_signal_allowed"] or p["main_merge_allowed"] or p["authoritative_model_output_allowed"]:
        raise ValueError("sensitive permission unexpectedly open")
    return auth

def reserve_owner(execution_head:str,arming_sha:str,auth:dict[str,Any])->dict[str,Any]:
    repo=os.environ["GITHUB_REPOSITORY"]; current=int(os.environ["GITHUB_RUN_ID"])
    wf=urllib.parse.quote(WORKFLOW_FILE,safe="")
    q=urllib.parse.urlencode({"event":"workflow_dispatch","per_page":100})
    data=api_json(f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?{q}")
    runs=[x for x in data.get("workflow_runs",[]) if x.get("event")=="workflow_dispatch"]
    runs.sort(key=lambda x:(x.get("created_at") or "",int(x["id"])))
    if len(runs)!=1 or int(runs[0]["id"])!=current:
        raise ValueError("current run is not the unique first workflow_dispatch owner; separate governance acknowledgement required before retry")
    evidence={
      "schema_version":1,
      "status":"PRE_ACCESS_OWNER_RESERVED_NO_OOS_VALUE_READ_YET",
      "run_id":current,
      "execution_head":execution_head,
      "arming_merge_sha":arming_sha,
      "authorization_fingerprint":auth["fingerprint"],
      "oos_artifact_downloaded":False,
      "oos_market_value_read":False,
      "oos_label_value_read":False,
      "authorization_consumed":False,
      "prediction_recomputed":False,
      "model_loaded":False,
      "final_lockbox_accessed":False,
    }
    p=R/"build/pre-access";p.mkdir(parents=True,exist_ok=True)
    (p/"dispatch_preflight.json").write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
    return evidence

def download_artifact(repo:str,aid:int,expected_zip_sha:str,dest_zip:Path,dest_dir:Path)->None:
    url=f"https://api.github.com/repos/{repo}/actions/artifacts/{aid}/zip"
    req=urllib.request.Request(url,headers=headers())
    dest_zip.parent.mkdir(parents=True,exist_ok=True)
    with opener().open(req,timeout=180) as resp,dest_zip.open("wb") as out:
        shutil.copyfileobj(resp,out)
    got=sha256_file(dest_zip)
    if got!=expected_zip_sha: raise ValueError(f"artifact {aid} zip digest mismatch: {got}")
    dest_dir.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(dest_zip) as z:
        for info in z.infolist():
            target=(dest_dir/info.filename).resolve()
            if not str(target).startswith(str(dest_dir.resolve())+os.sep) and target!=dest_dir.resolve():
                raise ValueError("artifact zip path traversal")
        z.extractall(dest_dir)

def execute(execution_head:str,arming_sha:str)->int:
    pre=R/"build/pre-access/dispatch_preflight.json"
    if not pre.is_file(): raise ValueError("pre-access reservation evidence missing")
    pe=load(pre)
    if pe["execution_head"]!=execution_head or pe["arming_merge_sha"]!=arming_sha or pe["run_id"]!=int(os.environ["GITHUB_RUN_ID"]):
        raise ValueError("pre-access evidence binding mismatch")
    auth=verify_arming(execution_head,arming_sha)
    auth_dir=R/"build/arming";auth_dir.mkdir(parents=True,exist_ok=True)
    auth_path=auth_dir/"authorization.json";auth_path.write_text(json.dumps(auth,indent=2)+"\n",encoding="utf-8")
    repo=os.environ["GITHUB_REPOSITORY"]
    pred_dir=R/"build/prediction-artifact";bound_dir=R/"build/physical-boundary"
    download_artifact(repo,PRED_AID,PRED_DIGEST,R/"build/zips/prediction.zip",pred_dir)
    names=sorted(p.name for p in pred_dir.iterdir() if p.is_file())
    if names!=["authorization_consumption.json","oos_predictions.parquet"]: raise ValueError("prediction artifact file set drift")
    if sha256_file(pred_dir/"oos_predictions.parquet")!=PRED_SHA: raise ValueError("prediction parquet hash drift")
    download_artifact(repo,BOUNDARY_AID,BOUNDARY_DIGEST,R/"build/zips/boundary.zip",bound_dir)
    artifact_evidence={
      "schema_version":1,"status":"IMMUTABLE_INPUTS_DOWNLOADED_AFTER_ARMING_AND_OWNER_VALIDATION",
      "run_id":int(os.environ["GITHUB_RUN_ID"]),"execution_head":execution_head,"arming_merge_sha":arming_sha,
      "prediction_artifact_id":PRED_AID,"prediction_zip_sha256":PRED_DIGEST,"predictions_sha256":PRED_SHA,
      "physical_boundary_artifact_id":BOUNDARY_AID,"physical_boundary_zip_sha256":BOUNDARY_DIGEST,
      "prediction_recomputed":False,"model_loaded":False,"oos_market_value_read_before_runner":False,"oos_label_value_read_before_runner":False,
    }
    (R/"build/pre-access/artifact_download_evidence.json").write_text(json.dumps(artifact_evidence,indent=2)+"\n",encoding="utf-8")
    out=R/"build/out";work=R/"build/work";out.mkdir(parents=True,exist_ok=True);work.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ);env["EXECUTION_HEAD"]=execution_head
    cmd=[sys.executable,str(R/RUNNER),"--authorization",str(auth_path),"--predictions",str(pred_dir/"oos_predictions.parquet"),"--physical-boundary",str(bound_dir),"--work-dir",str(work),"--out",str(out),"--execution-head",execution_head]
    subprocess.run(cmd,check=True,env=env)
    return 0

def preflight(execution_head:str,arming_sha:str,confirmation:str)->int:
    verify_static()
    if confirmation!=CONFIRM: raise ValueError("confirmation token mismatch")
    git_head=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    if git_head!=execution_head: raise ValueError("checkout head mismatch")
    auth=verify_arming(execution_head,arming_sha)
    reserve_owner(execution_head,arming_sha,auth)
    print(json.dumps({"preflight":"PASS","execution_head":execution_head,"arming_merge_sha":arming_sha,"authorization_fingerprint":auth["fingerprint"],"oos_artifact_downloaded":False,"oos_market_value_read":False,"oos_label_value_read":False},indent=2))
    return 0

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("--mode",choices=["static","preflight","execute"],required=True)
    ap.add_argument("--execution-head");ap.add_argument("--arming-merge-sha");ap.add_argument("--confirmation")
    a=ap.parse_args()
    if a.mode=="static":
        checks=verify_static();print(json.dumps({"static_carrier":"PASS","execution_contract_fingerprint":EXEC_FP,"checks":checks,"oos_artifact_downloaded":False,"oos_market_value_read":False,"oos_label_value_read":False},indent=2));return 0
    if not a.execution_head or not a.arming_merge_sha: raise ValueError("execution head and arming merge sha required")
    if a.mode=="preflight": return preflight(a.execution_head,a.arming_merge_sha,a.confirmation or "")
    return execute(a.execution_head,a.arming_merge_sha)

if __name__=="__main__":
    raise SystemExit(main())
