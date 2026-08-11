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
    promotion = load("governance/stage3_s3g1j_v17_30_runtime_promotion.json")
    wrapper = load("governance/stage3_s3g1j_v17_30_runtime_wrapper_acceptance.json")
    v29 = load("governance/stage3_s3g1j_v17_29_full_final.json")
    v28 = load("governance/stage3_s3g1j_v17_28_full_final.json")
    v27 = load("governance/stage3_s3g1j_v17_27_full_final.json")
    v26 = load("governance/stage3_s3g1j_v17_26_full_final.json")

    def req(cond: bool, message: str) -> None:
        if not cond:
            errors.append(message)

    stage2_fp = "f17f7ab63f4532dda635eb7366e7df7bf5497a5ce814410105312bccb53125bb"
    s3g2_sha = "0eb139572865628283f86c981990e59e076d5ef2a978a5967aace90d553e30dd"
    v30_wrapper_digest = "sha256:232b2e4a6c64b271193853d4e8fd32c0fdfd367344ecec720902fe8f090333dc"
    v29_digest = "sha256:71a4daa6c8372f3d64080b5fa5b787914292d889da7051de699eb6610189c726"
    v28_digest = "sha256:82375169faada969ceafd4356ab0a2707aa14592d5db090c5d3910863d571c8b"
    v27_digest = "sha256:410e257d7a3ada353926970f806abc3e970e5638f55c1dec7b47c71c57777721"
    v26_digest = "sha256:7f2e707e9192af527ff0444b48caf6bebfbfa1ef7559ec2810b6f47b1790567b"

    req(authority.get("schema_version") == 7, "authority map schema must be 7")
    req(authority.get("status") == "INTEGRATION_IN_PROGRESS", "authority status drift")
    req((authority.get("stage2_dependency") or {}).get("fingerprint") == stage2_fp, "authority Stage2 fingerprint drift")
    req(lock.get("version") == "V3.3.14-stage3-final-lock", "Stage3 final-lock version drift")
    req(lock.get("status") == "NOT_READY", "Stage3 final lock must remain NOT_READY")
    req((lock.get("stage2") or {}).get("fingerprint") == stage2_fp, "final lock Stage2 fingerprint drift")
    req(project.get("schema_version") == 7, "project status schema must be 7")
    req(runtime.get("schema_version") == 14, "runtime manifest schema must be 14")
    req(activation.get("schema_version") == 16, "activation manifest schema must be 16")

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
    req(authority.get("current_s3g1j_execution_pr") == 113, "last completed basis execution evidence PR must remain #113")
    req(authority.get("current_s3g1j_governance_pr") == 125, "current runtime governance PR must be #125")
    req(authority.get("current_s3g1j_runtime_wrapper_pr") == 123, "current runtime wrapper PR must be #123")
    req(123 in set(authority.get("non_merge_evidence_prs") or []), "runtime wrapper PR #123 must remain non-merge evidence")
    req(113 in set(authority.get("non_merge_evidence_prs") or []), "V17.29 basis execution PR #113 must remain non-merge evidence")
    req(g1j.get("formal_runtime_generation") == "V17.30", "S3G1J formal runtime must be V17.30")
    req(g1j.get("runtime_wrapper_pr") == 123, "V17.30 runtime wrapper PR drift")
    req(g1j.get("runtime_wrapper_artifact_digest") == v30_wrapper_digest, "V17.30 wrapper digest drift")
    req(g1j.get("runtime_governance_pr") == 125, "V17.30 governance PR drift")
    req(g1j.get("last_completed_full_basis_generation") == "V17.29", "latest completed basis must remain V17.29")
    req(g1j.get("full_basis_evidence_manifest") == "governance/stage3_s3g1j_v17_29_full_final.json", "V17.29 full-basis evidence path drift")
    req(g1j.get("source_execution_pr") == 113, "V17.29 source execution PR drift")
    req(g1j.get("accepted_execution_pr") == 112, "V17.29 acceptance PR drift")
    req(g1j.get("full_basis_governance_closure_pr") == 114, "V17.29 full-basis governance PR drift")
    req(g1j.get("accepted_run_id") == 31389854868, "V17.29 accepted run drift")
    req(g1j.get("accepted_artifact_id") == 9063271903, "V17.29 artifact ID drift")
    req(g1j.get("accepted_artifact_digest") == v29_digest, "V17.29 artifact digest drift")
    req(g1j.get("document_count") == 121354, "V17.29 document count drift")
    req(g1j.get("numeric_observation_count") == 1051820, "V17.29 numeric count drift")
    req(g1j.get("document_error_count") == 1364, "V17.29 error count drift")
    req(g1j.get("unresolved_tie_count") == 1281, "V17.29 tie count drift")
    req(g1j.get("next_full_basis_generation") == "V17.30", "next full basis must be V17.30")
    req(g1j.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "V17.30 full basis must be not started")
    req(g1j.get("expected_next_numeric_observation_count") == 1051826, "V17.30 expected numeric count drift")
    req(g1j.get("expected_next_document_error_count") == 1362, "V17.30 expected error count drift")
    req(g1j.get("expected_next_unresolved_tie_count") == 1279, "V17.30 expected tie count drift")
    req(g1j.get("expected_values_are_not_production_acceptance") is True, "V17.30 expectation mislabeled as acceptance")
    req(g1j.get("data_verdict") == "FAIL_CLOSED", "S3G1J data verdict must remain FAIL_CLOSED")
    req(g1j.get("final_gate") is False, "S3G1J incorrectly marked final PASS")

    current = runtime.get("current_production_authority") or {}
    formal = runtime.get("formal_runtime") or {}
    latest = runtime.get("full_basis_last_completed_final") or {}
    prev28 = runtime.get("previous_last_completed_full_basis_final") or {}
    prev27 = runtime.get("previous_full_basis_final") or {}
    prev26 = runtime.get("historical_full_basis_final") or {}
    next_required = runtime.get("next_full_basis_required") or {}
    req(current.get("generation") == "V17.30", "runtime current generation drift")
    req(current.get("status") == "RUNTIME_PROMOTED_FULL_BASIS_PENDING_DATA_FAIL_CLOSED", "runtime authority status drift")
    req(formal.get("runtime_generation") == "V17.30", "formal runtime generation drift")
    req(formal.get("parser_git_blob") == "cc782817e5ee73fcae085d71f4896a0adc004dcd", "formal V17.30 parser blob drift")
    req(formal.get("extractor_git_blob") == "d74a2b1f8f0ec3af8d89ce259e83392d7f8cc20c", "formal V17.30 extractor blob drift")
    req(formal.get("promotion_safety_parser_git_blob") == "1a4364d5cde7881455902f6fa1dbe5e68f3843a6", "formal V17.30 helper blob drift")
    req(latest.get("generation") == "V17.29" and latest.get("run") == 31389854868, "runtime latest completed basis drift")
    req(latest.get("artifact_digest") == v29_digest, "runtime V17.29 digest drift")
    req(prev28.get("generation") == "V17.28" and prev28.get("run") == 30997260730, "runtime retained V17.28 history drift")
    req(prev28.get("artifact_digest") == v28_digest and prev28.get("retained") is True, "runtime V17.28 history not retained")
    req(prev27.get("generation") == "V17.27" and prev27.get("artifact_digest") == v27_digest and prev27.get("retained") is True, "runtime V17.27 history drift")
    req(prev26.get("generation") == "V17.26" and prev26.get("artifact_digest") == v26_digest and prev26.get("retained") is True, "runtime V17.26 history drift")
    req(next_required.get("generation") == "V17.30", "runtime next basis generation drift")
    req(next_required.get("status") == "REQUIRED_NOT_STARTED", "runtime V17.30 basis status drift")
    req(next_required.get("expected_values_are_not_production_acceptance") is True, "runtime expectation boundary drift")

    active = activation.get("accepted_production_runtime") or {}
    req(active.get("generation") == "V17.30", "activation runtime drift")
    req(active.get("runtime_manifest_schema") == 14, "activation runtime schema drift")
    req(active.get("full_basis_execution_pending") is True, "activation must require fresh V17.30 full basis")
    req(active.get("next_full_basis_generation") == "V17.30", "activation next basis drift")
    req(active.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "activation next basis status drift")
    req(active.get("last_completed_full_basis_generation") == "V17.29", "activation last completed basis drift")
    req(active.get("last_completed_full_basis_run") == 31389854868, "activation last completed run drift")
    req(active.get("last_completed_full_basis_artifact_digest") == v29_digest, "activation V17.29 digest drift")
    req(active.get("data_verdict") == "FAIL_CLOSED", "activation data verdict drift")
    req((activation.get("accepted_v17_30_runtime_wrapper") or {}).get("runtime_promoted") is True, "activation V17.30 wrapper not promoted")
    req((activation.get("accepted_v17_29_full_basis_evidence") or {}).get("last_completed_full_basis_authority") is True, "activation must retain V17.29 as last completed basis")

    req(promotion.get("generation") == "V17.30", "V17.30 promotion manifest drift")
    req(promotion.get("governance_pr") == 125, "V17.30 promotion PR drift")
    req((promotion.get("wrapper_acceptance") or {}).get("execution_pr") == 123, "promotion wrapper PR drift")
    req((promotion.get("next_full_basis") or {}).get("status") == "REQUIRED_NOT_STARTED", "promotion started full basis unexpectedly")
    req((promotion.get("hard_boundaries") or {}).get("fresh_64_shard_execution_started") is False, "promotion started fresh execution")
    req((wrapper.get("authorization") or {}).get("formal_runtime_promotion_governance_eligible") is True, "registered wrapper not promotion eligible")

    lock_g1j = (lock.get("required_gates") or {}).get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(lock_g1j.get("formal_runtime_generation") == "V17.30", "final lock runtime drift")
    req(lock_g1j.get("last_completed_full_basis_generation") == "V17.29", "final lock last basis drift")
    req(lock_g1j.get("run_id") == 31389854868, "final lock V17.29 run drift")
    req(lock_g1j.get("artifact_digest") == v29_digest, "final lock V17.29 digest drift")
    req(lock_g1j.get("next_full_basis_generation") == "V17.30", "final lock next generation drift")
    req(lock_g1j.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "final lock next basis status drift")
    req(lock_g1j.get("final_gate_pass") is False, "final lock incorrectly unlocks S3G1J")

    pg1j = ((project.get("stage3") or {}).get("s3g1j") or {})
    req(pg1j.get("formal_runtime_generation") == "V17.30", "project runtime drift")
    req(pg1j.get("last_completed_full_basis_generation") == "V17.29", "project last basis drift")
    req(pg1j.get("accepted_run_id") == 31389854868, "project V17.29 run drift")
    req(pg1j.get("accepted_artifact_digest") == v29_digest, "project V17.29 digest drift")
    req(pg1j.get("numeric_observation_count") == 1051820, "project numeric count drift")
    req(pg1j.get("document_error_count") == 1364, "project error count drift")
    req(pg1j.get("unresolved_tie_count") == 1281, "project tie count drift")
    req(pg1j.get("next_full_basis_generation") == "V17.30", "project next basis drift")
    req(pg1j.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "project next basis status drift")
    req(pg1j.get("expected_values_are_not_production_acceptance") is True, "project expectation boundary drift")
    req(pg1j.get("data_verdict") == "FAIL_CLOSED", "project data verdict drift")
    req(pg1j.get("final_gate_pass") is False, "project incorrectly marks S3G1J final")

    accepted29 = v29.get("accepted_run") or {}
    result29 = v29.get("full_basis_result") or {}
    req(accepted29.get("run_id") == 31389854868 and accepted29.get("artifact_id") == 9063271903, "V17.29 evidence identity drift")
    req(accepted29.get("artifact_digest") == v29_digest, "V17.29 evidence digest drift")
    req(result29.get("numeric_observation_count") == 1051820 and result29.get("document_error_count") == 1364 and result29.get("unresolved_tie_count") == 1281, "V17.29 result counts drift")
    req(result29.get("final_data_gate_pass") is False, "V17.29 evidence incorrectly passes data gate")

    for name, evidence, run, artifact, digest, numeric, err, ties in (
        ("V17.28", v28, 30997260730, 8927455692, v28_digest, 1051799, 1371, 1288),
        ("V17.27", v27, 30806818977, 8854139999, v27_digest, 1051793, 1373, 1290),
        ("V17.26", v26, 30733013665, 8828600783, v26_digest, 1051778, 1378, 1295),
    ):
        accepted = evidence.get("accepted_run") or {}
        result = evidence.get("full_basis_result") or {}
        req(accepted.get("run_id") == run, f"{name} historical run drift")
        req(accepted.get("artifact_id") == artifact, f"{name} historical artifact ID drift")
        req(accepted.get("artifact_digest") == digest, f"{name} historical digest drift")
        req(result.get("numeric_observation_count") == numeric, f"{name} historical numeric drift")
        req(result.get("document_error_count") == err, f"{name} historical error drift")
        req(result.get("unresolved_tie_count") == ties, f"{name} historical tie drift")

    req(((authority.get("authoritative_components") or {}).get("S3G2_ANNOUNCEMENT_LEDGER") or {}).get("ledger_sha256") == s3g2_sha, "S3G2 authority semantic hash drift")
    req((project.get("stage3") or {}).get("s3g2_semantic_ledger_sha256") == s3g2_sha, "project S3G2 semantic hash drift")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("STAGE3_AUTHORITY_MAP_V17_30_RUNTIME_V17_29_LAST_BASIS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
