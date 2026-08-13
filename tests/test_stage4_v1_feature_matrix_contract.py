from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_matrix_contract_binds_exact_feature_set_v1_1() -> None:
    matrix = load("config/stage4_v1_feature_matrix_contract.json")
    feature = load("governance/stage4_v1_feature_set_contract.json")
    assert matrix["feature_set_version"] == "V1.1"
    assert matrix["feature_set_fingerprint"] == "757d384cd090620cb8a351b8bcf6d93884577c74dd4fb874bb2f7880e0c939a3"
    assert feature["feature_set_version"] == matrix["feature_set_version"]
    assert feature["feature_set_fingerprint"] == matrix["feature_set_fingerprint"]


def test_matrix_inputs_are_exactly_pinned() -> None:
    p = load("config/stage4_v1_feature_matrix_contract.json")["pinned_artifacts"]
    assert p["historical_ohlcv"] == {"artifact_id": 8651700277, "digest": "sha256:bf977d4f379d421bd198865b90df90caef7ba6cfb5d6d1af96e5487300c1a2f8"}
    assert p["forward_ohlcv"] == {"artifact_id": 9150060738, "digest": "sha256:1eaa0c0e588c95f835a9e576659616bb8e68d0c19c9712b9821ea88c90451ba9"}
    assert p["forward_g5"]["artifact_id"] == 9168063389
    assert p["forward_g5"]["digest"] == "sha256:fa95e9bed319bfcfde70225ac5a61c2e0bb08810d52091d198f54bd396b33cae"
    assert p["forward_g5"]["data_sha256"] == "64c77590bc42585e61f77e8023b59388f507ffd9153f0cfc4cc656a2de0bd453"
    assert p["historical_financial_v17_30"]["artifact_id"] == 9112098872
    assert p["forward_financial_v17_30"]["artifact_id"] == 9166040064
    assert p["earnings_surprise_s3g4"]["artifact_id"] == 9126607328
    assert p["market_regime_v1"]["artifact_id"] == 9166323143
    assert p["trading_universe_policy"]["artifact_id"] == 8675790808


def test_expected_population_arithmetic_is_exact() -> None:
    expected = load("config/stage4_v1_feature_matrix_contract.json")["expected_inputs"]
    assert expected["historical_ohlcv_rows"] == 8038444
    assert expected["forward_ohlcv_rows"] == 41487
    assert expected["combined_ohlcv_rows"] == expected["historical_ohlcv_rows"] + expected["forward_ohlcv_rows"] == 8079931
    assert expected["historical_financial_rows"] == 1051826
    assert expected["forward_financial_rows"] == 1363
    assert expected["earnings_surprise_rows"] == 29139
    assert expected["market_regime_rows"] == 2821
    assert expected["forward_g5_rows"] == 101


def test_matrix_has_no_labels_and_keeps_runtime_track_out() -> None:
    c = load("config/stage4_v1_feature_matrix_contract.json")
    hard = c["hard_boundaries"]
    assert hard["no_industry_identity"] is True
    assert hard["no_general_web_news"] is True
    assert hard["no_social_media"] is True
    assert hard["no_current_industry_backfill"] is True
    assert hard["no_zero_fill_financials"] is True
    assert hard["no_alpha_labels"] is True
    assert hard["alpha_training_allowed"] is False
    assert hard["live_signal_allowed"] is False
    assert hard["authoritative_model_output"] is False


def test_time_semantics_are_strict_pit() -> None:
    c = load("config/stage4_v1_feature_matrix_contract.json")
    t = c["time_semantics"]
    assert t["row_information_time"] == "SESSION_T_CLOSE"
    assert t["row_effective_time"] == "NEXT_TRADING_SESSION_AFTER_T"
    assert t["future_backfill"] == "FORBIDDEN"
    assert t["financial_missing"] == "LATEST_REPORT_MISSING_STAYS_MISSING_NO_PRIOR_REPORT_CARRY"
    assert c["expected_outputs"]["candidate_price_rule"] == "0 < raw_unadjusted_close < 70 CNY"
    assert c["expected_outputs"]["exact_70_excluded"] is True


def test_industry_supersession_is_not_silently_reversed() -> None:
    feature = load("governance/stage4_v1_feature_set_contract.json")
    families = {x["family_id"]: x for x in feature["fingerprint_basis"]["feature_families"]}
    assert families["INDUSTRY_IDENTITY_PIT"]["disposition"] == "OUT_PENDING_NORMALIZATION_PLUGIN"
    assert families["INDUSTRY_IDENTITY_PIT"]["model_visible"] is False
    assert feature["invariants"]["unvalidated_industry_forward_fill_forbidden"] is True
