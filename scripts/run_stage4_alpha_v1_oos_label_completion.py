#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,re,subprocess,sys,tempfile
from pathlib import Path
from typing import Any
from stage4_alpha_v1_label_materialization import (
    PREREG_FP,BOUNDARY_FP,PRED_SHA256,PRED_ROWS,OOS_START,OOS_END,LATEST_VALID20,LOCKBOX_START,
    IMPLEMENTATION_FP,BOUNDARY_FILES,canonical_hash,sha256_file,validate_prediction_input,
    validate_physical_boundary,write_consumption_marker,materialize_labels,
)
from stage4_alpha_v1_alpha_evaluation import evaluate_alpha

HIST_EXEC_FP="224d9144d1989f021c29bb17ce13a6d2644b2d8992d604738b4e596a6907d177"
RUNTIME_VETO_FP="727e5d1496f1a79240d5c4f874e6b956a9539b80c104169268b9c80d26d45676"
ORIGINAL_AUTH_FP="d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d"
PRED_ARTIFACT_ID=10142949262
PRED_ARTIFACT_DIGEST="sha256:068b451ecc21b05557334569e3af957e106087bf0839a3df01cbcf838536fe4c"
BOUNDARY_ARTIFACT_ID=10142948546
BOUNDARY_ARTIFACT_DIGEST="sha256:76711c8bd5277bfe569868a0be7bba5dd074cac92fde88c92e4c0ce7e127a86c"
CONSUMPTION_EVENT="FIRST_SUCCESSFUL_READ_OF_ANY_OOS_MARKET_VALUE_USED_FOR_LABEL_MATERIALIZATION_OR_FIRST_SUCCESSFUL_READ_OF_ANY_OOS_LABEL_VALUE_WHICHEVER_OCCURS_FIRST"
EXPECTED_QUARTERS=["2023Q1","2023Q2","2023Q3","2023Q4","2024Q1","2024Q2","2024Q3","2024Q4"]
RUNTIME_RUNNER=Path(__file__).with_name("run_stage4_alpha_v1_runtime_veto_v1_1.py")
RUNTIME_AUDITOR=Path(__file__).with_name("audit_stage4_alpha_v1_runtime_veto_v1_1.py")
RUNTIME_CONTRACT=Path("governance/stage4_alpha_v1_runtime_veto_contract_v1_1.json")
BOUNDARY_CONTRACT=Path("governance/stage4_alpha_v1_oos_physical_boundary_contract.json")
FROZEN_GIT_BLOBS={
 str(RUNTIME_RUNNER):"26c7371fa886cc5031dddf031c7317c4ad9bdc57",
 str(RUNTIME_AUDITOR):"35f6b388564993241e364ea3b332a9d16eca19c5",
 str(RUNTIME_CONTRACT):"b6668800143249ccf29d15a7f5c87f1a21905b98",
 str(BOUNDARY_CONTRACT):"6b4e85cf495ff2f43b076309b10d100b369af140",
}

def validate_frozen_dependencies()->None:
    for path,expected in FROZEN_GIT_BLOBS.items():
        p=Path(path)
        if not p.is_file(): raise ValueError("frozen dependency missing: "+path)
        got=subprocess.check_output(["git","hash-object",str(p)],text=True).strip()
        if got!=expected: raise ValueError(f"frozen dependency drift: {path} {got} != {expected}")

def validate_future_authorization(path:Path,execution_head:str)->dict[str,Any]:
    auth=json.loads(path.read_text(encoding="utf-8"));basis=auth.get("fingerprint_basis")
    if not isinstance(basis,dict) or auth.get("fingerprint")!=canonical_hash(basis): raise ValueError("future label-completion authorization fingerprint mismatch")
    if auth.get("status")!="AUTHORIZED_SINGLE_USE_OOS_LABEL_COMPLETION_V1": raise ValueError("unexpected future label-completion authorization status")
    expected={
      "preregistration_fingerprint":PREREG_FP,"implementation_fingerprint":IMPLEMENTATION_FP,
      "original_oos_authorization_fingerprint":ORIGINAL_AUTH_FP,"historical_execution_contract_fingerprint":HIST_EXEC_FP,
      "physical_boundary_contract_fingerprint":BOUNDARY_FP,"runtime_veto_v1_1_fingerprint":RUNTIME_VETO_FP,
      "prediction_artifact_id":PRED_ARTIFACT_ID,"prediction_artifact_digest":PRED_ARTIFACT_DIGEST,"predictions_sha256":PRED_SHA256,
      "physical_boundary_artifact_id":BOUNDARY_ARTIFACT_ID,"physical_boundary_artifact_digest":BOUNDARY_ARTIFACT_DIGEST,
      "max_label_completion_runs":1,"consumption_event":CONSUMPTION_EVENT,"future_prediction_computation_allowed":False,
      "model_load_allowed":False,"fit_retrain_tune_reselect_allowed":False,"final_lockbox_access_allowed":False,
      "live_signal_allowed":False,"main_merge_allowed":False,"authoritative_output_allowed":False,
    }
    for k,v in expected.items():
        if basis.get(k)!=v: raise ValueError("future authorization drift: "+k)
    if basis.get("authorized_execution_head")!=execution_head: raise ValueError("future authorization execution head mismatch")
    if basis.get("after_consumption_reexecution_forbidden") is not True: raise ValueError("future authorization must forbid post-consumption reexecution")
    return auth

def run_cmd(args:list[str])->None:
    subprocess.run(args,check=True)

def synthetic_self_test()->int:
    import pandas as pd,pyarrow as pa,pyarrow.parquet as pq
    validate_frozen_dependencies()
    run_cmd([sys.executable,str(RUNTIME_RUNNER),"--synthetic-self-test"])
    run_cmd([sys.executable,str(RUNTIME_AUDITOR),"--synthetic-self-test"])
    with tempfile.TemporaryDirectory(prefix="stage4-label-completion-synth-") as td:
        root=Path(td);boundary=root/"boundary";work=root/"work";out=root/"out"
        boundary.mkdir();work.mkdir();out.mkdir()
        dates=pd.bdate_range(OOS_START,OOS_END).date;codes=[f"{600000+i:06d}" for i in range(25)]
        pred=[];market=[];life=[]
        for j,code in enumerate(codes):
            drift=.0003+(j/(len(codes)-1))*.0017;score=float(j);life.append({"exchange":"SSE","code":code,"listed_from":dates[0],"listed_to_exclusive":None})
            for i,d in enumerate(dates):
                px=10.0*((1.0+drift)**i);pred.append({"trade_date":d,"exchange":"SSE","code":code,"prediction":score});market.append({"trade_date":d,"exchange":"SSE","code":code,"open":px,"high":px*1.001,"low":px*.999,"close":px,"volume_shares":1_000_000.0,"factor":1.0})
        predictions=root/"oos_predictions.parquet";pq.write_table(pa.Table.from_pylist(pred),predictions,compression="zstd")
        pq.write_table(pa.Table.from_pylist(market),boundary/BOUNDARY_FILES["market"],compression="zstd");pq.write_table(pa.Table.from_pylist(life),boundary/BOUNDARY_FILES["lifecycle"],compression="zstd")
        # Synthetic mode needs only market/lifecycle plus placeholder boundary metadata; real Runtime Veto is tested by its frozen self-tests above.
        (boundary/BOUNDARY_FILES["execution_state"]).write_bytes(b"synthetic-not-read")
        (boundary/BOUNDARY_FILES["manifest"]).write_text(json.dumps({"status":"SYNTHETIC"})+"\n")
        (boundary/BOUNDARY_FILES["independent_audit"]).write_text(json.dumps({"pass":True,"failed_checks":[]})+"\n")
        (boundary/BOUNDARY_FILES["hashes"]).write_text("{}\n")
        validate_prediction_input(predictions,synthetic=True);files=validate_physical_boundary(boundary,synthetic=True)
        consumed={"n":0}
        def mark(): consumed["n"]+=1
        labels,meta=materialize_labels(predictions,files["market"],files["lifecycle"],work,expected_start=OOS_START,expected_end=OOS_END,latest_valid20=LATEST_VALID20,lockbox_start=LOCKBOX_START,consume_callback=mark)
        if consumed["n"]!=1: raise AssertionError("synthetic consumption callback not exactly once")
        alpha=evaluate_alpha(predictions,labels,out,latest_valid20=LATEST_VALID20,expected_start=OOS_START,expected_quarters=EXPECTED_QUARTERS,positive_quarters_required=6,bootstrap_resamples=1000)
        if not alpha["gate_pass"]: raise AssertionError("synthetic positive Alpha path must pass")
        src=Path(__file__).with_name("stage4_alpha_v1_label_materialization.py").read_text()
        if 'CAST("close" AS DOUBLE)' not in src or 'CAST("open" AS DOUBLE) AS open_px' not in src: raise AssertionError("identifier-safe parser repair missing")
        if re.search(r"CAST\(close AS DOUBLE\)|CAST\(open AS DOUBLE\)",src): raise AssertionError("unquoted parser-defect form reintroduced")
        print(json.dumps({"synthetic_self_test":"PASS","label_rows":meta["label_rows"],"alpha_gate_pass":True,"runtime_veto_v1_1_frozen_self_tests":True,"prediction_recomputed":False,"model_loaded":False,"oos_value_read":False,"final_lockbox_accessed":False},indent=2))
    return 0

def execute(a:argparse.Namespace)->int:
    validate_frozen_dependencies();head=a.execution_head
    if not re.fullmatch(r"[0-9a-f]{40}",head): raise ValueError("invalid execution head")
    if os.environ.get("EXECUTION_HEAD") and os.environ["EXECUTION_HEAD"]!=head: raise ValueError("execution head environment mismatch")
    auth=validate_future_authorization(Path(a.authorization),head);pred=Path(a.predictions);boundary=Path(a.physical_boundary);work=Path(a.work_dir);out=Path(a.out);work.mkdir(parents=True,exist_ok=True);out.mkdir(parents=True,exist_ok=True)
    ps=validate_prediction_input(pred,synthetic=False);files=validate_physical_boundary(boundary,synthetic=False);consumed={"done":False}
    def consume_once():
        if not consumed["done"]: write_consumption_marker(out,auth,head);consumed["done"]=True
    labels,meta=materialize_labels(pred,files["market"],files["lifecycle"],work,expected_start=OOS_START,expected_end=OOS_END,latest_valid20=LATEST_VALID20,lockbox_start=LOCKBOX_START,consume_callback=consume_once)
    if not consumed["done"]: raise ValueError("authorization not consumed at first successful market-value read")
    alpha=evaluate_alpha(pred,labels,out,latest_valid20=LATEST_VALID20,expected_start=OOS_START,expected_quarters=EXPECTED_QUARTERS,positive_quarters_required=6)
    runtime_dir=out/"runtime_veto_v1_1";runtime_dir.mkdir(exist_ok=True);audit_out=out/"oos_runtime_veto_independent_audit.json"
    common=["--contract",str(RUNTIME_CONTRACT),"--boundary-contract",str(BOUNDARY_CONTRACT),"--physical-boundary",str(boundary),"--predictions",str(pred)]
    run_cmd([sys.executable,str(RUNTIME_RUNNER),*common,"--out",str(runtime_dir)])
    run_cmd([sys.executable,str(RUNTIME_AUDITOR),*common,"--runtime-dir",str(runtime_dir),"--out",str(audit_out)])
    runtime=json.loads((runtime_dir/"oos_runtime_veto_summary.json").read_text());ra=json.loads(audit_out.read_text());runtime_pass=bool(runtime.get("gate_pass") and ra.get("pass"));combined=bool(alpha["gate_pass"] and runtime_pass)
    result={"schema_version":1,"status":"BOTH_GATES_PASS_NO_AUTO_PROMOTION" if combined else "NO_PROMOTION_NO_RETUNING_ON_OOS","execution_head":head,"authorization_fingerprint":auth["fingerprint"],"implementation_fingerprint":IMPLEMENTATION_FP,"prediction_rows":int(ps["rows"]),"prediction_recomputed":False,"model_loaded":False,"fit_retraining_tuning_reselection_executed":False,"label_completion":meta,"alpha_gate_pass":bool(alpha["gate_pass"]),"runtime_veto_gate_pass":runtime_pass,"combined_business_gate_pass":combined,"auto_promotion":False,"separate_post_result_governance_acceptance_required":True,"final_lockbox_accessed":False,"live_signal_allowed":False,"authoritative_output":False,"main_merge_allowed":False,"failure_action":"NO_PROMOTION_NO_RETUNING_ON_OOS"}
    (out/"label_completion_result.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result,indent=2));return 0

def main()->int:
    if "--synthetic-self-test" in sys.argv:return synthetic_self_test()
    ap=argparse.ArgumentParser()
    for n in ["authorization","predictions","physical-boundary","work-dir","out","execution-head"]:ap.add_argument("--"+n,required=True)
    return execute(ap.parse_args())
if __name__=="__main__":raise SystemExit(main())
