#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path

ALLOWED_STATES = {"WARMUP", "RISK_ON_BROAD", "RISK_ON_SELECTIVE", "NEUTRAL", "RISK_OFF_ORDERLY", "RISK_OFF_STRESS"}
NUMERIC_OPTIONAL = {"ew_return_5d", "ew_return_20d", "net_breadth_5d_mean", "ew_return_vol_20d", "amount_ratio_5d_20d", "q33_ret20_prior", "q67_ret20_prior", "q33_breadth5_prior", "q67_breadth5_prior", "q80_vol20_prior"}
NUMERIC_ALWAYS = {"advance_ratio", "net_breadth", "ew_return_1d", "cross_sectional_return_std_1d"}

def sha256(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()
def read_rows(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f: return list(csv.DictReader(f))
def is_finite_number(value: str) -> bool:
    try: return math.isfinite(float(value))
    except Exception: return False

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--root", required=True); ap.add_argument("--contract", required=True); ap.add_argument("--freshness-gate", required=True); ap.add_argument("--out", required=True); args = ap.parse_args()
    root = Path(args.root); contract_path = Path(args.contract); contract = json.loads(contract_path.read_text(encoding="utf-8")); manifest_path = root / "manifest.json"; manifest = json.loads(manifest_path.read_text(encoding="utf-8")); data_path = root / manifest["data_file"]; rows = read_rows(data_path); freshness = json.loads(Path(args.freshness_gate).read_text(encoding="utf-8")); errors = []
    if freshness.get("pass") is not True or freshness.get("stage4_research_unlocked") is not True: errors.append("pinned freshness hard gate is not PASS/research-unlocked")
    if freshness.get("alpha_training_allowed") is not False: errors.append("freshness gate unexpectedly allows alpha training")
    if manifest.get("lifecycle") != "SHADOW" or manifest.get("enabled") is not False: errors.append("Market Regime V1 must remain SHADOW and disabled")
    if manifest.get("training_allowed") is not False or manifest.get("live_allowed") is not False: errors.append("Market Regime V1 may not allow training/live")
    if manifest.get("failure_policy") != "ISOLATE_FAIL_CLOSED" or manifest.get("fallback_behavior") != "BASELINE_UNCHANGED": errors.append("extension isolation policy mismatch")
    if manifest.get("authoritative") is not False or manifest.get("stage3_frozen_unchanged") is not True: errors.append("shadow result cannot be authoritative or mutate Stage3")
    if manifest.get("contract_sha256") != sha256(contract_path.read_bytes()): errors.append("contract hash mismatch")
    if manifest.get("data_sha256") != sha256(data_path.read_bytes()): errors.append("data hash mismatch")
    if manifest.get("source_rows") != int(manifest["historical"]["rows"]) + int(manifest["forward"]["rows"]): errors.append("source row accounting mismatch")
    expected = contract["expected"]
    if int(manifest.get("source_rows", -1)) != int(expected["source_rows"]): errors.append(f"source row total mismatch {manifest.get('source_rows')} != {expected['source_rows']}")
    if int(manifest["historical"]["rows"]) != int(contract["sources"]["frozen_stage2_g3"]["rows"]): errors.append("historical source row count differs from pinned contract")
    if int(manifest["forward"]["rows"]) != int(contract["sources"]["freshness_v2_forward_ohlcv"]["rows"]): errors.append("forward source row count differs from pinned contract")
    if len(rows) != int(manifest.get("output_rows", -1)): errors.append("output row count mismatch")
    if len(rows) != int(expected["trading_sessions"]): errors.append(f"trading session count mismatch {len(rows)} != {expected['trading_sessions']}")
    if not rows: errors.append("empty Market Regime output")
    else:
        if rows[-1]["trade_date"] != contract["time_semantics"]["target_session"]: errors.append(f"last session mismatch {rows[-1]['trade_date']}")
        if rows[-1]["effective_session"] != contract["time_semantics"]["next_session_after_target"]: errors.append(f"last effective session mismatch {rows[-1]['effective_session']}")
        if rows[0]["regime_state"] != "WARMUP": errors.append("first row must be WARMUP")
    previous_day = ""; non_warmup = 0; expected_prior = None; warmup_min = int(contract["classification"]["min_prior_feature_sessions"])
    for i, r in enumerate(rows):
        day, eff = r["trade_date"], r["effective_session"]
        if previous_day and day <= previous_day: errors.append(f"non-increasing trade_date at row {i}: {previous_day}->{day}"); break
        previous_day = day
        if eff and eff <= day: errors.append(f"effective_session is not strictly later at {day}: {eff}"); break
        if r["regime_state"] not in ALLOWED_STATES: errors.append(f"invalid regime state at {day}: {r['regime_state']}"); break
        for k in NUMERIC_ALWAYS:
            if not is_finite_number(r[k]): errors.append(f"nonfinite mandatory metric {k} at {day}: {r[k]!r}"); break
        if errors: break
        for k in NUMERIC_OPTIONAL:
            if r[k] and not is_finite_number(r[k]): errors.append(f"nonfinite optional metric {k} at {day}: {r[k]!r}"); break
        if errors: break
        comparable = int(r["comparable_count"])
        if int(r["advancers"]) + int(r["decliners"]) + int(r["unchanged"]) != comparable: errors.append(f"breadth population mismatch at {day}"); break
        if comparable > int(r["traded_count"]): errors.append(f"comparable exceeds traded count at {day}"); break
        prior = int(r["prior_threshold_observations"]); thresholds = [r["q33_ret20_prior"], r["q67_ret20_prior"], r["q33_breadth5_prior"], r["q67_breadth5_prior"], r["q80_vol20_prior"]]
        if r["regime_state"] == "WARMUP":
            if any(thresholds): errors.append(f"WARMUP row unexpectedly carries classification thresholds at {day}"); break
        else:
            non_warmup += 1
            if prior < warmup_min: errors.append(f"classified before warmup at {day}: prior={prior}"); break
            if not all(thresholds): errors.append(f"classified row missing prior-only thresholds at {day}"); break
            q33r, q67r, q33b, q67b = map(float, thresholds[:4])
            if q33r > q67r or q33b > q67b: errors.append(f"quantile order violation at {day}"); break
        if expected_prior is not None and prior < expected_prior: errors.append(f"prior threshold observation count regressed at {day}"); break
        expected_prior = prior
    if rows and non_warmup == 0: errors.append("no classified post-warmup rows")
    states = {r["regime_state"] for r in rows}
    if rows and len(states - {"WARMUP"}) < 2: errors.append(f"historical replay produced fewer than two non-warmup states: {sorted(states)}")
    checks = {"freshness_gate_pass": freshness.get("pass") is True, "strict_next_session_effective_time": not any("effective_session" in x for x in errors), "prior_only_thresholds_present_after_warmup": not any("threshold" in x or "warmup" in x.lower() for x in errors), "replay_output_hash_locked": manifest.get("data_sha256") == sha256(data_path.read_bytes()), "frozen_stage3_unchanged": manifest.get("stage3_frozen_unchanged") is True, "shadow_disabled": manifest.get("lifecycle") == "SHADOW" and manifest.get("enabled") is False, "training_forbidden": manifest.get("training_allowed") is False, "live_forbidden": manifest.get("live_allowed") is False, "population_accounting": not any("population" in x or "comparable exceeds" in x for x in errors), "state_diversity": len(states - {"WARMUP"}) >= 2 if rows else False}
    if not all(checks.values()):
        for k, v in checks.items():
            if not v and k not in errors: errors.append(f"check_failed:{k}")
    result = {"gate": "STAGE4_MARKET_REGIME_V1_SHADOW_REPLAY_AUDIT", "pass": not errors, "checks": checks, "failed_checks": [k for k, v in checks.items() if not v], "errors": errors, "output_rows": len(rows), "non_warmup_rows": non_warmup, "state_counts": manifest.get("state_counts"), "coverage_start": rows[0]["trade_date"] if rows else None, "coverage_end": rows[-1]["trade_date"] if rows else None, "data_sha256": sha256(data_path.read_bytes()) if data_path.exists() else None, "manifest_sha256": sha256(manifest_path.read_bytes()) if manifest_path.exists() else None, "strict_pit": True, "authoritative": False, "lifecycle": "SHADOW", "stage4_feature_use_allowed": False, "alpha_training_allowed": False, "live_signal_allowed": False, "meaning": "PASS establishes a replayable SHADOW Market Regime candidate only. Separate TESTED/ACCEPTED promotion is required before Stage4 feature use."}
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if not errors else 2

if __name__ == "__main__": raise SystemExit(main())
