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
    v17_28 = load("governance/stage3_s3g1j_v17_28_full_final.json")
    v17_29 = load("governance/stage3_s3g1j_v17_29_runtime_promotion.json")

    def req(cond: bool, message: str) -> None:
        if not cond:
            errors.append(message)

    stage2_fp = "f17f7ab63f4532dda635eb7366e7df7bf5497a5ce814410105312bccb53125bb"
    s3g2_sha = "0eb139572865628283f86c981990e59e076d5ef2a978a5967aace90d553e30dd"
    v17_28_digest = "sha256:82375169faada969ceafd4356ab0a2707aa14592d5db090c5d3910863d571c8b"
    wrapper_digest = "sha256:4f9940513c2d0ef5250b8874b32f68655badfe4a695a2fe2c3da0a54d2a01670"
    wrapper_report_sha = "29fc2947008e26b8c17ab5c9013a31c5e283c2d89aa37a8f7de2e1da5658a406"

    req(authority.get("schema_version") == 5, "authority map schema must be 5")
    req(authority.get("status") == "INTEGRATION_IN_PROGRESS", "authority status drift")
    req((authority.get("stage2_dependency") or {}).get("fingerprint") == stage2_fp, "authority Stage2 fingerprint drift")
    req(lock.get("version") == "V3.3.12-stage3-final-lock", "Stage3 final-lock version drift")
    req(lock.get("status") == "NOT_READY", "Stage3 final lock must remain NOT_READY")
    req((lock.get("stage2") or {}).get("fingerprint") == stage2_fp, "final lock Stage2 fingerprint drift")
    req(project.get("schema_version") == 5, "project status schema must be 5")
    req(runtime.get("schema_version") == 12, "runtime manifest schema must be 12")
    req(activation.get("schema_version") == 14, "activation manifest schema must be 14")

    for key in ("stage4_unlocked", "alpha_training_allowed", "live_signal_allowed"):
        req(project.get(key) is False, f"project unexpectedly enables {key}")
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
    req(authority.get("current_s3g1j_execution_pr") == 109, "current S3G1J wrapper evidence PR must be #109")
    req(authority.get("current_s3g1j_governance_pr") == 110, "current S3G1J governance PR must be #110")
    req(109 in set(authority.get("non_merge_evidence_prs") or []), "wrapper PR #109 must remain non-merge evidence")
    req(g1j.get("formal_runtime_generation") == "V17.29", "S3G1J runtime must be V17.29")
    req(g1j.get("runtime_wrapper_pr") == 109, "V17.29 wrapper PR drift")
    req(g1j.get("runtime_wrapper_pr_closed_without_merge") is True, "V17.29 wrapper PR must close unmerged")
    req(g1j.get("runtime_wrapper_run_id") == 31312709490, "V17.29 wrapper run drift")
    req(g1j.get("runtime_wrapper_artifact_id") == 9037869497, "V17.29 wrapper artifact ID drift")
    req(g1j.get("runtime_wrapper_artifact_digest") == wrapper_digest, "V17.29 wrapper artifact digest drift")
    req(g1j.get("runtime_wrapper_report_sha256") == wrapper_report_sha, "V17.29 wrapper report SHA drift")
    req(g1j.get("runtime_contract_pass") is True, "V17.29 runtime contract not PASS")

    # V17.28 must remain the latest completed basis until a new V17.29 run is accepted.
    req(g1j.get("last_completed_full_basis_generation") == "V17.28", "last completed full basis must remain V17.28")
    req(g1j.get("accepted_run_id") == 30997260730, "V17.28 accepted run drift")
    req(g1j.get("accepted_artifact_id") == 8927455692, "V17.28 artifact ID drift")
    req(g1j.get("accepted_artifact_digest") == v17_28_digest, "V17.28 artifact digest drift")
    req(g1j.get("document_count") == 121354, "last completed document count drift")
    req(g1j.get("numeric_observation_count") == 1051799, "last completed numeric count drift")
    req(g1j.get("document_error_count") == 1371, "last completed document error count drift")
    req(g1j.get("unresolved_tie_count") == 1288, "last completed unresolved tie count drift")
    req(g1j.get("data_verdict") == "FAIL_CLOSED", "S3G1J data verdict must remain FAIL_CLOSED")
    req(g1j.get("final_gate") is False, "S3G1J incorrectly marked final PASS")
    req(g1j.get("next_full_basis_generation") == "V17.29", "next full basis generation drift")
    req(g1j.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "next full basis status drift")
    req(g1j.get("expected_next_numeric_observation_count") == 1051820, "V17.29 expected numeric count drift")
    req(g1j.get("expected_next_document_error_count") == 1364, "V17.29 expected error count drift")
    req(g1j.get("expected_next_unresolved_tie_count") == 1281, "V17.29 expected tie count drift")
    req(g1j.get("expected_values_are_not_production_acceptance") is True, "expected counts lost non-authoritative marker")
    req(g1j.get("status") == "FORMAL_RUNTIME_V17_29_FULL_BASIS_V17_28_LAST_COMPLETED_PENDING_FAIL_CLOSED", "S3G1J status drift")

    # Immutable V17.28 full-basis evidence remains unchanged historical truth.
    accepted = v17_28.get("accepted_run") or {}
    result = v17_28.get("full_basis_result") or {}
    req(accepted.get("run_id") == 30997260730, "V17.28 evidence run drift")
    req(accepted.get("artifact_id") == 8927455692, "V17.28 evidence artifact drift")
    req(accepted.get("artifact_digest") == v17_28_digest, "V17.28 evidence digest drift")
    req(result.get("document_count") == 121354, "V17.28 evidence document count drift")
    req(result.get("numeric_observation_count") == 1051799, "V17.28 evidence numeric count drift")
    req(result.get("document_error_count") == 1371, "V17.28 evidence error count drift")
    req(result.get("unresolved_tie_count") == 1288, "V17.28 evidence tie count drift")
    req(result.get("final_data_gate_pass") is False, "V17.28 evidence incorrectly passes data gate")

    # V17.29 promotion evidence must explicitly separate runtime from full basis.
    req(v17_29.get("schema_version") == 1, "V17.29 promotion evidence schema drift")
    req(v17_29.get("generation") == "V17.29", "V17.29 promotion evidence generation drift")
    wrapper = v17_29.get("wrapper_implementation") or {}
    req(wrapper.get("pr") == 109, "V17.29 promotion evidence wrapper PR drift")
    req(wrapper.get("closed_without_merge") is True, "V17.29 wrapper merge boundary drift")
    req(wrapper.get("head_sha") == "04a014f852bff57aef57542553864fcd3f1df13d", "V17.29 wrapper head drift")
    req(wrapper.get("acceptance_run") == 31312709490, "V17.29 wrapper acceptance run drift")
    req(wrapper.get("acceptance_artifact_id") == 9037869497, "V17.29 wrapper artifact drift")
    req(wrapper.get("acceptance_artifact_digest") == wrapper_digest, "V17.29 promotion wrapper digest drift")
    req(wrapper.get("acceptance_report_sha256") == wrapper_report_sha, "V17.29 promotion wrapper report drift")
    nxt = v17_29.get("next_full_basis") or {}
    req(nxt.get("generation") == "V17.29", "promotion next basis generation drift")
    req(nxt.get("status") == "REQUIRED_NOT_STARTED", "promotion next basis must be not started")
    req(nxt.get("expected_values_are_not_production_acceptance") is True, "promotion expected counts incorrectly authoritative")
    boundaries = v17_29.get("hard_boundaries") or {}
    req(boundaries.get("fresh_64_shard_execution_started") is False, "promotion started full basis too early")
    req(boundaries.get("stage3_status") == "NOT_READY", "promotion unlocks Stage3")
    req(boundaries.get("stage4_alpha_live_locked") is True, "promotion unlocks downstream")

    current = runtime.get("current_production_authority") or {}
    formal = runtime.get("formal_runtime") or {}
    latest = runtime.get("full_basis_last_completed_final") or {}
    next_required = runtime.get("next_full_basis_required") or {}
    req(current.get("generation") == "V17.29", "runtime current production generation drift")
    req(current.get("status") == "RUNTIME_PROMOTED_FULL_BASIS_PENDING_FAIL_CLOSED", "runtime authority status drift")
    req(current.get("full_basis_evidence_manifest") is None, "V17.29 must not claim a full-basis evidence manifest yet")
    req(formal.get("runtime_generation") == "V17.29", "formal runtime generation drift")
    req(formal.get("parser_path") == "scripts/stage3_financial_pdf_parser_v21.py", "formal parser path drift")
    req(formal.get("extractor_path") == "scripts/extract_stage3_financial_pdf_values_v19.py", "formal extractor path drift")
    req(formal.get("parser_git_blob") == "37ab001356c479808e3fa5f67f2270649e3130ba", "formal parser blob drift")
    req(formal.get("extractor_git_blob") == "7be4f17357e92144c3f54ddd4951ec57a0878049", "formal extractor blob drift")
    req(latest.get("generation") == "V17.28", "runtime latest completed basis must remain V17.28")
    req(latest.get("run") == 30997260730, "runtime latest completed run drift")
    req(next_required.get("generation") == "V17.29", "runtime next basis generation drift")
    req(next_required.get("status") == "REQUIRED_NOT_STARTED", "runtime next basis status drift")
    req(next_required.get("expected_values_are_not_yet_production_acceptance") is True, "runtime expected counts incorrectly accepted")

    active = activation.get("accepted_production_runtime") or {}
    req(active.get("generation") == "V17.29", "activation runtime drift")
    req(active.get("runtime_manifest_schema") == 12, "activation runtime manifest schema drift")
    req(active.get("full_basis_execution_pending") is True, "activation must keep V17.29 full basis pending")
    req(active.get("last_completed_full_basis_generation") == "V17.28", "activation last completed basis drift")
    req(active.get("last_completed_full_basis_run") == 30997260730, "activation last completed run drift")
    req(active.get("execution_verdict") == "PENDING", "activation V17.29 execution verdict must be pending")
    req(active.get("data_verdict") == "FAIL_CLOSED", "activation data verdict drift")
    req(active.get("expected_values_are_not_production_acceptance") is True, "activation expected counts incorrectly accepted")

    lock_g1j = (lock.get("required_gates") or {}).get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(lock_g1j.get("formal_runtime_generation") == "V17.29", "final lock runtime drift")
    req(lock_g1j.get("last_completed_full_basis_generation") == "V17.28", "final lock latest basis drift")
    req(lock_g1j.get("run_id") == 30997260730, "final lock V17.28 run drift")
    req(lock_g1j.get("artifact_digest") == v17_28_digest, "final lock V17.28 digest drift")
    req(lock_g1j.get("document_error_count") == 1371, "final lock historical error drift")
    req(lock_g1j.get("unresolved_tie_count") == 1288, "final lock historical tie drift")
    req(lock_g1j.get("next_full_basis_generation") == "V17.29", "final lock next basis drift")
    req(lock_g1j.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "final lock next basis status drift")
    req(lock_g1j.get("expected_values_are_not_production_acceptance") is True, "final lock expected counts incorrectly accepted")
    req(lock_g1j.get("final_gate_pass") is False, "final lock incorrectly unlocks S3G1J")

    project_g1j = ((project.get("stage3") or {}).get("s3g1j") or {})
    req(project_g1j.get("formal_runtime_generation") == "V17.29", "project runtime drift")
    req(project_g1j.get("last_completed_full_basis_generation") == "V17.28", "project latest basis drift")
    req(project_g1j.get("accepted_run_id") == 30997260730, "project V17.28 run drift")
    req(project_g1j.get("numeric_observation_count") == 1051799, "project historical numeric drift")
    req(project_g1j.get("document_error_count") == 1371, "project historical error drift")
    req(project_g1j.get("unresolved_tie_count") == 1288, "project historical tie drift")
    req(project_g1j.get("next_full_basis_generation") == "V17.29", "project next basis drift")
    req(project_g1j.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "project next basis status drift")
    req(project_g1j.get("expected_values_are_not_production_acceptance") is True, "project expected counts incorrectly accepted")
    req(project_g1j.get("data_verdict") == "FAIL_CLOSED", "project data verdict drift")
    req(project_g1j.get("final_gate_pass") is False, "project incorrectly marks S3G1J final")

    s3g2 = components.get("S3G2_ANNOUNCEMENT_LEDGER") or {}
    req(s3g2.get("status") == "FINAL_GATE_PASS_DETERMINISTIC" and s3g2.get("final_gate") is True, "S3G2 status drift")
    req(s3g2.get("deterministic_final_run_id") == 30522392946, "S3G2 run drift")
    req(s3g2.get("ledger_sha256") == s3g2_sha, "S3G2 SHA drift")

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
        "s3g1j_next_full_basis_generation": g1j.get("next_full_basis_generation"),
        "s3g1j_next_full_basis_status": g1j.get("next_full_basis_status"),
        "s3g1j_data_verdict": g1j.get("data_verdict"),
        "s3g1j_last_completed_document_errors": g1j.get("document_error_count"),
        "s3g1j_last_completed_unresolved_ties": g1j.get("unresolved_tie_count"),
        "stage4_unlocked": project.get("stage4_unlocked"),
        "alpha_training_allowed": project.get("alpha_training_allowed"),
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
