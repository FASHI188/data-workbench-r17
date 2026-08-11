#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V30_RUN = 31518370789
V30_HEAD = "a18b81a9f38692533d0427f4a5b50767abf1a7c8"
V30_ARTIFACT_ID = 9112098872
V30_DIGEST = "sha256:706c6dd7252a64fd5c2956df6c594b5c91de29f02ca7d0553fa932017e8867ba"
V29_RUN = 31389854868
V29_ARTIFACT_ID = 9063271903
V29_DIGEST = "sha256:71a4daa6c8372f3d64080b5fa5b787914292d889da7051de699eb6610189c726"


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []

    def req(ok: bool, message: str) -> None:
        if not ok:
            errors.append(message)

    authority = load("governance/stage3_authority_map.json")
    runtime = load("governance/stage3_s3g1j_runtime_manifest.json")
    activation = load("governance/stage3_workflow_activation_manifest.json")
    lock = load("config/stage3_final_lock.json")
    project = load("data/project_status.json")
    promotion = load("governance/stage3_s3g1j_v17_30_runtime_promotion.json")
    wrapper = load("governance/stage3_s3g1j_v17_30_runtime_wrapper_acceptance.json")
    v30 = load("governance/stage3_s3g1j_v17_30_full_final.json")
    v29 = load("governance/stage3_s3g1j_v17_29_full_final.json")
    v28 = load("governance/stage3_s3g1j_v17_28_full_final.json")
    v27 = load("governance/stage3_s3g1j_v17_27_full_final.json")
    v26 = load("governance/stage3_s3g1j_v17_26_full_final.json")

    req(authority.get("schema_version") == 8, "authority schema drift")
    req(runtime.get("schema_version") == 15, "runtime schema drift")
    req(activation.get("schema_version") == 17, "activation schema drift")
    req(lock.get("version") == "V3.3.15-stage3-final-lock", "final-lock version drift")
    req(project.get("schema_version") == 8, "project schema drift")

    formal = runtime.get("formal_runtime") or {}
    current = runtime.get("current_production_authority") or {}
    latest = runtime.get("full_basis_last_completed_final") or {}
    next_basis = runtime.get("next_full_basis_required") or {}
    req(current.get("generation") == "V17.30", "current runtime authority must be V17.30")
    req(formal.get("runtime_generation") == "V17.30", "formal runtime must be V17.30")
    req(formal.get("parser_git_blob") == "cc782817e5ee73fcae085d71f4896a0adc004dcd", "V17.30 parser blob drift")
    req(formal.get("extractor_git_blob") == "d74a2b1f8f0ec3af8d89ce259e83392d7f8cc20c", "V17.30 extractor blob drift")
    req(formal.get("promotion_safety_parser_git_blob") == "1a4364d5cde7881455902f6fa1dbe5e68f3843a6", "V17.30 helper blob drift")
    req(latest.get("generation") == "V17.30", "latest completed basis must be V17.30")
    req(latest.get("run") == V30_RUN, "V17.30 latest run drift")
    req(latest.get("head_sha") == V30_HEAD, "V17.30 latest head drift")
    req(latest.get("artifact_id") == V30_ARTIFACT_ID, "V17.30 latest artifact drift")
    req(latest.get("artifact_digest") == V30_DIGEST, "V17.30 latest digest drift")
    req(latest.get("document_rows") == 121354, "V17.30 document count drift")
    req(latest.get("numeric_observations") == 1051826, "V17.30 numeric count drift")
    req(latest.get("document_error_count") == 1362, "V17.30 error count drift")
    req(latest.get("unresolved_tie_count") == 1279, "V17.30 tie count drift")
    req(latest.get("verdict") == "FAIL_CLOSED", "V17.30 data verdict drift")
    req(next_basis.get("generation") is None, "next basis must be empty after current acceptance")
    req(next_basis.get("status") == "NONE_CURRENT_RUNTIME_ACCEPTED", "next basis status drift")

    # Promotion evidence is immutable history: at promotion time the full basis had not started.
    promo_next = promotion.get("next_full_basis") or {}
    promo_hard = promotion.get("hard_boundaries") or {}
    req(promotion.get("generation") == "V17.30", "promotion generation drift")
    req(promotion.get("governance_pr") == 125, "promotion PR drift")
    req(promo_next.get("status") == "REQUIRED_NOT_STARTED", "historical promotion state drift")
    req(promo_next.get("expected_values_are_not_production_acceptance") is True, "historical promotion expectation boundary drift")
    req(promo_hard.get("fresh_64_shard_execution_started") is False, "historical promotion execution-state drift")

    wpr = wrapper.get("execution_pr") or {}
    wrun = wrapper.get("accepted_run") or {}
    req(wpr.get("number") == 123 and wpr.get("closed_without_merge") is True, "runtime wrapper PR drift")
    req(wrun.get("run_id") == 31458469699, "runtime wrapper run drift")

    active = activation.get("accepted_production_runtime") or {}
    req(active.get("generation") == "V17.30", "activation runtime drift")
    req(active.get("full_basis_execution_pending") is False, "activation incorrectly marks full basis pending")
    req(active.get("last_completed_full_basis_generation") == "V17.30", "activation latest basis drift")
    req(active.get("last_completed_full_basis_run") == V30_RUN, "activation latest run drift")
    req(active.get("last_completed_full_basis_artifact_digest") == V30_DIGEST, "activation latest digest drift")
    req(active.get("data_verdict") == "FAIL_CLOSED", "activation data verdict drift")
    v30a = activation.get("accepted_v17_30_full_basis_evidence") or {}
    v29a = activation.get("accepted_v17_29_full_basis_evidence") or {}
    req(v30a.get("last_completed_full_basis_authority") is True, "V17.30 activation authority missing")
    req(v29a.get("last_completed_full_basis_authority") is False, "V17.29 must no longer be latest authority")
    req(v29a.get("historical_full_basis_authority_retained") is True, "V17.29 history not retained")
    for key in ("accepted_v17_28_full_basis_evidence", "accepted_v17_27_full_basis_evidence", "accepted_v17_26_full_basis_evidence"):
        req((activation.get(key) or {}).get("historical_full_basis_authority_retained") is True, f"{key} history not retained")

    g1j = (authority.get("authoritative_components") or {}).get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(g1j.get("formal_runtime_generation") == "V17.30", "authority map runtime drift")
    req(g1j.get("last_completed_full_basis_generation") == "V17.30", "authority map latest basis drift")
    req(g1j.get("accepted_run_id") == V30_RUN, "authority map accepted run drift")
    req(g1j.get("accepted_artifact_id") == V30_ARTIFACT_ID, "authority map artifact drift")
    req(g1j.get("accepted_artifact_digest") == V30_DIGEST, "authority map digest drift")
    req(g1j.get("data_verdict") == "FAIL_CLOSED", "authority map data verdict drift")
    req(g1j.get("final_gate") is False, "authority map incorrectly passes S3G1J")
    prev = g1j.get("previous_full_basis_authority") or {}
    req(prev.get("generation") == "V17.29" and prev.get("run") == V29_RUN and prev.get("artifact_id") == V29_ARTIFACT_ID and prev.get("artifact_digest") == V29_DIGEST, "authority map V17.29 history drift")

    lock_g1j = (lock.get("required_gates") or {}).get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(lock.get("status") == "NOT_READY", "Stage3 final lock must remain NOT_READY")
    req(lock_g1j.get("formal_runtime_generation") == "V17.30", "final lock runtime drift")
    req(lock_g1j.get("last_completed_full_basis_generation") == "V17.30", "final lock latest basis drift")
    req(lock_g1j.get("run_id") == V30_RUN and lock_g1j.get("artifact_id") == V30_ARTIFACT_ID, "final lock authority drift")
    req(lock_g1j.get("data_verdict") == "FAIL_CLOSED", "final lock data verdict drift")
    req(lock_g1j.get("final_gate_pass") is False, "final lock incorrectly passes S3G1J")

    stage3 = project.get("stage3") or {}
    pg1j = stage3.get("s3g1j") or {}
    req(stage3.get("status") == "NOT_READY", "project Stage3 must remain NOT_READY")
    req(project.get("stage4_unlocked") is False, "Stage4 unexpectedly unlocked")
    req(project.get("alpha_training_allowed") is False, "Alpha training unexpectedly allowed")
    req(project.get("live_signal_allowed") is False, "live signals unexpectedly allowed")
    req(pg1j.get("formal_runtime_generation") == "V17.30", "project runtime drift")
    req(pg1j.get("last_completed_full_basis_generation") == "V17.30", "project latest basis drift")
    req(pg1j.get("accepted_run_id") == V30_RUN and pg1j.get("accepted_artifact_id") == V30_ARTIFACT_ID, "project accepted authority drift")
    req(pg1j.get("data_verdict") == "FAIL_CLOSED", "project data verdict drift")
    req(pg1j.get("final_gate_pass") is False, "project incorrectly passes S3G1J")

    # Append-only historical evidence: exact values must not be rewritten when latest pointer advances.
    for name, evidence, run_id, artifact_id, numeric, err_count, ties in (
        ("V17.30", v30, V30_RUN, V30_ARTIFACT_ID, 1051826, 1362, 1279),
        ("V17.29", v29, V29_RUN, V29_ARTIFACT_ID, 1051820, 1364, 1281),
        ("V17.28", v28, 30997260730, 8927455692, 1051799, 1371, 1288),
        ("V17.27", v27, 30806818977, 8854139999, 1051793, 1373, 1290),
        ("V17.26", v26, 30733013665, 8828600783, 1051778, 1378, 1295),
    ):
        accepted = evidence.get("accepted_run") or {}
        result = evidence.get("full_basis_result") or {}
        req(accepted.get("run_id") == run_id, f"{name} historical run drift")
        req(accepted.get("artifact_id") == artifact_id, f"{name} historical artifact drift")
        req(result.get("numeric_observation_count") == numeric, f"{name} historical numeric drift")
        req(result.get("document_error_count") == err_count, f"{name} historical errors drift")
        req(result.get("unresolved_tie_count") == ties, f"{name} historical ties drift")
        req(result.get("final_data_verdict") == "FAIL_CLOSED", f"{name} historical verdict drift")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("STAGE3_AUTHORITY_MAP_V17_30_FULL_BASIS_LATEST_HISTORY_RETAINED_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
