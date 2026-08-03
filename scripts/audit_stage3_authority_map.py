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

    def req(cond: bool, message: str) -> None:
        if not cond:
            errors.append(message)

    expected_fp = "f17f7ab63f4532dda635eb7366e7df7bf5497a5ce814410105312bccb53125bb"
    expected_s3g2_sha = "0eb139572865628283f86c981990e59e076d5ef2a978a5967aace90d553e30dd"
    expected_s3g1j_digest = "sha256:410e257d7a3ada353926970f806abc3e970e5638f55c1dec7b47c71c57777721"
    expected_s3g1j_semantic_sha = "05b914b03dbcc23d3f6eca560189afbfe6ea427913f9cf1380fa09cdea6aa8d7"

    req(authority.get("schema_version") == 2, "authority map schema must be 2")
    req(authority.get("status") == "INTEGRATION_IN_PROGRESS", "authority map must remain INTEGRATION_IN_PROGRESS")
    req((authority.get("stage2_dependency") or {}).get("fingerprint") == expected_fp, "authority Stage2 fingerprint drift")
    req(lock.get("version") == "V3.3.9-stage3-final-lock", "Stage3 final-lock version drift")
    req(lock.get("status") == "NOT_READY", "Stage3 final lock must remain NOT_READY during clean integration")
    req((lock.get("stage2") or {}).get("fingerprint") == expected_fp, "Stage3 lock Stage2 fingerprint drift")
    req(project.get("schema_version") == 2, "project status schema must be 2")
    req(project.get("stage4_unlocked") is False, "project status unexpectedly unlocks Stage4")
    req(project.get("alpha_training_allowed") is False, "project status unexpectedly allows Alpha training")
    req(project.get("live_signal_allowed") is False, "project status unexpectedly allows live signals")

    expected_pending = {"S3G1J_FINANCIAL_RAW_VALUES", "S3G4_EARNINGS_SURPRISE"}
    req(set(lock.get("remaining_unlocked_gates") or []) == expected_pending, "Stage3 final-lock pending gate set drift")
    req(set((project.get("stage3") or {}).get("pending_final_gates") or []) == expected_pending, "project pending gate set drift")
    components = authority.get("authoritative_components") or {}
    for gate in expected_pending:
        req(gate in components, f"authority map missing pending gate {gate}")
        req((components.get(gate) or {}).get("final_gate") is False, f"pending gate {gate} incorrectly marked final")

    g1j = components.get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(authority.get("current_s3g1j_execution_pr") == 87, "current S3G1J execution PR must be #87")
    req(authority.get("current_s3g1j_governance_pr") == 88, "current S3G1J governance PR must be #88")
    req(g1j.get("accepted_execution_pr") == 87, "S3G1J authority does not point to execution PR #87")
    req(g1j.get("governance_closure_pr") == 88, "S3G1J authority does not point to governance PR #88")
    req(g1j.get("generation") == "V17.27", "S3G1J generation drift")
    req(g1j.get("accepted_head_sha") == "fa77d30a2ccdd3664beab01fd7ff7b5d16761726", "S3G1J accepted head drift")
    req(g1j.get("governed_integration_sha") == "606cff54e4d44c74a5a086ec2876c2528cb975ea", "S3G1J governed integration SHA drift")
    req(g1j.get("accepted_run_id") == 30806818977, "S3G1J accepted run drift")
    req(g1j.get("accepted_artifact_id") == 8854139999, "S3G1J artifact ID drift")
    req(g1j.get("accepted_artifact_digest") == expected_s3g1j_digest, "S3G1J artifact digest drift")
    req(g1j.get("document_count") == 121354, "S3G1J document count drift")
    req(g1j.get("numeric_observation_count") == 1051793, "S3G1J numeric count drift")
    req(g1j.get("document_error_count") == 1373, "S3G1J document-error count drift")
    req(g1j.get("unresolved_tie_count") == 1290, "S3G1J unresolved-tie count drift")
    req(g1j.get("target_numeric_rows") == 15, "S3G1J target numeric count drift")
    req(g1j.get("unexpected_document_regression_count") == 0, "S3G1J unexpected regression detected")
    req(g1j.get("existing_numeric_semantic_sha256") == expected_s3g1j_semantic_sha, "S3G1J existing numeric semantic SHA drift")
    req(g1j.get("execution_pass") is True, "S3G1J execution evidence is not PASS")
    req(g1j.get("document_non_regression_pass") is True, "S3G1J document non-regression not PASS")
    req(g1j.get("numeric_non_regression_pass") is True, "S3G1J numeric non-regression not PASS")
    req(g1j.get("status") == "FULL_BASIS_EXECUTION_ACCEPTED_FAIL_CLOSED", "S3G1J status drift")
    req(g1j.get("data_verdict") == "FAIL_CLOSED", "S3G1J data verdict must remain FAIL_CLOSED")
    req(g1j.get("final_gate") is False, "S3G1J fail-closed data incorrectly marked final PASS")

    lock_g1j = (lock.get("required_gates") or {}).get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(lock_g1j.get("run_id") == 30806818977, "Stage3 lock does not record accepted S3G1J run")
    req(lock_g1j.get("artifact_id") == 8854139999, "Stage3 lock S3G1J artifact ID drift")
    req(lock_g1j.get("artifact_digest") == expected_s3g1j_digest, "Stage3 lock S3G1J artifact digest drift")
    req(lock_g1j.get("execution_pass") is True, "Stage3 lock loses S3G1J execution PASS")
    req(lock_g1j.get("data_verdict") == "FAIL_CLOSED", "Stage3 lock S3G1J verdict drift")
    req(lock_g1j.get("final_gate_pass") is False, "Stage3 lock incorrectly unlocks S3G1J")
    req(lock_g1j.get("document_error_count") == 1373, "Stage3 lock S3G1J errors drift")
    req(lock_g1j.get("unresolved_tie_count") == 1290, "Stage3 lock S3G1J ties drift")

    project_g1j = ((project.get("stage3") or {}).get("s3g1j") or {})
    req(project_g1j.get("accepted_run_id") == 30806818977, "project status S3G1J run drift")
    req(project_g1j.get("execution_pass") is True, "project status loses S3G1J execution PASS")
    req(project_g1j.get("data_verdict") == "FAIL_CLOSED", "project status S3G1J data verdict drift")
    req(project_g1j.get("final_gate_pass") is False, "project status incorrectly marks S3G1J final")
    req(project_g1j.get("document_error_count") == 1373, "project status S3G1J error count drift")
    req(project_g1j.get("unresolved_tie_count") == 1290, "project status S3G1J tie count drift")

    s3g2 = components.get("S3G2_ANNOUNCEMENT_LEDGER") or {}
    req(s3g2.get("repair_source_pr") == 40, "S3G2 repair provenance does not point to PR #40")
    req(s3g2.get("status") == "FINAL_GATE_PASS_DETERMINISTIC" and s3g2.get("final_gate") is True, "S3G2 is not locked as deterministic final PASS")
    req(s3g2.get("deterministic_final_run_id") == 30522392946, "S3G2 deterministic final run drift")
    req(s3g2.get("ledger_sha256") == expected_s3g2_sha, "S3G2 deterministic ledger SHA drift")
    req(s3g2.get("deterministic_replay_count") == 2 and s3g2.get("deterministic_replay_same_sha") is True, "S3G2 reproducibility evidence missing")
    req(s3g2.get("artifact_digest_is_transport_only") is True, "S3G2 artifact digest incorrectly treated as dataset identity")
    transport = s3g2.get("transport_artifact_digests_observed") or []
    req(len(transport) == 2 and len(set(transport)) == 2, "S3G2 transport-digest evidence must record two archive instances")
    req(s3g2.get("security_identity_count") == 3402 and s3g2.get("g3_trading_days") == 2808, "S3G2 universe/calendar accounting drift")
    lock_g2 = (lock.get("required_gates") or {}).get("S3G2_ANNOUNCEMENT_LEDGER") or {}
    req(lock_g2.get("run_id") == 30522392946, "Stage3 final lock does not contain deterministic S3G2 run")
    req(lock_g2.get("ledger_sha256") == expected_s3g2_sha, "Stage3 lock/authority S3G2 semantic SHA mismatch")
    req(lock_g2.get("deterministic_replay_count") == 2, "Stage3 lock does not record two deterministic S3G2 replays")
    req(lock_g2.get("artifact_digest_is_transport_only") is True, "Stage3 lock treats S3G2 archive digest as semantic identity")

    s3g3b = components.get("S3G3B_INDUSTRY_LEDGER") or {}
    req(s3g3b.get("source_pr") == 35 and s3g3b.get("final_gate") is True, "S3G3B authority mismatch")

    evidence = set(authority.get("non_merge_evidence_prs") or [])
    superseded = set(authority.get("superseded_s3g1j_production_prs") or [])
    req(not (evidence & superseded), "diagnostic and superseded production PR sets overlap")
    req(63 in superseded, "V17.11 production PR #63 must be retained as superseded history")
    req(87 not in evidence and 87 not in superseded, "current S3G1J execution PR incorrectly archived")
    req(88 not in evidence and 88 not in superseded, "current S3G1J governance PR incorrectly archived")

    policy = authority.get("policy") or {}
    for key in (
        "diagnostic_prs_are_evidence_not_merge_units",
        "accepted_candidate_does_not_equal_final_pass",
        "accepted_full_basis_execution_does_not_equal_final_data_pass",
        "artifact_archive_digest_is_transport_not_dataset_identity",
        "no_accounting_tolerance_relaxation",
        "no_pit_relaxation",
        "no_security_identity_relaxation",
        "unreliable_parse_remains_fail_closed",
    ):
        req(policy.get(key) is True, f"required Stage3 governance policy disabled: {key}")

    report = {
        "gate": "STAGE3_AUTHORITY_MAP",
        "pass": not errors,
        "stage3_status": lock.get("status"),
        "pending_final_gates": sorted(expected_pending),
        "s3g1j_generation": g1j.get("generation"),
        "s3g1j_accepted_run": g1j.get("accepted_run_id"),
        "s3g1j_execution_pass": g1j.get("execution_pass"),
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
