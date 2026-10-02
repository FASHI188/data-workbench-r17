from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_feature_set_fingerprint_is_exact_and_deterministic() -> None:
    c = _load("governance/stage4_v1_feature_set_contract.json")
    canonical = json.dumps(c["fingerprint_basis"], sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == c["feature_set_fingerprint"]
    assert c["feature_set_version"] == "V1.2"
    assert c["supersedes_feature_set_version"] == "V1.1"
    assert c["feature_set_fingerprint"] == "d319ea1c236d580d0d032a055e4cdc07bf45e586ecbef664c6f4b3a8be98f9ff"


def test_stage2_stage3_authority_and_financial_missingness_remain_frozen() -> None:
    c = _load("governance/stage4_v1_feature_set_contract.json")
    s2 = _load("data/stage2_final/manifest.json")
    s3 = _load("data/stage3_final/manifest.json")
    b = c["fingerprint_basis"]
    assert s2["version"] == b["stage2"]["version"]
    assert s2["stage2_dataset_fingerprint"] == b["stage2"]["fingerprint"]
    assert s3["version"] == b["stage3"]["version"]
    assert s3["stage3_dataset_fingerprint"] == b["stage3"]["fingerprint"]
    assert s3["s3g1j_retained_raw_residuals"]["retained_as_missing"] is True
    assert s3["s3g1j_retained_raw_residuals"]["usable_as_numeric_truth"] is False


def test_surprise_is_strict_prior_and_active_only_for_current_financial_period() -> None:
    c = _load("governance/stage4_v1_feature_set_contract.json")
    b = c["fingerprint_basis"]
    families = {r["family_id"]: r for r in b["feature_families"]}
    s = families["EARNINGS_GUIDANCE_SURPRISE_PIT"]
    assert s["disposition"] == "IN"
    assert s["activation"] == "SURPRISE_ECONOMIC_DATE_EQUALS_CURRENT_LATEST_FINANCIAL_ECONOMIC_DATE"
    assert b["pit_policy"]["surprise_expectation_strictly_prior"] is True
    assert b["pit_policy"]["earnings_surprise_requires_current_financial_economic_date_match"] is True
    assert b["missing_policy"]["surprise_from_noncurrent_financial_economic_period_treated_missing"] is True
    assert c["invariants"]["surprise_from_prior_financial_economic_period_is_missing"] is True


def test_surprise_supersession_evidence_is_exact_and_no_fixed_expiry_is_invented() -> None:
    s = _load("governance/stage4_v1_feature_set_v1_1_supersession.json")
    assert s["superseded_version"] == "V1.1"
    assert s["superseded_fingerprint"] == "757d384cd090620cb8a351b8bcf6d93884577c74dd4fb874bb2f7880e0c939a3"
    assert s["superseded_matrix_evidence"]["artifact_id"] == 9168438550
    assert s["superseded_matrix_evidence"]["matrix_rows"] == 7924181
    assert s["diagnostic_evidence"]["r1"]["age_p50_sessions"] == 133
    assert s["diagnostic_evidence"]["r1"]["age_gt_252_rows"] == 1743440
    assert s["diagnostic_evidence"]["r2_current_report_binding"]["current_report_match_rows"] == 1756064
    assert s["diagnostic_evidence"]["r2_current_report_binding"]["prior_period_stale_rows"] == 3976955
    assert s["hard_boundary"]["no_fixed_horizon_chosen_without_validation"] is True
    assert s["hard_boundary"]["no_prior_period_surprise_carry"] is True


def test_industry_stays_out_and_runtime_information_stays_out() -> None:
    c = _load("governance/stage4_v1_feature_set_contract.json")
    b = c["fingerprint_basis"]
    families = {r["family_id"]: r for r in b["feature_families"]}
    assert families["INDUSTRY_IDENTITY_PIT"]["disposition"] == "OUT_PENDING_NORMALIZATION_PLUGIN"
    assert families["INDUSTRY_IDENTITY_PIT"]["model_visible"] is False
    out = set(b["explicit_out"])
    assert {"GENERAL_WEB_NEWS", "SOCIAL_MEDIA", "RUMOR_OR_UNVERIFIED_SUPPLY_CHAIN", "ETF_PRIMARY_FLOW_WITHOUT_STRICT_PIT", "CURRENT_INDUSTRY_BACKFILL"} <= out
    evidence = c["source_facts"]["industry_artifact"]
    assert evidence["ledger_rows"] == 94171
    assert evidence["normalized_primary_code_rows"] == 19048
    assert evidence["csrc_2012_rows"] == 75124
    assert evidence["csrc_2012_normalized_primary_code_rows"] == 1


def test_market_regime_is_accepted_but_still_disabled() -> None:
    market = _load("governance/market_regime_v1_module_manifest.json")
    accepted = _load("governance/stage4_market_regime_v1_accepted_promotion.json")
    registry = _load("governance/extension_module_registry.json")
    assert market["lifecycle"] == "ACCEPTED"
    assert market["enabled"] is False
    assert market["training_allowed"] is False
    assert market["live_allowed"] is False
    assert accepted["permissions"]["stage4_feature_use_allowed"] is True
    assert accepted["permissions"]["alpha_training_allowed"] is False
    assert registry["accepted_baseline_anchor"]["stage4_unlocked"] is False


def test_freeze_does_not_authorize_training_or_live() -> None:
    c = _load("governance/stage4_v1_feature_set_contract.json")
    p = c["fingerprint_basis"]["permissions"]
    assert c["status"] == "FROZEN_PRETRAINING_CONTRACT"
    assert p["feature_set_frozen"] is True
    assert p["stage4_feature_materialization_allowed"] is True
    assert p["alpha_training_allowed"] is False
    assert p["live_signal_allowed"] is False
    assert p["authoritative_model_output"] is False
