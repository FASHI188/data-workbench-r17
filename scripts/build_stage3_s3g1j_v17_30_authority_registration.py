#!/usr/bin/env python3
import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DEFAULT = ROOT / "build" / "v17_30_authority_registration"

V29 = {
    "generation": "V17.29",
    "run": 31389854868,
    "head_sha": "22fa37064eeb8a49ad5292dd2be48bd7b674c673",
    "artifact_id": 9063271903,
    "artifact": "stage3-s3g1j-v17-29-full-final",
    "artifact_digest": "sha256:71a4daa6c8372f3d64080b5fa5b787914292d889da7051de699eb6610189c726",
    "document_rows": 121354,
    "numeric_observations": 1051820,
    "document_error_count": 1364,
    "unresolved_tie_count": 1281,
    "verdict": "FAIL_CLOSED",
}
V30 = {
    "generation": "V17.30",
    "execution_pr": 126,
    "execution_run": 31480775354,
    "execution_head_sha": "71b19f55648bdef6ded5e40335da9b6f09a8d44c",
    "acceptance_pr": 127,
    "acceptance_merge_commit": "121972a404c8773963477907c8b9abd3a4f5160b",
    "governance_pr": 128,
    "run": 31518370789,
    "head_sha": "a18b81a9f38692533d0427f4a5b50767abf1a7c8",
    "artifact_id": 9112098872,
    "artifact": "stage3-s3g1j-v17-30-full-final-preacceptance",
    "artifact_digest": "sha256:706c6dd7252a64fd5c2956df6c594b5c91de29f02ca7d0553fa932017e8867ba",
    "document_count": 121354,
    "numeric_observation_count": 1051826,
    "document_error_count": 1362,
    "unresolved_tie_count": 1279,
    "changed_announcement_ids": ["1223347318", "1223407043"],
    "target_numeric_rows": 6,
    "existing_numeric_semantic_sha256": "0457d2c4601e7356c842eebfab5b6b52e851da26f2508f8c38d3833f9ef6fa51",
    "target_numeric_semantic_sha256": "d572927ca89867571700809b554a0d9160951b06af26d3b670b6b662a29e535a",
}

FILES = {
    "runtime": ROOT / "governance/stage3_s3g1j_runtime_manifest.json",
    "activation": ROOT / "governance/stage3_workflow_activation_manifest.json",
    "authority": ROOT / "governance/stage3_authority_map.json",
    "lock": ROOT / "config/stage3_final_lock.json",
    "status": ROOT / "data/project_status.json",
}


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def dump(obj, p):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def assert_old(runtime, activation, authority, lock, status):
    assert runtime["schema_version"] == 14
    assert runtime["formal_runtime"]["runtime_generation"] == "V17.30"
    assert runtime["full_basis_last_completed_final"]["generation"] == "V17.29"
    assert runtime["full_basis_last_completed_final"]["run"] == V29["run"]
    assert runtime["next_full_basis_required"]["generation"] == "V17.30"
    assert runtime["next_full_basis_required"]["status"] == "REQUIRED_NOT_STARTED"
    assert activation["schema_version"] == 16
    assert activation["accepted_production_runtime"]["last_completed_full_basis_generation"] == "V17.29"
    assert authority["schema_version"] == 7
    assert authority["authoritative_components"]["S3G1J_FINANCIAL_RAW_VALUES"]["last_completed_full_basis_generation"] == "V17.29"
    assert lock["version"] == "V3.3.14-stage3-final-lock"
    assert lock["required_gates"]["S3G1J_FINANCIAL_RAW_VALUES"]["last_completed_full_basis_generation"] == "V17.29"
    assert status["schema_version"] == 7
    assert status["stage3"]["s3g1j"]["last_completed_full_basis_generation"] == "V17.29"
    assert status["stage3"]["status"] == "NOT_READY"
    assert status["stage4_unlocked"] is False
    assert status["alpha_training_allowed"] is False
    assert status["live_signal_allowed"] is False


def v30_acceptance():
    return {
        "generation": "V17.30",
        "authority_scope": "LATEST_COMPLETED_FULL_BASIS",
        "execution_pr": 126,
        "execution_pr_merged": False,
        "execution_pr_closed_without_merge": True,
        "acceptance_pr": 127,
        "acceptance_merge_commit": V30["acceptance_merge_commit"],
        "governance_pr": 128,
        "run": V30["run"],
        "head_sha": V30["head_sha"],
        "artifact_id": V30["artifact_id"],
        "artifact": V30["artifact"],
        "artifact_digest": V30["artifact_digest"],
        "execution_pass": True,
        "source_shard_verify_pass": True,
        "document_non_regression_pass": True,
        "numeric_non_regression_pass": True,
        "promotion_gold_equality_pass": True,
        "real_source_recheck_pass": True,
        "independent_artifact_recheck_pass": True,
        "document_count": V30["document_count"],
        "numeric_observation_count": V30["numeric_observation_count"],
        "document_error_count": V30["document_error_count"],
        "unresolved_tie_count": V30["unresolved_tie_count"],
        "target_document_count": 2,
        "target_numeric_rows": 6,
        "unexpected_document_regression_count": 0,
        "existing_numeric_semantic_sha256": V30["existing_numeric_semantic_sha256"],
        "target_numeric_semantic_sha256": V30["target_numeric_semantic_sha256"],
        "final_data_verdict": "FAIL_CLOSED",
    }


def build_runtime(src):
    x = copy.deepcopy(src)
    old_current = copy.deepcopy(x["full_basis_last_completed_final"])
    old_prev = copy.deepcopy(x["previous_last_completed_full_basis_final"])
    old_prev2 = copy.deepcopy(x["previous_full_basis_final"])
    old_hist = copy.deepcopy(x["historical_full_basis_final"])
    x["schema_version"] = 15
    x["scope"] = "V17.30 is both the formal S3G1J runtime and the latest completed machine-accepted 64-shard full-basis authority. Execution and non-regression pass, while the data verdict remains FAIL_CLOSED and S3G1J remains a pending Stage3 final gate."
    x["previous_manifest"] = {
        "schema_version": 14,
        "source_integration_sha": V30["acceptance_merge_commit"],
        "formal_runtime_generation": "V17.30",
        "full_basis_generation": "V17.29",
        "full_basis_execution_pending": True,
        "history_retention": "Git history plus immutable run IDs, artifact digests and governance evidence manifests",
    }
    cur = x["current_production_authority"]
    cur["status"] = "RUNTIME_AND_FULL_BASIS_ACCEPTED_DATA_FAIL_CLOSED"
    cur["full_basis_evidence_manifest"] = "governance/stage3_s3g1j_v17_30_full_final.json"
    cur["full_basis_acceptance"] = v30_acceptance()
    cur["runtime_promotion"]["full_basis_execution_pending"] = False
    cur["runtime_promotion"].pop("expected_full_basis_values_are_not_production_acceptance", None)
    cur["runtime_promotion"]["full_basis_execution_accepted"] = True
    x["v17_30_exact_source_gates"]["full_basis_evidence_manifest"] = "governance/stage3_s3g1j_v17_30_full_final.json"
    for f in ["governance/stage3_s3g1j_v17_30_full_final.json", "tests/test_stage3_v17_30_full_final_evidence.py"]:
        if f not in x["formal_runtime_files"]:
            x["formal_runtime_files"].append(f)
    x["full_basis_last_completed_final"] = {
        "generation": "V17.30", "run": V30["run"], "head_sha": V30["head_sha"],
        "artifact_id": V30["artifact_id"], "artifact": V30["artifact"], "artifact_digest": V30["artifact_digest"],
        "canonical_report_version_moments": 121354, "document_rows": 121354, "numeric_observations": 1051826,
        "document_error_count": 1362, "unresolved_tie_count": 1279,
        "changed_announcement_ids": V30["changed_announcement_ids"], "target_numeric_rows": 6,
        "unexpected_regression_count": 0, "existing_numeric_semantic_sha256": V30["existing_numeric_semantic_sha256"],
        "target_numeric_semantic_sha256": V30["target_numeric_semantic_sha256"],
        "execution_verdict": "PASS", "verdict": "FAIL_CLOSED"
    }
    old_current["retained"] = True
    old_prev["retained"] = True
    old_prev2["retained"] = True
    old_hist["retained"] = True
    x["previous_last_completed_full_basis_final"] = old_current
    x["previous_full_basis_final"] = old_prev
    x["historical_full_basis_final"] = old_prev2
    x["earlier_historical_full_basis_final"] = old_hist
    x["next_full_basis_required"] = {"generation": None, "status": "NONE_CURRENT_RUNTIME_ACCEPTED", "current_runtime_generation": "V17.30", "current_full_basis_generation": "V17.30"}
    x["production_final_status"] = "RUNTIME_AND_FULL_BASIS_ACCEPTED_DATA_FAIL_CLOSED"
    x["remaining_final_requirement"] = "Resolve or formally retain the remaining 1,362 document errors and 1,279 unresolved ties, complete S3G4 full final, Stage3 final freeze, reproducibility closure and freshness. Full-basis execution acceptance is not an S3G1J data PASS."
    return x


def build_activation(src):
    x = copy.deepcopy(src)
    x["schema_version"] = 17
    x["status"] = "ACTIVE_WORKFLOW_SET_WITH_V17_30_RUNTIME_AND_FULL_BASIS_ACCEPTED_DATA_FAIL_CLOSED"
    x["policy"] = "Only long-lived read-only safety, authority, runtime and accepted-evidence contracts remain active. Historical accepted evidence remains append-only across runtime generations. V17.30 is both the formal runtime and latest completed full-basis authority; execution acceptance does not equal an S3G1J data PASS."
    x["previous_activation_manifest"] = {"schema_version": 16, "source_integration_sha": V30["acceptance_merge_commit"], "accepted_runtime_generation": "V17.30", "last_completed_full_basis_generation": "V17.29", "v17_30_full_basis_execution_pending": True}
    wf = ".github/workflows/stage3-s3g1j-v17-30-full-final-evidence-contract.yml"
    if wf not in x["active_stage3_workflows"]:
        x["active_stage3_workflows"].append(wf)
    a = x["accepted_production_runtime"]
    a["status"] = "RUNTIME_AND_FULL_BASIS_ACCEPTED_DATA_FAIL_CLOSED"
    a["runtime_manifest_schema"] = 15
    a["full_basis_execution_pending"] = False
    for k in list(a):
        if k.startswith("next_full_basis_") or k.startswith("expected_next_") or k == "expected_values_are_not_production_acceptance":
            a.pop(k, None)
    a.update({
        "last_completed_full_basis_generation": "V17.30", "last_completed_full_basis_run": V30["run"],
        "last_completed_full_basis_head_sha": V30["head_sha"], "last_completed_full_basis_artifact_id": V30["artifact_id"],
        "last_completed_full_basis_artifact": V30["artifact"], "last_completed_full_basis_artifact_digest": V30["artifact_digest"],
        "last_completed_canonical_version_count": 121354, "last_completed_document_count": 121354,
        "last_completed_numeric_observation_count": 1051826, "last_completed_document_error_count": 1362,
        "last_completed_unresolved_tie_count": 1279, "execution_verdict": "PASS_LAST_COMPLETED_BASIS_V17_30",
        "data_verdict": "FAIL_CLOSED", "production_final_status": "RUNTIME_AND_FULL_BASIS_ACCEPTED_DATA_FAIL_CLOSED"
    })
    w = x["accepted_v17_30_runtime_wrapper"]
    w["full_basis_execution_pending"] = False
    w.pop("expected_next_basis_is_not_production_acceptance", None)
    w["full_basis_execution_accepted"] = True
    v29 = x.get("accepted_v17_29_full_basis_evidence")
    if v29:
        v29["last_completed_full_basis_authority"] = False
        v29["historical_full_basis_authority_retained"] = True
    x["accepted_v17_30_full_basis_evidence"] = {
        "evidence_manifest": "governance/stage3_s3g1j_v17_30_full_final.json",
        "evidence_contract_workflow": wf,
        "execution_pr": 126, "execution_pr_closed_without_merge": True,
        "acceptance_pr": 127, "acceptance_merge_commit": V30["acceptance_merge_commit"], "governance_pr": 128,
        "source_run": V30["execution_run"], "source_head_sha": V30["execution_head_sha"], "source_shard_count": 64,
        "run": V30["run"], "head_sha": V30["head_sha"], "artifact_id": V30["artifact_id"], "artifact": V30["artifact"], "artifact_digest": V30["artifact_digest"],
        "execution_pass": True, "source_shard_verify_pass": True, "document_non_regression_pass": True,
        "numeric_non_regression_pass": True, "promotion_gold_equality_pass": True, "real_source_recheck_pass": True,
        "independent_artifact_recheck_pass": True, "canonical_version_count": 121354, "document_count": 121354,
        "numeric_observation_count": 1051826, "document_error_count": 1362, "unresolved_tie_count": 1279,
        "target_document_count": 2, "target_numeric_rows": 6, "unexpected_regression_count": 0,
        "final_data_verdict": "FAIL_CLOSED", "stage3_status": "NOT_READY", "last_completed_full_basis_authority": True,
        "historical_runtime_generation_retained": True, "evidence_contract_active": True
    }
    return x


def build_authority(src):
    x = copy.deepcopy(src)
    x["schema_version"] = 8
    s = x["authoritative_components"]["S3G1J_FINANCIAL_RAW_VALUES"]
    s["last_completed_full_basis_generation"] = "V17.30"
    s["full_basis_evidence_manifest"] = "governance/stage3_s3g1j_v17_30_full_final.json"
    s.update({
        "source_execution_pr": 126, "source_execution_pr_merged": False, "source_execution_pr_closed_without_merge": True,
        "source_execution_run_id": V30["execution_run"], "source_execution_head_sha": V30["execution_head_sha"],
        "accepted_execution_pr": 127, "full_basis_governance_closure_pr": 128,
        "accepted_head_sha": V30["head_sha"], "accepted_basis_merge_commit": V30["acceptance_merge_commit"],
        "accepted_run_id": V30["run"], "accepted_artifact_id": V30["artifact_id"], "accepted_artifact": V30["artifact"],
        "accepted_artifact_digest": V30["artifact_digest"], "document_count": 121354, "numeric_observation_count": 1051826,
        "document_error_count": 1362, "unresolved_tie_count": 1279, "changed_announcement_ids": V30["changed_announcement_ids"],
        "target_numeric_rows": 6, "unexpected_document_regression_count": 0,
        "existing_numeric_semantic_sha256": V30["existing_numeric_semantic_sha256"],
        "target_numeric_semantic_sha256": V30["target_numeric_semantic_sha256"],
        "execution_pass": True, "document_non_regression_pass": True, "numeric_non_regression_pass": True,
        "promotion_gold_equality_pass": True, "real_source_recheck_pass": True, "independent_artifact_recheck_pass": True,
        "status": "FORMAL_RUNTIME_V17_30_FULL_BASIS_V17_30_LAST_COMPLETED_DATA_FAIL_CLOSED",
        "data_verdict": "FAIL_CLOSED", "final_gate": False,
        "final_requirement": "Resolve or formally retain residual errors/ties and complete S3G4, freshness, reproducibility closure and Stage3 final freeze."
    })
    for k in list(s):
        if k.startswith("next_full_basis_") or k.startswith("expected_next_") or k == "expected_values_are_not_production_acceptance":
            s.pop(k, None)
    s["previous_full_basis_authority"] = copy.deepcopy(V29)
    prs = x["non_merge_evidence_prs"]
    if 126 not in prs: prs.append(126)
    x["current_s3g1j_execution_pr"] = 126
    x["current_s3g1j_governance_pr"] = 128
    return x


def build_lock(src):
    x = copy.deepcopy(src)
    x["version"] = "V3.3.15-stage3-final-lock"
    s = x["required_gates"]["S3G1J_FINANCIAL_RAW_VALUES"]
    s.update({
        "last_completed_full_basis_generation": "V17.30", "full_basis_evidence": "governance/stage3_s3g1j_v17_30_full_final.json",
        "source_execution_pr": 126, "source_execution_pr_closed_without_merge": True,
        "source_execution_run_id": V30["execution_run"], "source_execution_head_sha": V30["execution_head_sha"],
        "acceptance_pr": 127, "acceptance_merge_commit": V30["acceptance_merge_commit"], "full_basis_governance_pr": 128,
        "run_id": V30["run"], "head_sha": V30["head_sha"], "artifact_id": V30["artifact_id"],
        "artifact": V30["artifact"], "artifact_digest": V30["artifact_digest"],
        "execution_pass": True, "document_non_regression_pass": True, "numeric_non_regression_pass": True,
        "promotion_gold_equality_pass": True, "real_source_recheck_pass": True, "independent_artifact_recheck_pass": True,
        "data_verdict": "FAIL_CLOSED", "final_gate_pass": False, "document_count": 121354,
        "numeric_observation_count": 1051826, "document_error_count": 1362, "unresolved_tie_count": 1279,
        "existing_numeric_semantic_sha256": V30["existing_numeric_semantic_sha256"], "target_numeric_semantic_sha256": V30["target_numeric_semantic_sha256"]
    })
    for k in list(s):
        if k.startswith("next_full_basis_") or k.startswith("expected_next_") or k == "expected_values_are_not_production_acceptance": s.pop(k, None)
    s["previous_full_basis_authority"] = copy.deepcopy(V29)
    x["interpretation"] = "V17.30 is the formal runtime and latest completed accepted 64-shard full-basis authority at 1,051,826 numeric observations / 1,362 document errors / 1,279 unresolved ties. S3G1J data remains FAIL_CLOSED; Stage3 remains NOT_READY."
    return x


def build_status(src):
    x = copy.deepcopy(src)
    x["schema_version"] = 8
    s = x["stage3"]["s3g1j"]
    s["runtime_status"] = "RUNTIME_AND_FULL_BASIS_ACCEPTED_DATA_FAIL_CLOSED"
    s["last_completed_full_basis_generation"] = "V17.30"
    s["status"] = "RUNTIME_V17_30_FULL_BASIS_V17_30_LAST_COMPLETED_DATA_FAIL_CLOSED"
    s.update({
        "full_basis_evidence": "governance/stage3_s3g1j_v17_30_full_final.json", "source_execution_pr": 126,
        "source_execution_pr_closed_without_merge": True, "source_execution_run_id": V30["execution_run"],
        "source_execution_head_sha": V30["execution_head_sha"], "acceptance_pr": 127,
        "acceptance_merge_commit": V30["acceptance_merge_commit"], "full_basis_governance_pr": 128,
        "accepted_run_id": V30["run"], "accepted_head_sha": V30["head_sha"], "accepted_artifact_id": V30["artifact_id"],
        "accepted_artifact_digest": V30["artifact_digest"], "document_count": 121354,
        "numeric_observation_count": 1051826, "document_error_count": 1362, "unresolved_tie_count": 1279,
        "execution_pass": True, "document_non_regression_pass": True, "numeric_non_regression_pass": True,
        "promotion_gold_equality_pass": True, "real_source_recheck_pass": True, "independent_artifact_recheck_pass": True,
        "existing_numeric_semantic_sha256": V30["existing_numeric_semantic_sha256"],
        "target_numeric_semantic_sha256": V30["target_numeric_semantic_sha256"], "data_verdict": "FAIL_CLOSED", "final_gate_pass": False,
        "previous_full_basis_authority": copy.deepcopy(V29)
    })
    for k in list(s):
        if k.startswith("next_full_basis_") or k.startswith("expected_next_") or k == "expected_values_are_not_production_acceptance": s.pop(k, None)
    x["stage3"]["reason"] = "Stage3 does not yet have a final all-gates PASS manifest on main. V17.30 is now the latest completed accepted S3G1J full basis but still has 1,362 document errors and 1,279 unresolved ties; S3G4 remains pending and freshness is stale."
    r = x["reproducibility"]
    r["s3g1j_last_completed_full_basis_generation"] = "V17.30"
    r["s3g1j_fresh_v17_30_full_basis_execution_started"] = True
    r["s3g1j_fresh_v17_30_full_basis_execution_accepted"] = True
    r.pop("s3g1j_full_basis_execution_pass_last_completed_v17_29", None)
    r["s3g1j_full_basis_execution_pass_last_completed_v17_30"] = True
    r["reason"] = "The V17.30 runtime wrapper and fresh V17.30 full-basis execution are machine accepted and reproducible. S3G1J data remains FAIL_CLOSED and S3G4/freshness/final freeze remain pending."
    x["notes"] = [
        "V17.30 is both the formal runtime and latest completed full-basis authority; this does not unlock Stage4.",
        "The latest completed accepted basis is V17.30 at 1,051,826 numeric / 1,362 errors / 1,279 ties / FAIL_CLOSED.",
        "V17.29, V17.28, V17.27 and V17.26 accepted evidence remains immutable and append-only.",
        "Any missing, stale, contradictory, or unverifiable readiness evidence is fail-closed."
    ]
    return x


def validate(r, a, m, l, s):
    assert r["schema_version"] == 15 and r["full_basis_last_completed_final"]["generation"] == "V17.30"
    assert r["previous_last_completed_full_basis_final"]["generation"] == "V17.29"
    assert r["previous_full_basis_final"]["generation"] == "V17.28"
    assert r["historical_full_basis_final"]["generation"] == "V17.27"
    assert r["earlier_historical_full_basis_final"]["generation"] == "V17.26"
    assert a["schema_version"] == 17 and a["accepted_v17_30_full_basis_evidence"]["last_completed_full_basis_authority"] is True
    assert a["accepted_v17_29_full_basis_evidence"]["last_completed_full_basis_authority"] is False
    assert m["schema_version"] == 8 and m["current_s3g1j_execution_pr"] == 126 and m["current_s3g1j_governance_pr"] == 128
    assert l["required_gates"]["S3G1J_FINANCIAL_RAW_VALUES"]["last_completed_full_basis_generation"] == "V17.30"
    assert s["stage3"]["s3g1j"]["last_completed_full_basis_generation"] == "V17.30"
    assert s["stage3"]["status"] == "NOT_READY" and not s["stage4_unlocked"] and not s["alpha_training_allowed"] and not s["live_signal_allowed"]
    for obj in (r, a, m, l, s):
        text = json.dumps(obj, ensure_ascii=False)
        assert '"ocr_enabled": true' not in text
        assert '"fuzzy_alias_matching_enabled": true' not in text
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args()
    src = {k: load(p) for k,p in FILES.items()}
    assert_old(src["runtime"], src["activation"], src["authority"], src["lock"], src["status"])
    out = {
        "stage3_s3g1j_runtime_manifest.json": build_runtime(src["runtime"]),
        "stage3_workflow_activation_manifest.json": build_activation(src["activation"]),
        "stage3_authority_map.json": build_authority(src["authority"]),
        "stage3_final_lock.json": build_lock(src["lock"]),
        "project_status.json": build_status(src["status"]),
    }
    validate(out["stage3_s3g1j_runtime_manifest.json"], out["stage3_workflow_activation_manifest.json"], out["stage3_authority_map.json"], out["stage3_final_lock.json"], out["project_status.json"])
    for name,obj in out.items(): dump(obj, args.out_dir / name)
    summary = {"gate":"S3G1J_V17_30_APPEND_ONLY_AUTHORITY_REGISTRATION_BUILD", "pass": True, "latest_completed_full_basis":"V17.30", "data_verdict":"FAIL_CLOSED", "stage3":"NOT_READY", "files": sorted(out)}
    dump(summary, args.out_dir / "registration_build_summary.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
