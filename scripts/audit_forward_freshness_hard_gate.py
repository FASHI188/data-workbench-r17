#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase1", required=True)
    ap.add_argument("--phase2", required=True)
    ap.add_argument("--phase3", required=True)
    ap.add_argument("--phase4", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--target-session", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    p1 = load(Path(a.phase1))
    p2 = load(Path(a.phase2))
    p3 = load(Path(a.phase3))
    p4 = load(Path(a.phase4))
    policy = load(Path(a.policy))
    target = a.target_session
    p2a = p2.get("forward_ohlcv") or {}
    p3a = p3.get("audit") or {}
    p4a = p4.get("audit") or {}

    checks = {
        "policy_fail_closed": policy.get("fail_closed") is True,
        "phase1_pass": p1.get("phase1_pass") is True,
        "current_master_at_target": p1.get("current_master_as_of") == target,
        "lifecycle_forward_pass": p1.get("lifecycle_forward_pass") is True,
        "phase2_ohlcv_pass": p2.get("phase2_pass") is True and p2a.get("pass") is True,
        "ohlcv_at_target": p2a.get("coverage_end") == target and p2a.get("last_trading_day") == target,
        "phase2_errors_empty": not p2a.get("errors"),
        "phase3_actions_pass": p3.get("phase3_pass") is True and p3a.get("pass") is True,
        "actions_at_target": p3a.get("current_session") == target,
        "actions_known_next_session_covered": int(p3a.get("known_next_session_actions", -1)) >= 0 and bool(p3a.get("next_session")),
        "phase3_errors_empty": not p3a.get("errors"),
        "phase4_financial_announcements_pass": p4.get("phase4_pass") is True and p4a.get("pass") is True,
        "financial_announcements_at_target": p4a.get("coverage_end") == target,
        "all_selected_reports_have_original_pdf_sha": p4a.get("all_selected_reports_have_original_pdf_source_sha") is True,
        "retained_financial_errors_are_missing": p4a.get("retained_errors_are_missing_not_numeric_truth") is True,
        "phase4_errors_empty": not p4a.get("errors"),
        "same_phase1_anchor_p2_p3_p4": p2.get("phase1_anchor_artifact") == p3.get("phase1_artifact") == p4.get("phase1_artifact"),
        "same_phase1_digest_p2_p3_p4": p2.get("phase1_anchor_digest") == p3.get("phase1_digest") == p4.get("phase1_digest"),
        "phase4_pins_phase2": p4.get("phase2_artifact") is not None and p4.get("phase2_digest") is not None,
        "phase4_pins_phase3": p4.get("phase3_artifact") is not None and p4.get("phase3_digest") is not None,
    }
    errors = [k for k, v in checks.items() if not v]
    result = {
        "gate": "FRESHNESS_V2_FOUR_FAMILY_HARD_GATE",
        "pass": not errors,
        "target_mode": "STAGE4_RESEARCH_TRAINING_PREPARATION",
        "target_session": target,
        "checks": checks,
        "failed_checks": errors,
        "evidence": {
            "phase1_sha256": sha(Path(a.phase1).read_bytes()),
            "phase2_sha256": sha(Path(a.phase2).read_bytes()),
            "phase3_sha256": sha(Path(a.phase3).read_bytes()),
            "phase4_sha256": sha(Path(a.phase4).read_bytes()),
            "policy_sha256": sha(Path(a.policy).read_bytes()),
        },
        "stage4_research_unlocked": not errors,
        "alpha_training_allowed": False,
        "live_signal_allowed": False,
        "authoritative": False,
        "meaning": "PASS permits beginning Market Regime and Stage4 V1 feature work on the pinned frozen+forward evidence basis. It does not promote forward artifacts into frozen Stage2/Stage3, authorize Alpha training, or authorize live signals.",
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
