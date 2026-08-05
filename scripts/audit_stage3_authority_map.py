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
    promotion = load("governance/stage3_s3g1j_v17_28_runtime_promotion.json")

    def req(cond: bool, message: str) -> None:
        if not cond:
            errors.append(message)

    expected_fp = "f17f7ab63f4532dda635eb7366e7df7bf5497a5ce814410105312bccb53125bb"
    expected_s3g2_sha = "0eb139572865628283f86c981990e59e076d5ef2a978a5967aace90d553e30dd"
    v17_27_digest = "sha256:410e257d7a3ada353926970f806abc3e970e5638f55c1dec7b47c71c57777721"
    v17_27_semantic_sha = "05b914b03dbcc23d3f6eca560189afbfe6ea427913f9cf1380fa09cdea6aa8d7"
    wrapper_digest = "sha256:f8639b4a2eac2d09b16586365b7932d255457ce66aad2484547bb517d0d185a6"

    req(authority.get("schema_version") == 3, "authority map schema must be 3")
    req(authority.get("status") == "INTEGRATION_IN_PROGRESS", "authority map status drift")
    req((authority.get("stage2_dependency") or {}).get("fingerprint") == expected_fp, "authority Stage2 fingerprint drift")
    req(lock.get("version") == "V3.3.10-stage3-final-lock", "Stage3 final-lock version drift")
    req(lock.get("status") == "NOT_READY", "Stage3 final lock must remain NOT_READY")
    req((lock.get("stage2") or {}).get("fingerprint") == expected_fp, "Stage3 lock Stage2 fingerprint drift")
    req(project.get("schema_version") == 3, "project status schema must be 3")
    req(project.get("stage4_unlocked") is False, "project unexpectedly unlocks Stage4")
    req(project.get("alpha_training_allowed") is False, "project unexpectedly allows Alpha training")
    req(project.get("live_signal_allowed") is False, "project unexpectedly allows live signals")

    unlock = authority.get("project_unlock") or {}
    req(unlock.get("stage4_unlocked") is False, "authority map unlocks Stage4")
    req(unlock.get("alpha_training_allowed") is False, "authority map allows Alpha training")
    req(unlock.get("live_signal_allowed") is False, "authority map allows live signals")

    expected_pending = {"S3G1J_FINANCIAL_RAW_VALUES", "S3G4_EARNINGS_SURPRISE"}
    req(set(lock.get("remaining_unlocked_gates") or []) == expected_pending, "final-lock pending gate set drift")
    req(set((project.get("stage3") or {}).get("pending_final_gates") or []) == expected_pending, "project pending gate set drift")

    components = authority.get("authoritative_components") or {}
    for gate in expected_pending:
        req(gate in components, f"authority map missing pending gate {gate}")
        req((components.get(gate) or {}).get("final_gate") is False, f"pending gate {gate} incorrectly final")

    g1j = components.get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(authority.get("current_s3g1j_execution_pr") == 87, "last full-basis execution PR must remain #87")
    req(authority.get("current_s3g1j_governance_pr") == 94, "accepted runtime-wrapper governance PR must be #94")
    req(g1j.get("formal_runtime_generation") == "V17.28", "S3G1J formal runtime drift")
    req(g1j.get("runtime_wrapper_pr") == 94, "S3G1J wrapper PR drift")
    req(g1j.get("runtime_wrapper_head_sha") == "6969c58ee60314e3e897e55b132266612c602777", "S3G1J wrapper head drift")
    req(g1j.get("runtime_wrapper_merge_commit") == "d7c38e71c9155d404df1c08feba9d66fac0a4d7a", "S3G1J wrapper merge drift")
    req(g1j.get("runtime_wrapper_run_id") == 30978715158, "S3G1J wrapper run drift")
    req(g1j.get("runtime_wrapper_artifact_id") == 8919289427, "S3G1J wrapper artifact ID drift")
    req(g1j.get("runtime_wrapper_artifact_digest") == wrapper_digest, "S3G1J wrapper artifact digest drift")
    req(g1j.get("runtime_contract_pass") is True, "S3G1J runtime contract is not PASS")

    req(g1j.get("last_completed_full_basis_generation") == "V17.27", "last completed full-basis generation drift")
    req(g1j.get("accepted_execution_pr") == 87, "V17.27 execution provenance drift")
    req(g1j.get("governance_closure_pr") == 88, "V17.27 governance provenance drift")
    req(g1j.get("accepted_run_id") == 30806818977, "V17.27 accepted run drift")
    req(g1j.get("accepted_artifact_id") == 8854139999, "V17.27 artifact ID drift")
    req(g1j.get("accepted_artifact_digest") == v17_27_digest, "V17.27 artifact digest drift")
    req(g1j.get("document_count") == 121354, "V17.27 document count drift")
    req(g1j.get("numeric_observation_count") == 1051793, "V17.27 numeric count drift")
    req(g1j.get("document_error_count") == 1373, "V17.27 error count drift")
    req(g1j.get("unresolved_tie_count") == 1290, "V17.27 tie count drift")
    req(g1j.get("target_numeric_rows") == 15, "V17.27 target numeric count drift")
    req(g1j.get("unexpected_document_regression_count") == 0, "unexpected document regression detected")
    req(g1j.get("existing_numeric_semantic_sha256") == v17_27_semantic_sha, "V17.27 semantic SHA drift")
    req(g1j.get("execution_pass") is True, "last full-basis execution is not PASS")
    req(g1j.get("document_non_regression_pass") is True, "document non-regression not PASS")
    req(g1j.get("numeric_non_regression_pass") is True, "numeric non-regression not PASS")

    req(g1j.get("next_full_basis_generation") == "V17.28", "next full-basis generation drift")
    req(g1j.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "next full-basis must remain not started")
    req(g1j.get("expected_v17_28_document_count") == 121354, "expected V17.28 document count drift")
    req(g1j.get("expected_v17_28_numeric_observation_count") == 1051799, "expected V17.28 numeric count drift")
    req(g1j.get("expected_v17_28_document_error_count") == 1371, "expected V17.28 error count drift")
    req(g1j.get("expected_v17_28_unresolved_tie_count") == 1288, "expected V17.28 tie count drift")
    req(g1j.get("expected_values_are_not_production_acceptance") is True, "expected counts misrepresented as production")
    req(g1j.get("status") == "FORMAL_RUNTIME_V17_28_FULL_BASIS_PENDING_FAIL_CLOSED", "S3G1J status drift")
    req(g1j.get("data_verdict") == "FAIL_CLOSED", "S3G1J data verdict must remain FAIL_CLOSED")
    req(g1j.get("final_gate") is False, "S3G1J incorrectly marked final PASS")

    lock_g1j = (lock.get("required_gates") or {}).get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(lock_g1j.get("formal_runtime_generation") == "V17.28", "final lock formal runtime drift")
    req(lock_g1j.get("runtime_wrapper_run_id") == 30978715158, "final lock wrapper run drift")
    req(lock_g1j.get("runtime_wrapper_artifact_digest") == wrapper_digest, "final lock wrapper digest drift")
    req(lock_g1j.get("last_completed_full_basis_generation") == "V17.27", "final lock last full basis drift")
    req(lock_g1j.get("run_id") == 30806818977, "final lock V17.27 run drift")
    req(lock_g1j.get("artifact_digest") == v17_27_digest, "final lock V17.27 digest drift")
    req(lock_g1j.get("data_verdict") == "FAIL_CLOSED", "final lock data verdict drift")
    req(lock_g1j.get("final_gate_pass") is False, "final lock incorrectly unlocks S3G1J")
    req(lock_g1j.get("next_full_basis_generation") == "V17.28", "final lock next generation drift")
    req(lock_g1j.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "final lock next run status drift")
    req(lock_g1j.get("expected_values_are_not_production_acceptance") is True, "final lock expected counts misrepresented")

    project_g1j = ((project.get("stage3") or {}).get("s3g1j") or {})
    req(project_g1j.get("formal_runtime_generation") == "V17.28", "project formal runtime drift")
    req(project_g1j.get("runtime_wrapper_run_id") == 30978715158, "project wrapper run drift")
    req(project_g1j.get("last_completed_full_basis_generation") == "V17.27", "project last full basis drift")
    req(project_g1j.get("accepted_run_id") == 30806818977, "project V17.27 run drift")
    req(project_g1j.get("execution_pass") is True, "project loses execution PASS")
    req(project_g1j.get("data_verdict") == "FAIL_CLOSED", "project data verdict drift")
    req(project_g1j.get("final_gate_pass") is False, "project incorrectly marks S3G1J final")
    req(project_g1j.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "project next full basis status drift")
    req(project_g1j.get("expected_values_are_not_production_acceptance") is True, "project expected counts misrepresented")

    req(runtime.get("schema_version") == 10, "runtime manifest schema drift")
    req((runtime.get("formal_runtime") or {}).get("runtime_generation") == "V17.28", "runtime manifest generation drift")
    req((runtime.get("full_basis_last_completed_final") or {}).get("generation") == "V17.27", "runtime manifest historical authority drift")
    req((runtime.get("next_full_basis_required") or {}).get("status") == "REQUIRED_NOT_STARTED", "runtime manifest next basis status drift")
    req(activation.get("schema_version") == 12, "activation manifest schema drift")
    req((activation.get("accepted_production_runtime") or {}).get("generation") == "V17.28", "activation runtime drift")
    req((activation.get("accepted_production_runtime") or {}).get("full_basis_execution_pending") is True, "activation must keep V17.28 basis pending")
    req((promotion.get("last_completed_full_basis") or {}).get("generation") == "V17.27", "promotion historical basis drift")
    req((promotion.get("next_full_basis") or {}).get("status") == "REQUIRED_NOT_STARTED", "promotion next basis status drift")

    s3g2 = components.get("S3G2_ANNOUNCEMENT_LEDGER") or {}
    req(s3g2.get("repair_source_pr") == 40, "S3G2 repair provenance drift")
    req(s3g2.get("status") == "FINAL_GATE_PASS_DETERMINISTIC" and s3g2.get("final_gate") is True, "S3G2 final status drift")
    req(s3g2.get("deterministic_final_run_id") == 30522392946, "S3G2 run drift")
    req(s3g2.get("ledger_sha256") == expected_s3g2_sha, "S3G2 ledger SHA drift")
    req(s3g2.get("deterministic_replay_count") == 2 and s3g2.get("deterministic_replay_same_sha") is True, "S3G2 replay evidence missing")
    req(s3g2.get("artifact_digest_is_transport_only") is True, "S3G2 archive digest treated as dataset identity")

    evidence = set(authority.get("non_merge_evidence_prs") or [])
    superseded = set(authority.get("superseded_s3g1j_production_prs") or [])
    req(not (evidence & superseded), "diagnostic and superseded PR sets overlap")
    req({90, 92}.issubset(evidence), "V17.28 diagnostic/candidate PRs missing from evidence set")
    req(63 in superseded, "V17.11 PR #63 must remain superseded history")

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
        "pending_final_gates": sorted(expected_pending),
        "s3g1j_formal_runtime_generation": g1j.get("formal_runtime_generation"),
        "s3g1j_last_completed_full_basis_generation": g1j.get("last_completed_full_basis_generation"),
        "s3g1j_last_completed_run": g1j.get("accepted_run_id"),
        "s3g1j_next_full_basis_status": g1j.get("next_full_basis_status"),
        "s3g1j_data_verdict": g1j.get("data_verdict"),
        "s3g1j_document_errors": g1j.get("document_error_count"),
        "s3g1j_unresolved_ties": g1j.get("unresolved_tie_count"),
        "s3g2_final_run": s3g2.get("deterministic_final_run_id"),
        "s3g2_ledger_sha256": s3g2.get("ledger_sha256"),
        "stage4_unlocked": project.get("stage4_unlocked"),
        "alpha_training_allowed": project.get("alpha_training_allowed"),
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
