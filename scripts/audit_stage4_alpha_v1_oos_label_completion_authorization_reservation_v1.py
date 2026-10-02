#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path

R = Path(__file__).resolve().parents[1]
RES_FP = "4c91f96fee0970a25ecaef673419a7c5e02c02b72591e2aafeac6ee594f38558"
PREREG_FP = "0e9b79a406e3a7789ade5b93878cd4276c5f424b0f0e9e4906048b9254e4cac3"
IMPL_FP = "a9addd6eefc82737e5a39c7828dc9b68a5d4336e2ee3e8ebeaeee1d628014045"
IMPL_ACCEPT_FP = "60522faad23985ffd5aa643be8af528673b6db8026874ef0565d2a8d30fcdaa3"
ORIG_AUTH_FP = "d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d"
PRED_SHA = "66a039aa76e4b1962049e3e0d41a43fb1f6c626d934a552f871f91bd27fe01da"
CONSUMPTION = "FIRST_SUCCESSFUL_READ_OF_ANY_OOS_MARKET_VALUE_USED_FOR_LABEL_MATERIALIZATION_OR_FIRST_SUCCESSFUL_READ_OF_ANY_OOS_LABEL_VALUE_WHICHEVER_OCCURS_FIRST"

SRC = {
    "scripts/run_stage4_alpha_v1_oos_label_completion.py": "7fe790864be6d324f4571f57ed23213920605a48d9b4415849e12c37cdb8f2d6",
    "scripts/stage4_alpha_v1_label_materialization.py": "97442670c4f5e86e541c4730549c454c07507d38459d56c742211cc4c2103ab0",
    "scripts/stage4_alpha_v1_alpha_evaluation.py": "4c4e7e1674ef64dd6e68fde65ba58d3954f2b4262e476863a21ac600fa8b68a3",
}
BLOBS = {
    "scripts/run_stage4_alpha_v1_runtime_veto_v1_1.py": "26c7371fa886cc5031dddf031c7317c4ad9bdc57",
    "scripts/audit_stage4_alpha_v1_runtime_veto_v1_1.py": "35f6b388564993241e364ea3b332a9d16eca19c5",
    "governance/stage4_alpha_v1_runtime_veto_contract_v1_1.json": "b6668800143249ccf29d15a7f5c87f1a21905b98",
    "governance/stage4_alpha_v1_oos_physical_boundary_contract.json": "6b4e85cf495ff2f43b076309b10d100b369af140",
}

def load(path: str):
    return json.loads((R / path).read_text(encoding="utf-8"))

def canonical_hash(x) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

def sha256(path: str) -> str:
    return hashlib.sha256((R / path).read_bytes()).hexdigest()

def git_blob(path: str) -> str:
    return subprocess.check_output(["git", "hash-object", str(R / path)], text=True).strip()

def main() -> int:
    auth = load("governance/stage4_alpha_v1_oos_label_completion_authorization_reservation_v1.json")
    audit = load("governance/stage4_alpha_v1_oos_label_completion_authorization_reservation_audit_v1.json")
    state = load("governance/accepted_project_state.json")
    modules = load("governance/project_module_index.json")
    prereg = load("governance/stage4_alpha_v1_oos_label_completion_preregistration_v1_3_supersession.json")
    impl_accept = load("governance/stage4_alpha_v1_oos_label_completion_implementation_acceptance.json")
    consumed = load("governance/stage4_alpha_v1_oos_validation_consumed_incomplete_evidence.json")
    b = auth["fingerprint_basis"]
    checks = {}
    def ck(name, value):
        checks[name] = bool(value)

    ck("reservation_fingerprint", auth["fingerprint"] == RES_FP and canonical_hash(b) == RES_FP)
    ck("reservation_status", auth["status"] == "FROZEN_SINGLE_USE_OOS_LABEL_COMPLETION_AUTHORIZATION_RESERVATION_UNARMED_NO_OOS_ACCESS")
    ck("prereg_bound", prereg["fingerprint"] == PREREG_FP and b["preregistration_fingerprint"] == PREREG_FP)
    ck("implementation_bound", b["implementation_fingerprint"] == IMPL_FP and impl_accept["fingerprint"] == IMPL_ACCEPT_FP and b["implementation_acceptance_fingerprint"] == IMPL_ACCEPT_FP)
    ck("consumed_history_preserved", consumed["authorization"]["fingerprint"] == ORIG_AUTH_FP and consumed["authorization"]["consumed"] is True and consumed["authorization"]["reusable"] is False and b["original_oos_authorization_fingerprint"] == ORIG_AUTH_FP and b["original_authorization_consumed"] is True and b["original_authorization_reusable"] is False)
    ck("immutable_prediction", b["prediction_artifact_id"] == 10142949262 and b["predictions_sha256"] == PRED_SHA and b["prediction_rows"] == 1515811 and b["sole_score_input"] is True)
    ck("immutable_boundary", b["physical_boundary_artifact_id"] == 10142948546 and b["physical_boundary_candidate_rows"] == 1453359 and b["post_oos_rows_observed"] == 0 and b["broad_source_redownload_forbidden"] is True and b["physical_boundary_rebuild_forbidden"] is True)
    ck("source_hashes", b["implementation_sources"] == SRC and all(sha256(k) == v for k, v in SRC.items()))
    ck("frozen_runtime_blobs", b["frozen_runtime_dependencies"] == BLOBS and all(git_blob(k) == v for k, v in BLOBS.items()))
    ck("unarmed", b["authorized_execution_head"] is None and b["authorization_armed"] is False and b["armed_runs_remaining"] == 0)
    ck("single_use_future", b["max_label_completion_runs"] == 1 and b["consumption_event"] == CONSUMPTION and b["after_consumption_reexecution_forbidden"] is True)
    ck("authorization_gate_zero_access", b["authorization_pr_oos_artifact_download_allowed"] is False and b["authorization_pr_oos_market_value_read_allowed"] is False and b["authorization_pr_oos_label_value_read_allowed"] is False and b["authorization_pr_prediction_computation_allowed"] is False and b["authorization_pr_model_load_allowed"] is False)
    ck("future_forbidden", b["future_prediction_computation_allowed"] is False and b["model_load_allowed"] is False and b["fit_retrain_tune_reselect_allowed"] is False and b["final_lockbox_access_allowed"] is False and b["live_signal_allowed"] is False and b["main_merge_allowed"] is False and b["authoritative_output_allowed"] is False)
    ck("exact_head_sequence", b["execution_pr_creation_allowed_after_reservation_acceptance"] is True and b["exact_head_execution_pr_required"] is True and b["exact_head_arming_required_before_dispatch"] is True and b["workflow_dispatch_only_for_label_bearing_execution"] is True and b["automatic_pull_request_execution_forbidden"] is True)
    p = state["permissions"]
    ck("state_research_only", state["schema_version"] == 12 and state["status"] == "RESEARCH_ONLY")
    ck("state_execution_pr_only", p["oos_execution_pr_creation_allowed"] is True and p["oos_label_access_allowed"] is False and p["oos_label_bearing_execution_runs_remaining"] == 0)
    ck("state_sensitive_closed", p["model_fit_allowed"] is False and p["development_final_refit_allowed"] is False and p["lockbox_label_access_allowed"] is False and p["live_signal_allowed"] is False and p["main_merge_allowed"] is False and p["authoritative_model_output_allowed"] is False)
    mod = next(x for x in modules["modules"] if x["id"] == "OOS_LABEL_COMPLETION_V1")
    old = next(x for x in modules["modules"] if x["id"] == "OOS_VALIDATION_V1")
    ck("module_index", modules["index_version"] == "V1.9" and mod["status"] == "AUTHORIZATION_RESERVED_UNARMED_NO_OOS_ACCESS" and mod["authorization_reservation_fingerprint"] == RES_FP and mod["authorized_execution_head"] is None and mod["armed_runs_remaining"] == 0 and old["status"] == "CONSUMED_INCOMPLETE_NO_PROMOTION")
    ck("audit_manifest", audit["authorization_fingerprint_expected"] == RES_FP and audit["status"] == "PASS_FOR_GOVERNANCE_ACCEPTANCE_UNARMED_NO_OOS_ACCESS")

    failed = [k for k, v in checks.items() if not v]
    out = {
        "gate": "STAGE4_ALPHA_V1_OOS_LABEL_COMPLETION_AUTHORIZATION_RESERVATION_V1",
        "pass": not failed,
        "reservation_fingerprint": RES_FP,
        "checks": checks,
        "failed_checks": failed,
        "oos_artifact_download_executed": False,
        "oos_market_value_read": False,
        "oos_label_value_read": False,
        "prediction_computation_executed": False,
        "model_loaded": False,
        "authorization_armed": False,
        "armed_runs_remaining": 0,
        "final_lockbox_accessed": False,
        "next_gate": auth["next_gate"],
    }
    print(json.dumps(out, indent=2))
    return 0 if not failed else 2

if __name__ == "__main__":
    raise SystemExit(main())
