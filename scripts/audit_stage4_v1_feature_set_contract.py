#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> int:
    contract = load("governance/stage4_v1_feature_set_contract.json")
    stage2 = load("data/stage2_final/manifest.json")
    stage3 = load("data/stage3_final/manifest.json")
    market = load("governance/market_regime_v1_module_manifest.json")
    tested = load("governance/stage4_market_regime_v1_tested_promotion.json")
    basis = contract["fingerprint_basis"]

    checks: dict[str, bool] = {}
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":")).encode()
    checks["fingerprint_exact"] = hashlib.sha256(canonical).hexdigest() == contract["feature_set_fingerprint"]
    checks["stage2_authority_exact"] = (
        stage2["version"] == basis["stage2"]["version"]
        and stage2["stage2_dataset_fingerprint"] == basis["stage2"]["fingerprint"]
    )
    checks["stage3_authority_exact"] = (
        stage3["version"] == basis["stage3"]["version"]
        and stage3["stage3_dataset_fingerprint"] == basis["stage3"]["fingerprint"]
    )
    checks["stage3_financial_residuals_missing_only"] = (
        stage3["s3g1j_retained_raw_residuals"]["retained_as_missing"] is True
        and stage3["s3g1j_retained_raw_residuals"]["usable_as_numeric_truth"] is False
    )
    checks["s3g4_is_strict_prior"] = (
        stage3["s3g4"]["expectation_is_strictly_prior"] is True
        and stage3["s3g4"]["analyst_consensus_used"] is False
    )
    checks["market_regime_is_tested_not_accepted"] = (
        market["lifecycle"] == "TESTED"
        and market["enabled"] is False
        and market["training_allowed"] is False
        and market["live_allowed"] is False
        and tested["permissions"]["stage4_feature_use_allowed"] is False
        and tested["permissions"]["authoritative"] is False
    )
    out = set(basis["explicit_out"])
    checks["runtime_information_excluded"] = {
        "GENERAL_WEB_NEWS",
        "SOCIAL_MEDIA",
        "RUMOR_OR_UNVERIFIED_SUPPLY_CHAIN",
        "ETF_PRIMARY_FLOW_WITHOUT_STRICT_PIT",
        "GENERIC_ANNOUNCEMENT_TITLE_SENTIMENT_OR_SCALAR_INFERENCE",
    } <= out
    checks["pit_fail_closed"] = (
        basis["pit_policy"]["date_only_disclosure_uses_next_session"] is True
        and basis["pit_policy"]["future_backfill_forbidden"] is True
        and basis["missing_policy"]["zero_fill_for_missing_forbidden"] is True
        and basis["missing_policy"]["unknown_identity_or_time_semantics_fail_closed"] is True
    )
    permissions = basis["permissions"]
    checks["freeze_without_training_or_live"] = (
        permissions["feature_set_frozen"] is True
        and permissions["stage4_feature_materialization_allowed"] is True
        and permissions["market_regime_requires_ACCEPTED_before_materialization"] is True
        and permissions["alpha_training_allowed"] is False
        and permissions["live_signal_allowed"] is False
        and permissions["authoritative_model_output"] is False
    )

    failed = [name for name, ok in checks.items() if not ok]
    result = {
        "gate": "STAGE4_V1_FEATURE_SET_FREEZE_CONTRACT",
        "pass": not failed,
        "feature_set_id": contract["feature_set_id"],
        "feature_set_version": contract["feature_set_version"],
        "feature_set_fingerprint": contract["feature_set_fingerprint"],
        "checks": checks,
        "failed_checks": failed,
        "next_gate": contract["next_gate"],
        "alpha_training_allowed": False,
        "live_signal_allowed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
