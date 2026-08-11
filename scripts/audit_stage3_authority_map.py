#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []

    def req(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    authority = load("governance/stage3_authority_map.json")
    runtime = load("governance/stage3_s3g1j_runtime_manifest.json")
    activation = load("governance/stage3_workflow_activation_manifest.json")
    lock = load("config/stage3_final_lock.json")
    project = load("data/project_status.json")
    promotion = load("governance/stage3_s3g1j_v17_30_runtime_promotion.json")
    wrapper = load("governance/stage3_s3g1j_v17_30_runtime_wrapper_acceptance.json")
    v29 = load("governance/stage3_s3g1j_v17_29_full_final.json")
    v28 = load("governance/stage3_s3g1j_v17_28_full_final.json")
    v27 = load("governance/stage3_s3g1j_v17_27_full_final.json")
    v26 = load("governance/stage3_s3g1j_v17_26_full_final.json")

    v30_wrapper_digest = "sha256:232b2e4a6c64b271193853d4e8fd32c0fdfd367344ecec720902fe8f090333dc"
    v29_digest = "sha256:71a4daa6c8372f3d64080b5fa5b787914292d889da7051de699eb6610189c726"

    req(authority.get("schema_version") == 7, "authority schema drift")
    req(runtime.get("schema_version") == 14, "runtime schema drift")
    req(activation.get("schema_version") == 16, "activation schema drift")
    req(lock.get("version") == "V3.3.14-stage3-final-lock", "final-lock version drift")
    req(project.get("schema_version") == 7, "project schema drift")

    wpr = wrapper.get("execution_pr") or {}
    wrun = wrapper.get("accepted_run") or {}
    wauth = wrapper.get("authorization") or {}
    req(wpr.get("number") == 123, "wrapper PR drift")
    req(wpr.get("final_head_sha") == "d26d7f543c20d717ed8c8a421e28838feecd7a03", "wrapper head drift")
    req(wpr.get("closed_without_merge") is True, "wrapper PR must stay closed/unmerged")
    req(wrun.get("run_id") == 31458469699, "wrapper run drift")
    req(wrun.get("artifact_id") == 9088925988, "wrapper artifact ID drift")
    req(wrun.get("artifact_digest") == v30_wrapper_digest, "wrapper artifact digest drift")
    req(wauth.get("formal_v17_30_runtime_promotion_governance_eligible") is True, "registered wrapper not promotion eligible")
    req(wauth.get("v17_30_runtime_authority_activated") is False, "wrapper evidence itself must not activate V17.30")
    req(wauth.get("fresh_v17_30_full_basis_execution_authorized") is False, "wrapper evidence must not authorize full basis")

    formal = runtime.get("formal_runtime") or {}
    current = runtime.get("current_production_authority") or {}
    latest = runtime.get("full_basis_last_completed_final") or {}
    next_basis = runtime.get("next_full_basis_required") or {}
    req(current.get("generation") == "V17.30", "current runtime authority must be V17.30")
    req(formal.get("runtime_generation") == "V17.30", "formal runtime must be V17.30")
    req(formal.get("parser_git_blob") == "cc782817e5ee73fcae085d71f4896a0adc004dcd", "V17.30 parser blob drift")
    req(formal.get("extractor_git_blob") == "d74a2b1f8f0ec3af8d89ce259e83392d7f8cc20c", "V17.30 extractor blob drift")
    req(formal.get("promotion_safety_parser_git_blob") == "1a4364d5cde7881455902f6fa1dbe5e68f3843a6", "V17.30 helper blob drift")
    req(latest.get("generation") == "V17.29", "last completed basis must remain V17.29")
    req(latest.get("run") == 31389854868, "V17.29 last basis run drift")
    req(latest.get("artifact_id") == 9063271903, "V17.29 last basis artifact drift")
    req(latest.get("artifact_digest") == v29_digest, "V17.29 last basis digest drift")
    req(latest.get("numeric_observations") == 1051820, "V17.29 numeric count drift")
    req(latest.get("document_error_count") == 1364, "V17.29 error count drift")
    req(latest.get("unresolved_tie_count") == 1281, "V17.29 tie count drift")
    req(latest.get("verdict") == "FAIL_CLOSED", "V17.29 data verdict drift")
    req(next_basis.get("generation") == "V17.30", "next basis must be V17.30")
    req(next_basis.get("status") == "REQUIRED_NOT_STARTED", "V17.30 full basis must remain not started")
    req(next_basis.get("expected_numeric_observations") == 1051826, "V17.30 expected numeric drift")
    req(next_basis.get("expected_document_error_count") == 1362, "V17.30 expected error drift")
    req(next_basis.get("expected_unresolved_tie_count") == 1279, "V17.30 expected tie drift")
    req(next_basis.get("expected_values_are_not_production_acceptance") is True, "V17.30 expectations mislabeled as accepted")

    promo_next = promotion.get("next_full_basis") or {}
    promo_hard = promotion.get("hard_boundaries") or {}
    req(promotion.get("generation") == "V17.30", "promotion generation drift")
    req(promotion.get("governance_pr") == 125, "promotion PR drift")
    req(promo_next.get("status") == "REQUIRED_NOT_STARTED", "promotion unexpectedly started full basis")
    req(promo_next.get("expected_values_are_not_production_acceptance") is True, "promotion expectation boundary drift")
    req(promo_hard.get("fresh_64_shard_execution_started") is False, "promotion started fresh 64-shard execution")
    req(promo_hard.get("stage3_status") == "NOT_READY", "promotion incorrectly unlocks Stage3")

    active = activation.get("accepted_production_runtime") or {}
    req(active.get("generation") == "V17.30", "activation runtime drift")
    req(active.get("full_basis_execution_pending") is True, "activation must require V17.30 full basis")
    req(active.get("last_completed_full_basis_generation") == "V17.29", "activation last basis drift")
    req(active.get("last_completed_full_basis_run") == 31389854868, "activation V17.29 run drift")
    req(active.get("last_completed_full_basis_artifact_digest") == v29_digest, "activation V17.29 digest drift")
    req(active.get("data_verdict") == "FAIL_CLOSED", "activation data verdict drift")
    req((activation.get("accepted_v17_29_full_basis_evidence") or {}).get("last_completed_full_basis_authority") is True, "V17.29 must remain last completed basis authority")
    req((activation.get("accepted_v17_28_full_basis_evidence") or {}).get("historical_full_basis_authority_retained") is True, "V17.28 history not retained")
    req((activation.get("accepted_v17_27_full_basis_evidence") or {}).get("historical_full_basis_authority_retained") is True, "V17.27 history not retained")
    req((activation.get("accepted_v17_26_full_basis_evidence") or {}).get("historical_full_basis_authority_retained") is True, "V17.26 history not retained")

    g1j = (authority.get("authoritative_components") or {}).get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(g1j.get("formal_runtime_generation") == "V17.30", "authority map runtime drift")
    req(g1j.get("last_completed_full_basis_generation") == "V17.29", "authority map last basis drift")
    req(g1j.get("accepted_run_id") == 31389854868, "authority map V17.29 run drift")
    req(g1j.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "authority map next basis drift")
    req(g1j.get("expected_values_are_not_production_acceptance") is True, "authority map expectation boundary drift")
    req(g1j.get("final_gate") is False, "authority map incorrectly passes S3G1J")

    lock_g1j = (lock.get("required_gates") or {}).get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(lock.get("status") == "NOT_READY", "Stage3 final lock must remain NOT_READY")
    req(lock_g1j.get("formal_runtime_generation") == "V17.30", "final lock runtime drift")
    req(lock_g1j.get("last_completed_full_basis_generation") == "V17.29", "final lock last basis drift")
    req(lock_g1j.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "final lock next basis drift")
    req(lock_g1j.get("final_gate_pass") is False, "final lock incorrectly passes S3G1J")

    pg1j = ((project.get("stage3") or {}).get("s3g1j") or {})
    req((project.get("stage3") or {}).get("status") == "NOT_READY", "project Stage3 must remain NOT_READY")
    req(project.get("stage4_unlocked") is False, "Stage4 unexpectedly unlocked")
    req(project.get("alpha_training_allowed") is False, "Alpha training unexpectedly allowed")
    req(project.get("live_signal_allowed") is False, "live signals unexpectedly allowed")
    req(pg1j.get("formal_runtime_generation") == "V17.30", "project runtime drift")
    req(pg1j.get("last_completed_full_basis_generation") == "V17.29", "project last basis drift")
    req(pg1j.get("next_full_basis_status") == "REQUIRED_NOT_STARTED", "project next basis drift")
    req(pg1j.get("expected_values_are_not_production_acceptance") is True, "project expectation boundary drift")
    req(pg1j.get("final_gate_pass") is False, "project incorrectly passes S3G1J")

    for name, evidence, run_id, artifact_id, numeric, errors_count, ties in (
        ("V17.29", v29, 31389854868, 9063271903, 1051820, 1364, 1281),
        ("V17.28", v28, 30997260730, 8927455692, 1051799, 1371, 1288),
        ("V17.27", v27, 30806818977, 8854139999, 1051793, 1373, 1290),
        ("V17.26", v26, 30733013665, 8828600783, 1051778, 1378, 1295),
    ):
        accepted = evidence.get("accepted_run") or {}
        result = evidence.get("full_basis_result") or {}
        req(accepted.get("run_id") == run_id, f"{name} historical run drift")
        req(accepted.get("artifact_id") == artifact_id, f"{name} historical artifact drift")
        req(result.get("numeric_observation_count") == numeric, f"{name} historical numeric drift")
        req(result.get("document_error_count") == errors_count, f"{name} historical errors drift")
        req(result.get("unresolved_tie_count") == ties, f"{name} historical ties drift")
        req(result.get("final_data_verdict") == "FAIL_CLOSED", f"{name} historical verdict drift")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("STAGE3_AUTHORITY_MAP_V17_30_RUNTIME_V17_29_LAST_BASIS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
