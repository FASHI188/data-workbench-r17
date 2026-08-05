#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []
    authority = load("governance/stage3_authority_map.json")
    lock = load("config/stage3_final_lock.json")
    project = load("data/project_status.json")
    runtime = load("governance/stage3_s3g1j_runtime_manifest.json")
    activation = load("governance/stage3_workflow_activation_manifest.json")
    evidence = load("governance/stage3_s3g1j_v17_28_full_final.json")
    promotion = load("governance/stage3_s3g1j_v17_28_runtime_promotion.json")

    def req(cond: bool, message: str) -> None:
        if not cond:
            errors.append(message)

    stage2_fp = "f17f7ab63f4532dda635eb7366e7df7bf5497a5ce814410105312bccb53125bb"
    s3g2_sha = "0eb139572865628283f86c981990e59e076d5ef2a978a5967aace90d553e30dd"
    full_digest = "sha256:82375169faada969ceafd4356ab0a2707aa14592d5db090c5d3910863d571c8b"
    semantic_sha = "bcb154cc4d80a81acd409e64dc35c2902a5aeb37726b313df936717caf400672"
    wrapper_digest = "sha256:f8639b4a2eac2d09b16586365b7932d255457ce66aad2484547bb517d0d185a6"

    req(authority.get("schema_version") == 4, "authority map schema must be 4")
    req(authority.get("status") == "INTEGRATION_IN_PROGRESS", "authority status drift")
    req((authority.get("stage2_dependency") or {}).get("fingerprint") == stage2_fp, "authority Stage2 fingerprint drift")
    req(lock.get("version") == "V3.3.11-stage3-final-lock", "Stage3 final-lock version drift")
    req(lock.get("status") == "NOT_READY", "Stage3 final lock must remain NOT_READY")
    req((lock.get("stage2") or {}).get("fingerprint") == stage2_fp, "final lock Stage2 fingerprint drift")
    req(project.get("schema_version") == 4, "project status schema must be 4")
    req(project.get("stage4_unlocked") is False, "project unexpectedly unlocks Stage4")
    req(project.get("alpha_training_allowed") is False, "project unexpectedly allows Alpha training")
    req(project.get("live_signal_allowed") is False, "project unexpectedly allows live signals")
    req(runtime.get("schema_version") == 11, "runtime manifest schema must be 11")
    req(activation.get("schema_version") == 13, "activation manifest schema must be 13")

    unlock = authority.get("project_unlock") or {}
    req(unlock.get("stage4_unlocked") is False, "authority map unlocks Stage4")
    req(unlock.get("alpha_training_allowed") is False, "authority map allows Alpha training")
    req(unlock.get("live_signal_allowed") is False, "authority map allows live signals")

    pending = {"S3G1J_FINANCIAL_RAW_VALUES", "S3G4_EARNINGS_SURPRISE"}
    req(set(lock.get("remaining_unlocked_gates") or []) == pending, "final-lock pending gate set drift")
    req(set((project.get("stage3") or {}).get("pending_final_gates") or []) == pending, "project pending gate set drift")

    components = authority.get("authoritative_components") or {}
    for gate in pending:
        req(gate in components, f"authority missing pending gate {gate}")
        req((components.get(gate) or {}).get("final_gate") is False, f"pending gate {gate} incorrectly final")

    g1j = components.get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(authority.get("current_s3g1j_execution_pr") == 97, "current S3G1J acceptance PR must be #97")
    req(authority.get("current_s3g1j_governance_pr") == 98, "current S3G1J governance PR must be #98")
    req(96 in set(authority.get("non_merge_evidence_prs") or []), "execution PR #96 must remain non-merge evidence")
    req(g1j.get("formal_runtime_generation") == "V17.28", "S3G1J runtime drift")
    req(g1j.get("runtime_wrapper_pr") == 94, "wrapper PR drift")
    req(g1j.get("runtime_wrapper_run_id") == 30978715158, "wrapper run drift")
    req(g1j.get("runtime_wrapper_artifact_digest") == wrapper_digest, "wrapper digest drift")
    req(g1j.get("runtime_contract_pass") is True, "runtime contract not PASS")
    req(g1j.get("last_completed_full_basis_generation") == "V17.28", "latest full basis must be V17.28")
    req(g1j.get("source_execution_pr") == 96, "source execution PR drift")
    req(g1j.get("source_execution_pr_merged") is False, "source execution PR must not merge")
    req(g1j.get("source_execution_run_id") == 30981127011, "source execution run drift")
    req(g1j.get("accepted_execution_pr") == 97, "acceptance PR drift")
    req(g1j.get("governance_closure_pr") == 98, "governance PR drift")
    req(g1j.get("accepted_run_id") == 30997260730, "accepted run drift")
    req(g1j.get("accepted_artifact_id") == 8927455692, "artifact ID drift")
    req(g1j.get("accepted_artifact_digest") == full_digest, "artifact digest drift")
    req(g1j.get("document_count") == 121354, "document count drift")
    req(g1j.get("numeric_observation_count") == 1051799, "numeric count drift")
    req(g1j.get("document_error_count") == 1371, "document error count drift")
    req(g1j.get("unresolved_tie_count") == 1288, "unresolved tie count drift")
    req(g1j.get("changed_announcement_ids") == ["1207621057", "1209825769"], "changed target set drift")
    req(g1j.get("target_numeric_rows") == 6, "target numeric count drift")
    req(g1j.get("unexpected_document_regression_count") == 0, "unexpected document regression")
    req(g1j.get("existing_numeric_semantic_sha256") == semantic_sha, "existing numeric semantic SHA drift")
    req(g1j.get("execution_pass") is True, "execution not PASS")
    req(g1j.get("document_non_regression_pass") is True, "document non-regression not PASS")
    req(g1j.get("numeric_non_regression_pass") is True, "numeric non-regression not PASS")
    req(g1j.get("independent_artifact_recheck_pass") is True, "independent recheck not PASS")
    req(g1j.get("next_full_basis_status") == "NONE_CURRENT_RUNTIME_ACCEPTED", "next full-basis status drift")
    req(g1j.get("status") == "FORMAL_RUNTIME_V17_28_FULL_BASIS_ACCEPTED_DATA_FAIL_CLOSED", "S3G1J status drift")
    req(g1j.get("data_verdict") == "FAIL_CLOSED", "data verdict must remain FAIL_CLOSED")
    req(g1j.get("final_gate") is False, "S3G1J incorrectly marked final PASS")

    accepted = evidence.get("accepted_run") or {}
    result = evidence.get("full_basis_result") or {}
    req(accepted.get("run_id") == 30997260730, "evidence run drift")
    req(accepted.get("artifact_id") == 8927455692, "evidence artifact ID drift")
    req(accepted.get("artifact_digest") == full_digest, "evidence digest drift")
    req(result.get("document_count") == 121354, "evidence document count drift")
    req(result.get("numeric_observation_count") == 1051799, "evidence numeric count drift")
    req(result.get("document_error_count") == 1371, "evidence error count drift")
    req(result.get("unresolved_tie_count") == 1288, "evidence tie count drift")
    req(result.get("final_data_gate_pass") is False, "evidence incorrectly passes data gate")

    lock_g1j = (lock.get("required_gates") or {}).get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(lock_g1j.get("last_completed_full_basis_generation") == "V17.28", "final lock latest basis drift")
    req(lock_g1j.get("run_id") == 30997260730, "final lock run drift")
    req(lock_g1j.get("artifact_digest") == full_digest, "final lock digest drift")
    req(lock_g1j.get("document_error_count") == 1371, "final lock error count drift")
    req(lock_g1j.get("unresolved_tie_count") == 1288, "final lock tie count drift")
    req(lock_g1j.get("data_verdict") == "FAIL_CLOSED", "final lock verdict drift")
    req(lock_g1j.get("final_gate_pass") is False, "final lock incorrectly unlocks S3G1J")

    project_g1j = ((project.get("stage3") or {}).get("s3g1j") or {})
    req(project_g1j.get("last_completed_full_basis_generation") == "V17.28", "project latest basis drift")
    req(project_g1j.get("accepted_run_id") == 30997260730, "project run drift")
    req(project_g1j.get("artifact_id", project_g1j.get("accepted_artifact_id")) == 8927455692, "project artifact drift")
    req(project_g1j.get("execution_pass") is True, "project loses execution PASS")
    req(project_g1j.get("data_verdict") == "FAIL_CLOSED", "project data verdict drift")
    req(project_g1j.get("final_gate_pass") is False, "project incorrectly marks final")
    req(project_g1j.get("next_full_basis_status") == "NONE_CURRENT_RUNTIME_ACCEPTED", "project next basis status drift")

    current = runtime.get("current_production_authority") or {}
    req(current.get("generation") == "V17.28", "runtime generation drift")
    req(current.get("status") == "RUNTIME_AND_FULL_BASIS_ACCEPTED_DATA_FAIL_CLOSED", "runtime authority status drift")
    req(current.get("full_basis_evidence_manifest") == "governance/stage3_s3g1j_v17_28_full_final.json", "runtime evidence link drift")
    req((runtime.get("full_basis_last_completed_final") or {}).get("generation") == "V17.28", "runtime latest basis drift")
    req((runtime.get("full_basis_last_completed_final") or {}).get("run") == 30997260730, "runtime latest run drift")
    req((runtime.get("next_full_basis_required") or {}).get("status") == "NONE_CURRENT_RUNTIME_ACCEPTED", "runtime next basis drift")

    active = activation.get("accepted_production_runtime") or {}
    req(active.get("generation") == "V17.28", "activation runtime drift")
    req(active.get("full_basis_execution_pending") is False, "activation incorrectly keeps full basis pending")
    req(active.get("last_completed_full_basis_generation") == "V17.28", "activation latest basis drift")
    req(active.get("last_completed_full_basis_run") == 30997260730, "activation run drift")
    req(active.get("execution_verdict") == "PASS", "activation execution verdict drift")
    req(active.get("data_verdict") == "FAIL_CLOSED", "activation data verdict drift")

    req((promotion.get("last_completed_full_basis") or {}).get("generation") == "V17.27", "historical promotion manifest was rewritten")
    req((promotion.get("next_full_basis") or {}).get("status") == "REQUIRED_NOT_STARTED", "historical promotion manifest was rewritten")

    s3g2 = components.get("S3G2_ANNOUNCEMENT_LEDGER") or {}
    req(s3g2.get("status") == "FINAL_GATE_PASS_DETERMINISTIC" and s3g2.get("final_gate") is True, "S3G2 status drift")
    req(s3g2.get("deterministic_final_run_id") == 30522392946, "S3G2 run drift")
    req(s3g2.get("ledger_sha256") == s3g2_sha, "S3G2 SHA drift")
    req(s3g2.get("deterministic_replay_count") == 2 and s3g2.get("deterministic_replay_same_sha") is True, "S3G2 replay evidence missing")

    policy = authority.get("policy") or {}
    for key in (
        "diagnostic_prs_are_evidence_not_merge_units",
        "accepted_candidate_does_not_equal_final_pass",
        "runtime_promotion_does_not_equal_full_basis_acceptance",
        "expected_counts_do_not_equal_production_acceptance",
        "accepted_full_basis_execution_does_not_equal_final_data_pass",
        "artifact_archive_digest_is_transport_not_dataset_identity",
        "no_accounting_tolerance_relaxation",
        "no_pit_relaxation",
        "no_security_identity_relaxation",
        "unreliable_parse_remains_fail_closed",
    ):
        req(policy.get(key) is True, f"required governance policy disabled: {key}")

    report = {
        "gate": "STAGE3_AUTHORITY_MAP",
        "pass": not errors,
        "stage3_status": lock.get("status"),
        "pending_final_gates": sorted(pending),
        "s3g1j_formal_runtime_generation": g1j.get("formal_runtime_generation"),
        "s3g1j_last_completed_full_basis_generation": g1j.get("last_completed_full_basis_generation"),
        "s3g1j_last_completed_run": g1j.get("accepted_run_id"),
        "s3g1j_data_verdict": g1j.get("data_verdict"),
        "s3g1j_document_errors": g1j.get("document_error_count"),
        "s3g1j_unresolved_ties": g1j.get("unresolved_tie_count"),
        "stage4_unlocked": project.get("stage4_unlocked"),
        "alpha_training_allowed": project.get("alpha_training_allowed"),
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
