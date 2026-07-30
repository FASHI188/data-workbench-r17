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
    req(authority.get("status") == "INTEGRATION_IN_PROGRESS", "authority map must remain INTEGRATION_IN_PROGRESS")
    req((authority.get("stage2_dependency") or {}).get("fingerprint") == expected_fp, "authority Stage2 fingerprint drift")
    req(lock.get("status") == "NOT_READY", "Stage3 final lock must remain NOT_READY during clean integration")
    req((lock.get("stage2") or {}).get("fingerprint") == expected_fp, "Stage3 lock Stage2 fingerprint drift")
    req(project.get("stage4_unlocked") is False, "project status unexpectedly unlocks Stage4")
    req(project.get("alpha_training_allowed") is False, "project status unexpectedly allows Alpha training")
    req(project.get("live_signal_allowed") is False, "project status unexpectedly allows live signals")

    expected_pending = {"S3G1J_FINANCIAL_RAW_VALUES", "S3G4_EARNINGS_SURPRISE"}
    req(set(lock.get("remaining_unlocked_gates") or []) == expected_pending, "Stage3 final-lock pending gate set drift")
    components = authority.get("authoritative_components") or {}
    for gate in expected_pending:
        req(gate in components, f"authority map missing pending gate {gate}")
        req((components.get(gate) or {}).get("final_gate") is False, f"pending gate {gate} incorrectly marked final")

    g1j = components.get("S3G1J_FINANCIAL_RAW_VALUES") or {}
    req(authority.get("current_s3g1j_production_pr") == 63, "current S3G1J production PR must be #63")
    req(g1j.get("source_pr") == 63, "S3G1J authority does not point to PR #63")
    req(g1j.get("head_sha") == "e98d26b962a58cecc5c6416214e3c798c5e8a49e", "S3G1J accepted head drift")
    accounting = g1j.get("accepted_candidate_accounting") or {}
    req(accounting.get("v14_remaining") == 113, "S3G1J V14 residual baseline drift")
    req(accounting.get("v17_11_recovered") == 31, "S3G1J V17.11 recovery count drift")
    req(accounting.get("v17_11_remaining_fail_closed") == 82, "S3G1J fail-closed residual count drift")
    req(31 + 82 == 113, "S3G1J accepted accounting does not close")

    s3g2 = components.get("S3G2_ANNOUNCEMENT_LEDGER") or {}
    req(s3g2.get("repair_source_pr") == 40, "S3G2 repair provenance does not point to PR #40")
    req(s3g2.get("status") == "FINAL_GATE_PASS_DETERMINISTIC" and s3g2.get("final_gate") is True, "S3G2 is not locked as deterministic final PASS")
    req(s3g2.get("deterministic_final_run_id") == 30522392946, "S3G2 deterministic final run drift")
    req(s3g2.get("ledger_sha256") == expected_s3g2_sha, "S3G2 deterministic ledger SHA drift")
    req(s3g2.get("deterministic_replay_count") == 2 and s3g2.get("deterministic_replay_same_sha") is True, "S3G2 two-run reproducibility evidence missing")
    req(s3g2.get("artifact_digest_is_transport_only") is True, "S3G2 artifact digest incorrectly treated as dataset identity")
    transport = s3g2.get("transport_artifact_digests_observed") or []
    req(len(transport) == 2 and len(set(transport)) == 2, "S3G2 transport-digest evidence must record the two distinct archive instances")
    req(s3g2.get("security_identity_count") == 3402 and s3g2.get("g3_trading_days") == 2808, "S3G2 universe/calendar accounting drift")
    lock_g2 = (lock.get("required_gates") or {}).get("S3G2_ANNOUNCEMENT_LEDGER") or {}
    req(lock_g2.get("run_id") == 30522392946, "Stage3 final lock does not contain deterministic S3G2 run")
    req(lock_g2.get("ledger_sha256") == expected_s3g2_sha, "Stage3 lock/authority S3G2 semantic SHA mismatch")
    req(lock_g2.get("deterministic_replay_count") == 2, "Stage3 lock does not record two deterministic S3G2 replays")
    req(lock_g2.get("artifact_digest_is_transport_only") is True, "Stage3 lock still treats S3G2 archive digest as semantic identity")

    s3g3b = components.get("S3G3B_INDUSTRY_LEDGER") or {}
    req(s3g3b.get("source_pr") == 35 and s3g3b.get("final_gate") is True, "S3G3B authority mismatch")

    evidence = set(authority.get("non_merge_evidence_prs") or [])
    superseded = set(authority.get("superseded_s3g1j_production_prs") or [])
    req(not (evidence & superseded), "diagnostic and superseded production PR sets overlap")
    req(63 not in evidence and 63 not in superseded, "current S3G1J PR is incorrectly archived/superseded")

    policy = authority.get("policy") or {}
    for key in (
        "diagnostic_prs_are_evidence_not_merge_units",
        "accepted_candidate_does_not_equal_final_pass",
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
        "s3g2_final_run": s3g2.get("deterministic_final_run_id"),
        "s3g2_ledger_sha256": s3g2.get("ledger_sha256"),
        "s3g2_deterministic_replay_count": s3g2.get("deterministic_replay_count"),
        "current_s3g1j_pr": authority.get("current_s3g1j_production_pr"),
        "s3g1j_candidate_recovered": accounting.get("v17_11_recovered"),
        "s3g1j_candidate_remaining_fail_closed": accounting.get("v17_11_remaining_fail_closed"),
        "stage4_unlocked": project.get("stage4_unlocked"),
        "alpha_training_allowed": project.get("alpha_training_allowed"),
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
