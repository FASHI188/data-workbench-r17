#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> int:
    c = load("governance/stage4_v1_feature_set_contract.json")
    s2 = load("data/stage2_final/manifest.json")
    s3 = load("data/stage3_final/manifest.json")
    market = load("governance/market_regime_v1_module_manifest.json")
    accepted = load("governance/stage4_market_regime_v1_accepted_promotion.json")
    registry = load("governance/extension_module_registry.json")
    s10 = load("governance/stage4_v1_feature_set_v1_0_supersession.json")
    s11 = load("governance/stage4_v1_feature_set_v1_1_supersession.json")
    b = c["fingerprint_basis"]
    families = {r["family_id"]: r for r in b["feature_families"]}
    industry = families["INDUSTRY_IDENTITY_PIT"]
    surprise = families["EARNINGS_GUIDANCE_SURPRISE_PIT"]
    canonical = json.dumps(b, sort_keys=True, separators=(",", ":")).encode()
    modules = registry["modules"]
    module_fp = hashlib.sha256(json.dumps(modules, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    checks = {
      "fingerprint_exact": hashlib.sha256(canonical).hexdigest() == c["feature_set_fingerprint"] == "d319ea1c236d580d0d032a055e4cdc07bf45e586ecbef664c6f4b3a8be98f9ff",
      "v1_2_supersedes_v1_1": c["feature_set_version"] == "V1.2" and c["supersedes_feature_set_version"] == "V1.1" and s11["superseded_fingerprint"] == "757d384cd090620cb8a351b8bcf6d93884577c74dd4fb874bb2f7880e0c939a3",
      "v1_0_history_preserved": s10["superseded_fingerprint"] == "dab3ffc74a518fd0a75a3a63b0717354162820d1f5ab0cb5d75448cc9a4e9937",
      "stage2_authority_exact": s2["version"] == b["stage2"]["version"] and s2["stage2_dataset_fingerprint"] == b["stage2"]["fingerprint"],
      "stage3_authority_exact": s3["version"] == b["stage3"]["version"] and s3["stage3_dataset_fingerprint"] == b["stage3"]["fingerprint"],
      "financial_residuals_missing_only": s3["s3g1j_retained_raw_residuals"]["retained_as_missing"] is True and s3["s3g1j_retained_raw_residuals"]["usable_as_numeric_truth"] is False,
      "s3g4_strict_prior": s3["s3g4"]["expectation_is_strictly_prior"] is True and s3["s3g4"]["analyst_consensus_used"] is False,
      "surprise_current_period_only": surprise["activation"] == "SURPRISE_ECONOMIC_DATE_EQUALS_CURRENT_LATEST_FINANCIAL_ECONOMIC_DATE" and b["pit_policy"]["earnings_surprise_requires_current_financial_economic_date_match"] is True and b["missing_policy"]["surprise_from_noncurrent_financial_economic_period_treated_missing"] is True and s11["hard_boundary"]["no_prior_period_surprise_carry"] is True,
      "surprise_semantic_evidence_exact": s11["diagnostic_evidence"]["r1"]["age_p50_sessions"] == 133 and s11["diagnostic_evidence"]["r2_current_report_binding"]["current_report_match_rows"] == 1756064 and s11["diagnostic_evidence"]["r2_current_report_binding"]["prior_period_stale_rows"] == 3976955,
      "industry_excluded": industry["disposition"] == "OUT_PENDING_NORMALIZATION_PLUGIN" and industry["model_visible"] is False and c["source_facts"]["industry_artifact"]["csrc_2012_normalized_primary_code_rows"] == 1,
      "market_regime_accepted_disabled": market["lifecycle"] == "ACCEPTED" and market["enabled"] is False and market["training_allowed"] is False and market["live_allowed"] is False and accepted["permissions"]["stage4_feature_use_allowed"] is True,
      "module_registry_exact": module_fp == registry["module_set_fingerprint"],
      "baseline_still_locked": registry["accepted_baseline_anchor"]["stage4_unlocked"] is False and registry["accepted_baseline_anchor"]["alpha_training_allowed"] is False and registry["accepted_baseline_anchor"]["live_signal_allowed"] is False,
      "runtime_information_excluded": {"GENERAL_WEB_NEWS","SOCIAL_MEDIA","RUMOR_OR_UNVERIFIED_SUPPLY_CHAIN","ETF_PRIMARY_FLOW_WITHOUT_STRICT_PIT","CURRENT_INDUSTRY_BACKFILL"} <= set(b["explicit_out"]),
      "pit_fail_closed": b["pit_policy"]["future_backfill_forbidden"] is True and b["missing_policy"]["zero_fill_for_missing_forbidden"] is True and b["missing_policy"]["unknown_identity_or_time_semantics_fail_closed"] is True,
      "no_training_or_live": b["permissions"]["alpha_training_allowed"] is False and b["permissions"]["live_signal_allowed"] is False and b["permissions"]["authoritative_model_output"] is False,
    }
    failed=[k for k,v in checks.items() if not v]
    result={
      "gate":"STAGE4_V1_FEATURE_SET_FREEZE_CONTRACT",
      "pass":not failed,
      "feature_set_id":c["feature_set_id"],
      "feature_set_version":c["feature_set_version"],
      "feature_set_fingerprint":c["feature_set_fingerprint"],
      "surprise_activation":surprise["activation"],
      "industry_identity_disposition":industry["disposition"],
      "market_regime_lifecycle":market["lifecycle"],
      "checks":checks,
      "failed_checks":failed,
      "next_gate":c["next_gate"],
      "alpha_training_allowed":False,
      "live_signal_allowed":False,
    }
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if not failed else 2

if __name__ == "__main__":
    raise SystemExit(main())
