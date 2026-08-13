from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_stage4_market_regime_v1 as m
from extensions.contracts import ExtensionKind, ExtensionLifecycle, ExtensionManifest, validate_extension_manifest


def _contract(min_prior: int = 3) -> dict:
    return {"classification": {"min_prior_feature_sessions": min_prior}, "time_semantics": {"target_session": "2026-01-10", "next_session_after_target": "2026-01-11"}}


def _daily(n: int) -> dict[str, m.DailyAgg]:
    out = defaultdict(m.DailyAgg)
    for i in range(n):
        day = f"2026-01-{i+1:02d}"; a = out[day]; a.traded = a.comparable = 100
        if i % 3 == 0: a.adv, a.dec, a.unchanged, ret = 70, 25, 5, 0.006
        elif i % 3 == 1: a.adv, a.dec, a.unchanged, ret = 45, 50, 5, -0.002
        else: a.adv, a.dec, a.unchanged, ret = 55, 40, 5, 0.001
        a.ret_sum = ret * a.comparable; a.ret_sq_sum = (ret * ret + 0.0001) * a.comparable; a.volume = 1_000_000 + i * 10_000; a.amount = 100_000_000 + i * 1_000_000
    return out


def test_quantile_is_deterministic_linear_interpolation() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]; assert m.quantile_linear(xs, 0.0) == 1.0; assert m.quantile_linear(xs, 1.0) == 4.0; assert abs(m.quantile_linear(xs, 0.5) - 2.5) < 1e-12


def test_classification_requires_sign_and_prior_relative_thresholds() -> None:
    assert m.classify_state(0.10, 0.20, 0.01, -0.03, 0.05, -0.1, 0.1, 0.03)[0] == "RISK_ON_BROAD"
    assert m.classify_state(0.10, 0.00, 0.01, -0.03, 0.05, -0.1, 0.1, 0.03)[0] == "RISK_ON_SELECTIVE"
    assert m.classify_state(-0.08, -0.20, 0.04, -0.03, 0.05, -0.1, 0.1, 0.03)[0] == "RISK_OFF_STRESS"
    assert m.classify_state(-0.08, -0.20, 0.01, -0.03, 0.05, -0.1, 0.1, 0.03)[0] == "RISK_OFF_ORDERLY"


def test_future_observations_do_not_rewrite_prior_metrics_or_state() -> None:
    rows_a = m.build_rows(_daily(30), _contract(min_prior=3)); c2 = {"classification": {"min_prior_feature_sessions": 3}, "time_semantics": {"target_session": "2026-01-31", "next_session_after_target": "2026-02-01"}}; rows_b = m.build_rows(_daily(31), c2); keys = [k for k in m.OUTPUT_FIELDS if k != "effective_session"]
    for a, b in zip(rows_a, rows_b[:len(rows_a)]): assert {k: a[k] for k in keys} == {k: b[k] for k in keys}


def test_thresholds_are_prior_only_and_appear_only_after_warmup() -> None:
    rows = m.build_rows(_daily(30), _contract(min_prior=3)); classified = [r for r in rows if r["regime_state"] != "WARMUP"]; assert classified; first = classified[0]; assert int(first["prior_threshold_observations"]) >= 3 and first["q33_ret20_prior"]; prior_index = rows.index(first) - 1; assert rows[prior_index]["prior_threshold_observations"] == str(int(first["prior_threshold_observations"]) - 1)


def test_tested_module_manifest_remains_disabled_and_cannot_train_or_live() -> None:
    raw = json.loads((ROOT / "governance" / "market_regime_v1_module_manifest.json").read_text()); manifest = ExtensionManifest(module_id=raw["module_id"], module_version=raw["module_version"], contract_version=raw["contract_version"], kind=ExtensionKind(raw["kind"]), lifecycle=ExtensionLifecycle(raw["lifecycle"]), enabled=raw["enabled"], input_schema=raw["input_schema"], output_schema=raw["output_schema"], dependencies=tuple(raw["dependencies"]), training_allowed=raw["training_allowed"], live_allowed=raw["live_allowed"], failure_policy=raw["failure_policy"], fallback_behavior=raw["fallback_behavior"], timeout_seconds=raw["timeout_seconds"], max_retries=raw["max_retries"], acceptance_ref=raw["acceptance_ref"], rollback_target_module_version=raw["rollback_target_module_version"], rollback_target_module_set_fingerprint=raw["rollback_target_module_set_fingerprint"])
    validate_extension_manifest(manifest); assert manifest.lifecycle == ExtensionLifecycle.TESTED and manifest.enabled is False; assert manifest.training_allowed is False and manifest.live_allowed is False


def test_contract_excludes_non_ohlcv_v1_inputs() -> None:
    contract = json.loads((ROOT / "config" / "stage4_market_regime_v1_contract.json").read_text()); assert contract["v1_input_policy"]["allowed"] == ["FROZEN_STAGE2_G3_OHLCV", "FRESHNESS_V2_FORWARD_OHLCV"]; assert set(contract["v1_input_policy"]["explicitly_excluded"]) >= {"industry_membership", "news", "social_media", "financials", "announcements", "etf_flows"}; assert contract["classification"]["threshold_history"] == "STRICTLY_T_MINUS_1_OR_EARLIER"
