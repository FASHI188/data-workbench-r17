from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_matrix_contract_binds_exact_feature_set_v1_2() -> None:
    matrix = load("config/stage4_v1_feature_matrix_contract.json")
    feature = load("governance/stage4_v1_feature_set_contract.json")
    assert matrix["matrix_version"] == "V1.2"
    assert matrix["feature_set_version"] == "V1.2"
    assert matrix["feature_set_fingerprint"] == "d319ea1c236d580d0d032a055e4cdc07bf45e586ecbef664c6f4b3a8be98f9ff"
    assert feature["feature_set_version"] == matrix["feature_set_version"]
    assert feature["feature_set_fingerprint"] == matrix["feature_set_fingerprint"]


def test_v1_1_base_matrix_is_pinned_and_already_audited() -> None:
    base = load("config/stage4_v1_feature_matrix_contract.json")["base_matrix"]
    assert base["artifact_id"] == 9168438550
    assert base["artifact_digest"] == "sha256:813ae234c149fb30f725895cd67bcfbe404b1050cba9f915c9c4c0f5a1392a42"
    assert base["matrix_version"] == "V1.1"
    assert base["matrix_sha256"] == "1818f9cdaf86c965e45c07cd1d261ece0eb782a6aa0aa6846d18701bd8699feb"
    assert base["row_count"] == 7924181
    assert base["independent_audit_pass"] is True


def test_original_source_artifacts_remain_pinned() -> None:
    p = load("config/stage4_v1_feature_matrix_contract.json")["pinned_artifacts"]
    assert p["historical_ohlcv"]["artifact_id"] == 8651700277
    assert p["forward_ohlcv"]["artifact_id"] == 9150060738
    assert p["forward_g5"]["artifact_id"] == 9168063389
    assert p["forward_g5"]["data_sha256"] == "64c77590bc42585e61f77e8023b59388f507ffd9153f0cfc4cc656a2de0bd453"
    assert p["historical_financial_v17_30"]["artifact_id"] == 9112098872
    assert p["forward_financial_v17_30"]["artifact_id"] == 9166040064
    assert p["earnings_surprise_s3g4"]["artifact_id"] == 9126607328
    assert p["market_regime_v1"]["artifact_id"] == 9166323143
    assert p["trading_universe_policy"]["artifact_id"] == 8675790808


def test_expected_population_and_dates_remain_exact() -> None:
    c = load("config/stage4_v1_feature_matrix_contract.json")
    e = c["expected_inputs"]
    assert e["combined_ohlcv_rows"] == 8038444 + 41487 == 8079931
    assert e["historical_financial_rows"] == 1051826
    assert e["forward_financial_rows"] == 1363
    assert e["earnings_surprise_rows"] == 29139
    assert e["market_regime_rows"] == 2821
    assert c["expected_outputs"]["matrix_rows"] == 7924181
    assert c["expected_outputs"]["trade_date_max"] == "2026-08-12"
    assert c["expected_outputs"]["effective_session_max"] == "2026-08-13"


def test_surprise_semantics_are_current_financial_period_only() -> None:
    c = load("config/stage4_v1_feature_matrix_contract.json")
    t = c["time_semantics"]
    assert t["earnings_surprise_join"] == "LATEST_ACCEPTED_S3G4_SURPRISE_EVENT_KNOWN_BY_EFFECTIVE_SESSION_THEN_ACTIVE_ONLY_IF_SURPRISE_ECONOMIC_DATE_EQUALS_CURRENT_FINANCIAL_ECONOMIC_DATE"
    assert t["earnings_surprise_prior_period"] == "TREATED_AS_MISSING"
    assert t["earnings_surprise_fixed_day_expiry"] == "NOT_INVENTED"
    assert c["expected_outputs"]["surprise_prior_period_carry_allowed"] is False
    assert c["hard_boundaries"]["no_prior_period_surprise_carry"] is True


def test_matrix_has_no_labels_and_keeps_runtime_track_out() -> None:
    hard = load("config/stage4_v1_feature_matrix_contract.json")["hard_boundaries"]
    assert hard["no_industry_identity"] is True
    assert hard["no_general_web_news"] is True
    assert hard["no_social_media"] is True
    assert hard["no_current_industry_backfill"] is True
    assert hard["no_zero_fill_financials"] is True
    assert hard["no_alpha_labels"] is True
    assert hard["alpha_training_allowed"] is False
    assert hard["live_signal_allowed"] is False
    assert hard["authoritative_model_output"] is False


def test_industry_remains_excluded() -> None:
    feature = load("governance/stage4_v1_feature_set_contract.json")
    families = {x["family_id"]: x for x in feature["fingerprint_basis"]["feature_families"]}
    assert families["INDUSTRY_IDENTITY_PIT"]["disposition"] == "OUT_PENDING_NORMALIZATION_PLUGIN"
    assert families["INDUSTRY_IDENTITY_PIT"]["model_visible"] is False
    assert feature["invariants"]["unvalidated_industry_forward_fill_forbidden"] is True
