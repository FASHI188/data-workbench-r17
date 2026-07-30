#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--project-status", default="data/project_status.json")
    ap.add_argument("--stage2-manifest", default="data/stage2_final/manifest.json")
    ap.add_argument("--legacy-stage2-audit", default="data/stage2_audit.json")
    ap.add_argument("--freshness-policy", default="config/data_freshness_policy.json")
    ap.add_argument("--current-master", default="data/current_master/manifest.json")
    args = ap.parse_args()

    errors: list[str] = []
    as_of = date.fromisoformat(args.as_of)
    project_status = load_json(ROOT / args.project_status)
    stage2 = load_json(ROOT / args.stage2_manifest)
    legacy = load_json(ROOT / args.legacy_stage2_audit)
    freshness_policy = load_json(ROOT / args.freshness_policy)
    current_master = load_json(ROOT / args.current_master)

    require(errors, project_status.get("authoritative") is True, "project status is not authoritative")
    require(errors, project_status.get("project_phase") in {"RESEARCH_ONLY", "TRAINING_READY", "LIVE_READY"}, "unknown project phase")

    stage2_pass = (
        stage2.get("version") == "V3.2.25-stage2-final-freeze"
        and stage2.get("status") == "PASS"
        and stage2.get("all_hard_gates_pass") is True
        and not stage2.get("errors")
        and bool(stage2.get("stage2_dataset_fingerprint"))
    )
    require(errors, stage2_pass, "authoritative Stage2 final manifest is not a clean PASS")
    require(
        errors,
        (project_status.get("stage2") or {}).get("authoritative_manifest") == args.stage2_manifest,
        "project status does not point to the authoritative Stage2 final manifest",
    )
    require(
        errors,
        (project_status.get("stage2") or {}).get("dataset_fingerprint") == stage2.get("stage2_dataset_fingerprint"),
        "project status Stage2 fingerprint does not match final manifest",
    )

    require(errors, legacy.get("status") == "SUPERSEDED", "legacy data/stage2_audit.json is not marked SUPERSEDED")
    require(errors, legacy.get("authoritative") is False, "legacy Stage2 audit is still marked authoritative")
    require(errors, legacy.get("superseded_by") == args.stage2_manifest, "legacy Stage2 audit points to the wrong successor")

    coverage_end_s = str((stage2.get("fingerprint_basis") or {}).get("coverage_end") or "")
    require(errors, bool(coverage_end_s), "Stage2 final manifest has no coverage_end")
    coverage_end = date.fromisoformat(coverage_end_s) if coverage_end_s else as_of

    current_master_as_of_s = str((current_master.get("szse") or {}).get("as_of") or "")
    require(errors, bool(current_master_as_of_s), "current master has no SZSE as_of date")
    current_master_as_of = date.fromisoformat(current_master_as_of_s) if current_master_as_of_s else coverage_end

    threshold = int(
        (((freshness_policy.get("policy") or {}).get("ohlcv") or {}).get("calendar_day_hard_stale_threshold") or 0)
    )
    require(errors, threshold > 0, "freshness policy has no positive hard stale threshold")
    coverage_lag_days = (as_of - coverage_end).days
    master_lag_days = (as_of - current_master_as_of).days
    hard_stale = coverage_lag_days > threshold or master_lag_days > threshold

    stage3_info = project_status.get("stage3") or {}
    stage3_manifest_rel = str(stage3_info.get("authoritative_final_manifest") or "data/stage3_final/manifest.json")
    stage3_manifest_path = ROOT / stage3_manifest_rel
    stage3_final_pass = False
    if stage3_manifest_path.exists():
        stage3_manifest = load_json(stage3_manifest_path)
        stage3_final_pass = (
            stage3_manifest.get("status") == "PASS"
            and stage3_manifest.get("all_hard_gates_pass") is True
            and not stage3_manifest.get("errors")
        )
    else:
        require(errors, stage3_info.get("status") == "NOT_READY", "Stage3 final manifest is absent but project status is not NOT_READY")
        require(errors, stage3_info.get("final_manifest_present_on_main") is False, "project status incorrectly claims a Stage3 final manifest exists")

    unlock = project_status.get("unlock_requirements") or {}
    reproducibility_pass = unlock.get("reproducibility_pass") is True
    freshness_pass = (not hard_stale) and unlock.get("freshness_pass") is True
    derived_stage4 = stage2_pass and stage3_final_pass and freshness_pass and reproducibility_pass
    derived_alpha = derived_stage4
    derived_live = derived_alpha and freshness_pass

    if hard_stale:
        require(errors, (project_status.get("freshness") or {}).get("status") == "STALE", "data is hard-stale but project status does not say STALE")
        require(errors, project_status.get("alpha_training_allowed") is False, "hard-stale data must block Alpha training")
        require(errors, project_status.get("live_signal_allowed") is False, "hard-stale data must block live signals")

    if project_status.get("stage4_unlocked") is True and not derived_stage4:
        errors.append("project status unlocks Stage4 without complete Stage2+Stage3+freshness+reproducibility evidence")
    if project_status.get("alpha_training_allowed") is True and not derived_alpha:
        errors.append("project status allows Alpha training without complete project-level evidence")
    if project_status.get("live_signal_allowed") is True and not derived_live:
        errors.append("project status allows live signals without complete project-level evidence")

    report = {
        "gate": "PROJECT_READINESS_GOVERNANCE",
        "pass": not errors,
        "as_of": as_of.isoformat(),
        "stage2_final_pass": stage2_pass,
        "stage2_fingerprint": stage2.get("stage2_dataset_fingerprint"),
        "stage3_final_manifest_present": stage3_manifest_path.exists(),
        "stage3_final_pass": stage3_final_pass,
        "coverage_end": coverage_end.isoformat(),
        "coverage_lag_days": coverage_lag_days,
        "current_master_as_of": current_master_as_of.isoformat(),
        "current_master_lag_days": master_lag_days,
        "hard_stale": hard_stale,
        "derived_stage4_unlocked": derived_stage4,
        "derived_alpha_training_allowed": derived_alpha,
        "derived_live_signal_allowed": derived_live,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
