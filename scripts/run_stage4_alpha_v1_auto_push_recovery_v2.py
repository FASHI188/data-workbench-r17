#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
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
CORE_PATH = "scripts/run_stage4_alpha_v1_oos_validation_core.py"


def canon(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


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
    subprocess.run([sys.executable, "scripts/run_stage4_alpha_v1_runtime_veto_v1_1.py", "--synthetic-self-test"], check=True)
    subprocess.run([sys.executable, "scripts/audit_stage4_alpha_v1_runtime_veto_v1_1.py", "--synthetic-self-test"], check=True)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["static", "reserve"], required=True)
    a = ap.parse_args()
    return static_self_test() if a.mode == "static" else reserve()


if __name__ == "__main__":
    raise SystemExit(main())
