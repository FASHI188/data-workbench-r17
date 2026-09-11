from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_evidence_binds_exact_feature_set_and_matrix() -> None:
    e = load("governance/stage4_v1_2_feature_matrix_evidence.json")
    f = load("governance/stage4_v1_feature_set_contract.json")
    m = load("config/stage4_v1_feature_matrix_contract.json")
    assert e["status"] == "MACHINE_ACCEPTED_PRETRAINING_FEATURE_EVIDENCE"
    assert e["feature_set"]["version"] == f["feature_set_version"] == m["feature_set_version"] == "V1.2"
    assert e["feature_set"]["fingerprint"] == f["feature_set_fingerprint"] == m["feature_set_fingerprint"]
    assert e["feature_set"]["fingerprint"] == "d319ea1c236d580d0d032a055e4cdc07bf45e586ecbef664c6f4b3a8be98f9ff"
    assert e["matrix"]["matrix_sha256"] == "c5fca80bc0f35c008590fe8f6cd7b8a16ab22e13b4978314a812f1ecb60b391c"
    assert e["matrix"]["row_count"] == e["matrix"]["unique_key_count"] == 7924181


def test_evidence_binds_exact_machine_run_and_artifact() -> None:
    e = load("governance/stage4_v1_2_feature_matrix_evidence.json")
    x = e["execution"]
    assert x["run_id"] == 31668151558
    assert x["head_sha"] == "3b337311641ef9dc8ec14ba1a08833bbd83a3bed"
    assert x["artifact_id"] == 9168728086
    assert x["artifact_digest"] == "sha256:a4d3a10165bf3b369c77c7b4f77e97663bc3125f506d9203388e6f63198bda4a"
    assert x["conclusion"] == "success"


def test_evidence_preserves_all_semantic_safety_boundaries() -> None:
    e = load("governance/stage4_v1_2_feature_matrix_evidence.json")
    a = e["independent_audit"]
    assert a["pass"] is True
    assert a["unaffected_column_mismatches"] == 0
    assert a["transformed_column_mismatches"] == 0
    assert a["active_current_period_surprise_rows"] == 1756064
    assert a["active_surprise_period_mismatch_rows"] == 0
    assert a["prior_period_surprise_rows_removed"] == 3976955
    assert a["surprise_missing_indicator_mismatches"] == 0
    assert a["negative_guidance_age_rows"] == 0
    assert a["future_surprise_source_rows"] == 0
    assert a["prohibited_columns"] == []
    s = e["semantic_boundaries"]
    assert s["industry_identity"] == "EXCLUDED_PENDING_NORMALIZATION_PLUGIN"
    assert s["general_web_news"] == "EXCLUDED_FROM_ALPHA_V1"
    assert s["social_media"] == "EXCLUDED_FROM_ALPHA_V1"


def test_evidence_authorizes_only_next_preregistration_gate() -> None:
    e = load("governance/stage4_v1_2_feature_matrix_evidence.json")
    p = e["permissions"]
    assert p["stage4_v1_feature_set_complete"] is True
    assert p["stage4_v1_feature_matrix_complete"] is True
    assert p["alpha_training_preregistration_allowed"] is True
    assert p["alpha_training_execution_allowed"] is False
    assert p["live_signal_allowed"] is False
    assert p["authoritative_model_output"] is False
    assert e["next_gate"] == "SEPARATE_STAGE4_ALPHA_V1_TRAINING_PREREGISTRATION_AND_OOS_DESIGN"
