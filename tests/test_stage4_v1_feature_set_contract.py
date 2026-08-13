from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_feature_set_fingerprint_is_exact_and_deterministic() -> None:
    contract = _load("governance/stage4_v1_feature_set_contract.json")
    canonical = json.dumps(contract["fingerprint_basis"], sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == contract["feature_set_fingerprint"]
    assert contract["feature_set_fingerprint"] == "06838625fa8afc3df87f7e8df22007c4e780e93dcbbe7605e7ec99fe1713c738"


def test_feature_set_locks_frozen_stage2_and_stage3_authority() -> None:
    contract = _load("governance/stage4_v1_feature_set_contract.json")
    stage2 = _load("data/stage2_final/manifest.json")
    stage3 = _load("data/stage3_final/manifest.json")
    basis = contract["fingerprint_basis"]
    assert stage2["version"] == basis["stage2"]["version"]
    assert stage2["stage2_dataset_fingerprint"] == basis["stage2"]["fingerprint"]
    assert stage3["version"] == basis["stage3"]["version"]
    assert stage3["stage3_dataset_fingerprint"] == basis["stage3"]["fingerprint"]
    assert stage3["s3g1j_retained_raw_residuals"]["retained_as_missing"] is True
    assert stage3["s3g1j_retained_raw_residuals"]["usable_as_numeric_truth"] is False


def test_feature_set_is_dual_track_and_excludes_non_pit_runtime_information() -> None:
    contract = _load("governance/stage4_v1_feature_set_contract.json")
    basis = contract["fingerprint_basis"]
    out = set(basis["explicit_out"])
    assert {"GENERAL_WEB_NEWS", "SOCIAL_MEDIA", "RUMOR_OR_UNVERIFIED_SUPPLY_CHAIN"} <= out
    assert "ETF_PRIMARY_FLOW_WITHOUT_STRICT_PIT" in out
    assert "GENERIC_ANNOUNCEMENT_TITLE_SENTIMENT_OR_SCALAR_INFERENCE" in out
    assert "CURRENT_INDUSTRY_BACKFILL" in out
    assert "TURNOVER_RATE_WITHOUT_PIT_SHARE_DENOMINATOR" in out
    assert "VALUATION_WITHOUT_PIT_DENOMINATOR" in out
    assert "INDUSTRY_RELATIVE_STRENGTH_OR_DIFFUSION_UNTIL_SEPARATE_TESTED_PLUGIN" in out


def test_feature_set_has_exact_pit_and_missingness_boundaries() -> None:
    contract = _load("governance/stage4_v1_feature_set_contract.json")
    pit = contract["fingerprint_basis"]["pit_policy"]
    missing = contract["fingerprint_basis"]["missing_policy"]
    assert pit["decision_cut"] == "SESSION_T_CLOSE_INFORMATION_ONLY_EFFECTIVE_NEXT_TRADING_SESSION"
    assert pit["date_only_disclosure_uses_next_session"] is True
    assert pit["surprise_expectation_strictly_prior"] is True
    assert pit["market_regime_thresholds_use_only_t_minus_1_history"] is True
    assert pit["future_backfill_forbidden"] is True
    assert missing["s3g1j_retained_errors_and_ties_are_missing_not_numeric_truth"] is True
    assert missing["zero_fill_for_missing_forbidden"] is True
    assert missing["coverage_and_missingness_report_required_per_feature"] is True
    assert missing["unknown_identity_or_time_semantics_fail_closed"] is True


def test_feature_families_are_explicit_and_market_regime_is_not_sneak_accepted() -> None:
    contract = _load("governance/stage4_v1_feature_set_contract.json")
    families = {row["family_id"]: row for row in contract["fingerprint_basis"]["feature_families"]}
    assert set(families) == {
        "UNIVERSE_ELIGIBILITY_PIT",
        "PRICE_VOLUME_TECHNICAL_PIT",
        "CORPORATE_ACTION_ADJUSTMENT_PIT",
        "FINANCIAL_STATEMENT_PIT",
        "EARNINGS_GUIDANCE_SURPRISE_PIT",
        "INDUSTRY_IDENTITY_PIT",
        "MARKET_REGIME_V1",
    }
    assert families["UNIVERSE_ELIGIBILITY_PIT"]["model_visible"] is False
    assert families["CORPORATE_ACTION_ADJUSTMENT_PIT"]["model_visible"] is False
    assert families["MARKET_REGIME_V1"]["disposition"] == "IN_PENDING_MODULE_ACCEPTANCE"
    market = _load("governance/market_regime_v1_module_manifest.json")
    tested = _load("governance/stage4_market_regime_v1_tested_promotion.json")
    assert market["lifecycle"] == "TESTED"
    assert market["enabled"] is False
    assert market["training_allowed"] is False
    assert market["live_allowed"] is False
    assert tested["permissions"]["stage4_feature_use_allowed"] is False


def test_freeze_does_not_authorize_alpha_training_or_live_signals() -> None:
    contract = _load("governance/stage4_v1_feature_set_contract.json")
    permissions = contract["fingerprint_basis"]["permissions"]
    assert contract["status"] == "FROZEN_PRETRAINING_CONTRACT"
    assert permissions["feature_set_frozen"] is True
    assert permissions["stage4_feature_materialization_allowed"] is True
    assert permissions["market_regime_requires_ACCEPTED_before_materialization"] is True
    assert permissions["alpha_training_allowed"] is False
    assert permissions["live_signal_allowed"] is False
    assert permissions["authoritative_model_output"] is False
