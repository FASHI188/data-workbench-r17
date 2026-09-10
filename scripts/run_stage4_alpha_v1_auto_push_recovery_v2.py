#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

RECOVERY_FP = "e7074a5bf328c548be0d7c6d1fba4db2a36ec3712e14842c912125bef85e75ad"
AUTH_FP = "d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d"
EXEC_FP = "224d9144d1989f021c29bb17ce13a6d2644b2d8992d604738b4e596a6907d177"
BOUNDARY_FP = "67e8555d3a9212a003a8293dc381cce0f7294917ef72875fed3218f240e0c255"
RUNTIME_FP = "727e5d1496f1a79240d5c4f874e6b956a9539b80c104169268b9c80d26d45676"
CORE_BLOB = "19134bc8960b6c9c825ea2708aa1aac14ce914af"
CONFIRM = "CONSUME_D260F117_SINGLE_OOS_RUN"
BRANCH = "agent/stage4-alpha-v1-oos-validation-execution"
WORKFLOW_FILE = "stage4-alpha-v1-oos-auto-push-recovery-v2.yml"
REQUEST_PATH = "governance/stage4_alpha_v1_oos_auto_push_recovery_request_v2.json"
SUPERSESSION_PATH = "governance/stage4_alpha_v1_oos_auto_push_recovery_supersession_v2.json"
RUNTIME_CONTRACT = "governance/stage4_alpha_v1_runtime_veto_contract_v1_1.json"
BOUNDARY_CONTRACT = "governance/stage4_alpha_v1_oos_physical_boundary_contract.json"
SOURCE_AUTH = "governance/stage4_alpha_v1_training_execution_authorization.json"
OOS_AUTH = "governance/stage4_alpha_v1_oos_validation_authorization.json"
EXEC_CONTRACT = "governance/stage4_alpha_v1_oos_validation_execution_contract.json"
ACCEPTED_STATE = "governance/accepted_project_state.json"
CORE_PATH = "scripts/run_stage4_alpha_v1_oos_validation_core.py"
ALPHA_AUDIT = "scripts/audit_stage4_alpha_v1_oos_validation.py"
BOUNDARY_BUILD_V12 = "scripts/build_stage4_alpha_v1_oos_physical_boundary_v1_2.py"
BOUNDARY_AUDIT_V12 = "scripts/audit_stage4_alpha_v1_oos_physical_boundary_v1_2.py"
RUNTIME_RUN_V11 = "scripts/run_stage4_alpha_v1_runtime_veto_v1_1.py"
RUNTIME_AUDIT_V11 = "scripts/audit_stage4_alpha_v1_runtime_veto_v1_1.py"

MATRIX_AID = 9168728086
MATRIX_ZIP_SHA = "a4d3a10165bf3b369c77c7b4f77e97663bc3125f506d9203388e6f63198bda4a"
MATRIX_SHA = "c5fca80bc0f35c008590fe8f6cd7b8a16ab22e13b4978314a812f1ecb60b391c"
G3_AID = 8651700277
G3_ZIP_SHA = "bf977d4f379d421bd198865b90df90caef7ba6cfb5d6d1af96e5487300c1a2f8"
G4_AID = 8651786270
G4_ZIP_SHA = "3343a1a42e5debf19d4a9595067cad50d808c979c8ae98f0ae8abbc09f1772cd"
G5_AID = 8651976824
G5_ZIP_SHA = "acbeaaca9fc849acbef213dbd9b50df034f28e36acd352e625acb44e536cbe22"
G2_AID = 8651477081
G2_ZIP_SHA = "652193c9ce18ad9e4cc93b8050910a1fb8b91c849bfdd990e9ee5f860ac147dd"
MODEL_AID = 9251178312
MODEL_ZIP_SHA = "e222dd2931933eb3e0c8aca0a35ee09e388a89cc8ea8f194df61c0c3b4b6cb5d"
MODEL_SHA = "e85aabf694799a16f8c5a1dea017e3489a9025ecf3d484d7a4f3fd931b0d702c"
PREPROCESS_SHA = "4b7833e4c4bdba9b956dba190f7337003ae944a624b59ddad7654b1457608330"
REFIT_MANIFEST_SHA = "153886720fc5d3fb424514984d51843c0e04c35474aa0c5feb4d81682982d826"


def canon(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run(cmd):
    subprocess.run(cmd, check=True)


def verify_frozen_authority():
    s = load(SUPERSESSION_PATH)
    assert s["status"] == "FROZEN_PRE_ACCESS_AUTO_PUSH_RECOVERY_V2_NO_OOS_ACCESS"
    assert canon(s["fingerprint_basis"]) == s["fingerprint"] == RECOVERY_FP
    b = s["fingerprint_basis"]
    assert b["repository"] == "FASHI188/data-workbench-r17"
    assert b["execution_branch"] == BRANCH
    assert b["auto_workflow_path"].endswith("/" + WORKFLOW_FILE)
    assert b["request_path"] == REQUEST_PATH
    a = b["authority"]
    assert a["oos_authorization_fingerprint"] == AUTH_FP
    assert a["execution_contract_v1_1_fingerprint"] == EXEC_FP
    assert a["physical_boundary_fingerprint"] == BOUNDARY_FP
    assert a["runtime_veto_v1_1_fingerprint"] == RUNTIME_FP
    assert a["frozen_core_git_blob"] == CORE_BLOB
    assert a["confirmation_token"] == CONFIRM
    z = b["failed_owner_zero_access_evidence"]
    assert z["failed_owner_run_id"] == 34208397287
    for k in ["model_downloaded", "model_loaded", "oos_prediction_computed", "oos_label_value_read", "authorization_consumed", "final_lockbox_accessed"]:
        assert z[k] is False
    d = b["independent_repair_evidence"]
    assert d["diagnostic_run_id"] == 34209917491
    assert d["finding"] == "PASS_LIFECYCLE_EXPLAINS_ALL_GAPS"
    assert d["entry_missing_state_rows"] == 52 and d["entry_active_lifecycle_missing_rows"] == 0 and d["entry_after_delist_rows"] == 52
    assert d["exit_missing_state_rows"] == 1217 and d["exit_active_lifecycle_missing_rows"] == 0 and d["exit_after_delist_rows"] == 1217
    for k in ["model_loaded", "oos_prediction_computed", "oos_label_value_read", "authorization_consumed"]:
        assert d[k] is False
    r = b["recovery_semantics"]
    assert r["old_owner_run_must_not_be_rerun"] is True
    assert r["eligible_recovery_event"] == "push"
    assert r["push_branch_exact"] == BRANCH and r["push_path_exact"] == REQUEST_PATH
    assert r["request_status_required"] == "ARMED_SINGLE_USE_AUTO_PUSH_RECOVERY_V2"
    assert r["current_run_attempt_must_equal"] == 1
    assert r["recovery_ledger_source"] == "IMMUTABLE_GITHUB_ACTIONS_RUN_HISTORY_FOR_RECOVERY_V2_WORKFLOW"
    assert r["earliest_recovery_v2_push_run_is_owner"] is True
    assert r["later_recovery_pushes_fail_closed"] is True
    assert r["automatic_rerun_forbidden"] is True and r["automatic_release_forbidden"] is True
    assert r["this_supersession_adds_no_authorization"] is True
    assert r["accepted_label_bearing_run_count_not_increased"] is True
    assert r["reservation_is_not_authorization_consumption"] is True
    assert r["authorization_consumed_at"] == "FIRST_OOS_PREDICTION_COMPUTATION"
    assert all(b["repair_scope"].values())
    assert b["workflow_permissions"] == {
        "contents": "read",
        "actions": "read",
        "repository_write_forbidden": True,
        "workflow_dispatch_creation_forbidden": True,
    }
    rc = load(RUNTIME_CONTRACT)
    assert rc["status"] == "FROZEN_PRE_ACCESS_RUNTIME_VETO_V1_1_LIFECYCLE_AWARE_NO_OOS_EXECUTION"
    assert canon(rc["fingerprint_basis"]) == rc["fingerprint"] == RUNTIME_FP
    assert rc["fingerprint_basis"]["physical_boundary_contract_fingerprint"] == BOUNDARY_FP
    ls = rc["fingerprint_basis"]["lifecycle_semantics"]
    assert ls["lifecycle_inactive_is_not_missing_data"] is True
    assert ls["lifecycle_inactive_does_not_modify_prediction_ranking_or_bucket_membership"] is True
    bc = load(BOUNDARY_CONTRACT)
    assert canon(bc["fingerprint_basis"]) == bc["fingerprint"] == BOUNDARY_FP
    got_blob = subprocess.check_output(["git", "hash-object", CORE_PATH], text=True).strip()
    assert got_blob == CORE_BLOB
    return s


def verify_request(armed_required: bool):
    r = load(REQUEST_PATH)
    assert r["supersession_fingerprint"] == RECOVERY_FP
    assert r["target_workflow_file"] == WORKFLOW_FILE
    assert r["target_branch"] == BRANCH
    assert r["authorization_fingerprint"] == AUTH_FP
    assert r["execution_contract_fingerprint"] == EXEC_FP
    assert r["runtime_veto_fingerprint"] == RUNTIME_FP
    assert r["confirmation"] == CONFIRM
    assert r["execution_head_source"] == "GITHUB_SHA_OF_ARMING_RECOVERY_REQUEST_COMMIT"
    assert r["failed_owner_run_id"] == 34208397287
    if armed_required:
        assert r["status"] == "ARMED_SINGLE_USE_AUTO_PUSH_RECOVERY_V2" and r["armed"] is True
    else:
        assert r["status"] in {"DISARMED_PRE_ACCESS_RECOVERY_V2", "ARMED_SINGLE_USE_AUTO_PUSH_RECOVERY_V2"}
        assert r["armed"] is (r["status"] == "ARMED_SINGLE_USE_AUTO_PUSH_RECOVERY_V2")
    return r


def static_self_test():
    verify_frozen_authority()
    r = verify_request(False)
    run([sys.executable, RUNTIME_RUN_V11, "--synthetic-self-test"])
    run([sys.executable, RUNTIME_AUDIT_V11, "--synthetic-self-test"])
    print(json.dumps({
        "recovery_pre_access_static": "PASS",
        "request_status": r["status"],
        "authorization_consumed": False,
        "oos_prediction_executed": False,
        "oos_label_value_read": False,
        "model_loaded": False,
        "final_lockbox_accessed": False,
    }, sort_keys=True))
    return 0


def reserve():
    verify_frozen_authority()
    verify_request(True)
    assert os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
    assert os.environ["GITHUB_RUN_ATTEMPT"] == "1"
    sha = os.environ["GITHUB_SHA"]
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == sha
    changed = subprocess.check_output(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha], text=True).strip().splitlines()
    assert changed == [REQUEST_PATH], changed
    repo = os.environ["GITHUB_REPOSITORY"]
    current = int(os.environ["GITHUB_RUN_ID"])
    token = os.environ["GH_TOKEN"]
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "stage4-alpha-v1-recovery-v2-reservation",
    }
    runs = None
    wf = urllib.parse.quote(WORKFLOW_FILE, safe="")
    for _ in range(12):
        q = urllib.parse.urlencode({"event": "push", "branch": BRANCH, "per_page": 100})
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?{q}",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        rr = [x for x in (data.get("workflow_runs") or []) if x.get("event") == "push" and x.get("head_branch") == BRANCH]
        if any(int(x["id"]) == current for x in rr):
            runs = rr
            break
        time.sleep(2)
    assert runs is not None, "current recovery push run not visible in durable Actions history"
    runs.sort(key=lambda x: (x.get("created_at") or "", int(x["id"])))
    assert len(runs) == 1, [(x["id"], x["head_sha"]) for x in runs]
    owner = runs[0]
    assert int(owner["id"]) == current
    assert owner["head_sha"] == sha
    print(json.dumps({
        "recovery_reservation_owner_run_id": current,
        "execution_head": sha,
        "eligible_recovery_v2_push_runs": [current],
        "old_failed_owner_run_id": 34208397287,
        "authorization_consumed": False,
    }, sort_keys=True))
    return 0


def download_artifact(artifact_id: int, expected_zip_sha: str, zip_path: Path, extract_dir: Path):
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "stage4-alpha-v1-recovery-v2-artifact-reader",
    }
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip",
        headers=headers,
    )
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=180) as resp, zip_path.open("wb") as out:
        shutil.copyfileobj(resp, out)
    got = sha256_file(zip_path)
    assert got == expected_zip_sha, (artifact_id, got, expected_zip_sha)
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(extract_dir)


def boundary():
    verify_frozen_authority()
    verify_request(True)
    assert os.environ.get("EXECUTION_HEAD") == os.environ.get("GITHUB_SHA")
    root = Path("build")
    src = root / "oos-boundary-sources"
    out = root / "oos-boundary"
    work = root / "oos-boundary-work"
    for forbidden in [root / "model", root / "oos", root / "runtime-veto"]:
        assert not forbidden.exists(), str(forbidden)
    for sub in ["matrix", "g3", "g4", "g5", "g2"]:
        (src / sub).mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    specs = [
        ("matrix", MATRIX_AID, MATRIX_ZIP_SHA),
        ("g3", G3_AID, G3_ZIP_SHA),
        ("g4", G4_AID, G4_ZIP_SHA),
        ("g5", G5_AID, G5_ZIP_SHA),
        ("g2", G2_AID, G2_ZIP_SHA),
    ]
    for name, aid, digest in specs:
        download_artifact(aid, digest, src / f"{name}.zip", src / name)
    matrix = src / "matrix" / "stage4_v1_2_feature_matrix.parquet"
    assert matrix.is_file() and sha256_file(matrix) == MATRIX_SHA
    assert len(list((src / "g4").rglob("g4_state_shard*.csv.gz"))) == 16

    bc = load(BOUNDARY_CONTRACT)
    assert bc["fingerprint"] == BOUNDARY_FP
    inputs = bc["fingerprint_basis"]["inputs"]
    env_specs = {
        "feature_matrix": (MATRIX_AID, MATRIX_ZIP_SHA),
        "stage2_g3": (G3_AID, G3_ZIP_SHA),
        "stage2_g4": (G4_AID, G4_ZIP_SHA),
        "stage2_g5": (G5_AID, G5_ZIP_SHA),
        "stage2_g2": (G2_AID, G2_ZIP_SHA),
    }
    artifacts = {}
    for key, (aid, digest) in env_specs.items():
        assert int(inputs[key]["artifact_id"]) == aid
        assert inputs[key]["artifact_zip_sha256"] == digest
        artifacts[key] = {"artifact_id": aid, "archive_sha256": digest, "verified": True}
    source_verification = {
        "schema_version": 3,
        "status": "VERIFIED",
        "boundary_contract_fingerprint": BOUNDARY_FP,
        "artifacts": artifacts,
    }
    sv = out / "source_archive_verification.json"
    sv.write_text(json.dumps(source_verification, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    run([
        sys.executable, BOUNDARY_BUILD_V12,
        "--contract", BOUNDARY_CONTRACT,
        "--source-cv-authorization", SOURCE_AUTH,
        "--source-verification", str(sv),
        "--matrix-root", str(src / "matrix"),
        "--g3-root", str(src / "g3"),
        "--g4-root", str(src / "g4"),
        "--g5-root", str(src / "g5"),
        "--g2-root", str(src / "g2"),
        "--work-dir", str(work),
        "--out", str(out),
    ])
    audit_path = out / "oos_physical_boundary_independent_audit.json"
    run([
        sys.executable, BOUNDARY_AUDIT_V12,
        "--contract", BOUNDARY_CONTRACT,
        "--source-cv-authorization", SOURCE_AUTH,
        "--source-verification", str(sv),
        "--package-dir", str(out),
        "--out", str(audit_path),
    ])

    outputs = bc["fingerprint_basis"]["outputs"]
    expected = {outputs[k] for k in ["features", "market", "execution_state", "lifecycle", "manifest", "source_verification", "independent_audit", "hashes"]}
    have = {p.name for p in out.iterdir() if p.is_file()}
    assert have == expected, (have, expected)
    manifest = load(out / outputs["manifest"])
    audit = load(out / outputs["independent_audit"])
    ready = manifest["runtime_candidate_path_readiness"]
    assert manifest["status"] == "PHYSICALLY_OOS_ONLY_PRE_PREDICTION_NON_LABEL"
    assert manifest["boundary_implementation"] == "V1_2_LIFECYCLE_AWARE_CANDIDATE_READINESS"
    assert ready["entry_lifecycle_inactive_rows"] == 52
    assert ready["exit_lifecycle_inactive_rows"] == 1217
    for k, v in ready.items():
        if k not in {"candidate_rows", "entry_lifecycle_inactive_rows", "exit_lifecycle_inactive_rows"}:
            assert int(v) == 0, (k, v)
    assert audit["pass"] is True and audit["failed_checks"] == []
    assert audit["oos_prediction_executed"] is False
    assert audit["oos_label_value_read"] is False
    assert audit["authorization_consumed"] is False
    assert audit["final_lockbox_accessed"] is False
    final_hashes = {
        p.name: sha256_file(p)
        for p in sorted(out.iterdir())
        if p.is_file() and p.name != outputs["hashes"]
    }
    (out / outputs["hashes"]).write_text(json.dumps(final_hashes, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    assert set(final_hashes) == expected - {outputs["hashes"]}

    shutil.rmtree(src)
    shutil.rmtree(work)
    assert not src.exists() and not work.exists()
    assert not (root / "model").exists()
    print(json.dumps({
        "physical_boundary": "PASS_V1_2_LIFECYCLE_AWARE",
        "entry_lifecycle_inactive_rows": 52,
        "exit_lifecycle_inactive_rows": 1217,
        "authorization_consumed": False,
        "oos_prediction_executed": False,
        "oos_label_value_read": False,
        "model_loaded": False,
        "final_lockbox_accessed": False,
    }, sort_keys=True))
    return 0


def execute():
    verify_frozen_authority()
    verify_request(True)
    sha = os.environ["GITHUB_SHA"]
    assert os.environ.get("EXECUTION_HEAD") == sha
    root = Path("build")
    boundary_root = root / "oos-boundary"
    assert boundary_root.is_dir()
    assert not (root / "oos-boundary-sources").exists()
    assert not (root / "oos-boundary-work").exists()

    model_dir = root / "model"
    out = root / "oos"
    work = root / "oos-work"
    veto = root / "runtime-veto"
    model_dir.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    veto.mkdir(parents=True, exist_ok=True)
    download_artifact(MODEL_AID, MODEL_ZIP_SHA, root / "model.zip", model_dir)
    model = model_dir / "model.pkl"
    preprocess = model_dir / "final_preprocess_manifest.json"
    refit = model_dir / "final_refit_execution_manifest.json"
    assert sha256_file(model) == MODEL_SHA
    assert sha256_file(preprocess) == PREPROCESS_SHA
    assert sha256_file(refit) == REFIT_MANIFEST_SHA
    assert subprocess.check_output(["git", "hash-object", CORE_PATH], text=True).strip() == CORE_BLOB
    assert not (root / "oos-boundary-sources").exists()

    run([
        sys.executable, CORE_PATH,
        "--physical-boundary", str(boundary_root),
        "--boundary-contract", BOUNDARY_CONTRACT,
        "--model", str(model),
        "--preprocess", str(preprocess),
        "--authorization", OOS_AUTH,
        "--execution-contract", EXEC_CONTRACT,
        "--source-cv-authorization", SOURCE_AUTH,
        "--accepted-state", ACCEPTED_STATE,
        "--work-dir", str(work),
        "--out", str(out),
        "--execution-head", sha,
    ])
    run([
        sys.executable, ALPHA_AUDIT,
        "--physical-boundary", str(boundary_root),
        "--boundary-contract", BOUNDARY_CONTRACT,
        "--source-cv-authorization", SOURCE_AUTH,
        "--model", str(model),
        "--preprocess", str(preprocess),
        "--authorization", OOS_AUTH,
        "--execution-contract", EXEC_CONTRACT,
        "--predictions", str(out / "oos_predictions.parquet"),
        "--labels", str(work / "oos_labels.parquet"),
        "--evaluation", str(work / "oos_evaluation_rows.parquet"),
        "--execution-dir", str(out),
        "--execution-head", sha,
        "--out", str(out / "oos_independent_audit.json"),
    ])
    run([
        sys.executable, RUNTIME_RUN_V11,
        "--contract", RUNTIME_CONTRACT,
        "--boundary-contract", BOUNDARY_CONTRACT,
        "--physical-boundary", str(boundary_root),
        "--predictions", str(out / "oos_predictions.parquet"),
        "--out", str(veto),
    ])
    run([
        sys.executable, RUNTIME_AUDIT_V11,
        "--contract", RUNTIME_CONTRACT,
        "--boundary-contract", BOUNDARY_CONTRACT,
        "--physical-boundary", str(boundary_root),
        "--predictions", str(out / "oos_predictions.parquet"),
        "--runtime-dir", str(veto),
        "--out", str(veto / "oos_runtime_veto_independent_audit.json"),
    ])

    aa = load(out / "oos_independent_audit.json")
    am = load(out / "oos_execution_manifest.json")
    ac = load(out / "authorization_consumption.json")
    ag = load(out / "oos_gate_result.json")
    vs = load(veto / "oos_runtime_veto_summary.json")
    va = load(veto / "oos_runtime_veto_independent_audit.json")
    assert aa["pass"] is True and aa["failed_checks"] == []
    assert am["authorization_consumed"] is True
    assert am["fit_executed"] is False and am["lockbox_accessed"] is False
    assert ac["status"] == "CONSUMED" and ac["execution_head"] == sha
    assert ac["lockbox_accessed"] is False
    assert va["pass"] is True and va["failed_checks"] == []
    assert va["oos_outcome_values_read"] is False
    assert va["fit_retrain_tune_reselect_executed"] is False
    assert va["final_lockbox_accessed"] is False
    combined = bool(ag["status"] == "PASS" and vs["gate_pass"] is True)
    assert not (out / "lockbox_predictions.parquet").exists()
    assert not (veto / "oos_labels.parquet").exists()
    print(json.dumps({
        "alpha_gate_status": ag["status"],
        "runtime_veto_gate_status": vs["status"],
        "runtime_veto_gate_pass": vs["gate_pass"],
        "combined_business_promotion_gate": combined,
        "authorization_consumed": True,
        "final_lockbox_accessed": False,
        "execution_head": sha,
    }, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["static", "reserve", "boundary", "execute"], required=True)
    a = ap.parse_args()
    if a.mode == "static":
        return static_self_test()
    if a.mode == "reserve":
        return reserve()
    if a.mode == "boundary":
        return boundary()
    return execute()


if __name__ == "__main__":
    raise SystemExit(main())
