#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from statistics import fmean, pstdev
from zoneinfo import ZoneInfo

REQUIRED_FIELDS = {"exchange", "code", "trade_date", "open", "high", "low", "close", "volume_shares", "amount_cny"}
OUTPUT_FIELDS = ["trade_date", "available_at", "effective_session", "traded_count", "comparable_count", "advancers", "decliners", "unchanged", "advance_ratio", "net_breadth", "ew_return_1d", "ew_return_5d", "ew_return_20d", "net_breadth_5d_mean", "ew_return_vol_20d", "cross_sectional_return_std_1d", "total_volume_shares", "total_amount_cny", "amount_ratio_5d_20d", "prior_threshold_observations", "q33_ret20_prior", "q67_ret20_prior", "q33_breadth5_prior", "q67_breadth5_prior", "q80_vol20_prior", "regime_state", "state_reason", "data_status"]
TZ = ZoneInfo("Asia/Shanghai")

@dataclass
class DailyAgg:
    traded: int = 0
    comparable: int = 0
    adv: int = 0
    dec: int = 0
    unchanged: int = 0
    ret_sum: float = 0.0
    ret_sq_sum: float = 0.0
    volume: int = 0
    amount: int = 0

def sha256(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()
def fmt(x: float | None) -> str:
    if x is None or not math.isfinite(x): return ""
    if abs(x) < 5e-16: x = 0.0
    return format(x, ".12g")

def quantile_linear(values: list[float], q: float) -> float:
    if not values: raise ValueError("quantile requires non-empty values")
    if not 0 <= q <= 1: raise ValueError("q outside [0,1]")
    s = sorted(values)
    if len(s) == 1: return s[0]
    pos = (len(s) - 1) * q; lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi: return s[lo]
    w = pos - lo
    return s[lo] * (1.0 - w) + s[hi] * w

def rolling_compound(xs: list[float]) -> float:
    out = 1.0
    for x in xs: out *= 1.0 + x
    return out - 1.0

def classify_state(ret20: float, breadth5: float, vol20: float, q33_ret20: float, q67_ret20: float, q33_breadth5: float, q67_breadth5: float, q80_vol20: float) -> tuple[str, str]:
    trend_high = ret20 > 0.0 and ret20 >= q67_ret20
    trend_low = ret20 < 0.0 and ret20 <= q33_ret20
    breadth_high = breadth5 >= q67_breadth5
    breadth_low = breadth5 <= q33_breadth5
    stress_high = vol20 >= q80_vol20
    if trend_low and stress_high: return "RISK_OFF_STRESS", "negative_low_quantile_trend+high_prior_relative_volatility"
    if trend_high and breadth_high: return "RISK_ON_BROAD", "positive_high_quantile_trend+high_prior_relative_breadth"
    if trend_high: return "RISK_ON_SELECTIVE", "positive_high_quantile_trend+non_high_breadth"
    if trend_low: return "RISK_OFF_ORDERLY", "negative_low_quantile_trend+non_stress_volatility"
    if breadth_low and ret20 < 0.0: return "RISK_OFF_ORDERLY", "negative_trend+low_prior_relative_breadth"
    return "NEUTRAL", "no_shadow_state_condition_met"

def discover_ohlcv_files(root: Path) -> list[Path]:
    found = []
    for p in sorted(root.rglob("*.csv.gz")):
        try:
            with gzip.open(p, "rt", encoding="utf-8", newline="") as f: header = next(csv.reader(f), [])
        except (OSError, UnicodeDecodeError): continue
        if REQUIRED_FIELDS.issubset(set(header)): found.append(p)
    if not found: raise RuntimeError(f"no OHLCV csv.gz files under {root}")
    return found

def consume_files(files: list[Path], daily: dict[str, DailyAgg], last_close: dict[tuple[str, str], tuple[str, float]], source_label: str, min_day_exclusive: date | None = None) -> dict:
    rows = 0; first_day = None; last_day = None; files_meta = []
    for p in files:
        file_rows = 0; file_first = None; file_last = None
        with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
            rd = csv.DictReader(f)
            if not REQUIRED_FIELDS.issubset(set(rd.fieldnames or [])): raise ValueError(f"OHLCV fields missing in {p}")
            per_key_last_day = {}
            for r in rd:
                ex, code, day_s = r["exchange"], r["code"], r["trade_date"]; day = date.fromisoformat(day_s)
                if min_day_exclusive is not None and day <= min_day_exclusive: raise ValueError(f"{source_label} row not strictly forward: {ex}:{code}:{day_s}")
                key = (ex, code); previous_in_file = per_key_last_day.get(key)
                if previous_in_file is not None and day_s <= previous_in_file: raise ValueError(f"non-increasing key date in {p}: {key} {previous_in_file}->{day_s}")
                per_key_last_day[key] = day_s
                close = float(r["close"])
                if not math.isfinite(close) or close <= 0: raise ValueError(f"nonpositive/nonfinite close {ex}:{code}:{day_s}:{r['close']}")
                volume, amount = int(r["volume_shares"]), int(r["amount_cny"])
                if volume < 0 or amount < 0: raise ValueError(f"negative volume/amount {ex}:{code}:{day_s}")
                a = daily[day_s]; a.traded += 1; a.volume += volume; a.amount += amount
                prev = last_close.get(key)
                if prev is not None:
                    prev_day, prev_close = prev
                    if day_s <= prev_day: raise ValueError(f"non-increasing cross-file key date {key} {prev_day}->{day_s}")
                    ret = close / prev_close - 1.0
                    if not math.isfinite(ret): raise ValueError(f"nonfinite return {key}:{day_s}")
                    a.comparable += 1; a.ret_sum += ret; a.ret_sq_sum += ret * ret
                    if ret > 1e-15: a.adv += 1
                    elif ret < -1e-15: a.dec += 1
                    else: a.unchanged += 1
                last_close[key] = (day_s, close); rows += 1; file_rows += 1
                first_day = day if first_day is None or day < first_day else first_day; last_day = day if last_day is None or day > last_day else last_day
                file_first = day if file_first is None or day < file_first else file_first; file_last = day if file_last is None or day > file_last else file_last
        files_meta.append({"file": str(p), "rows": file_rows, "first_day": file_first.isoformat() if file_first else None, "last_day": file_last.isoformat() if file_last else None})
    return {"label": source_label, "files": len(files), "rows": rows, "first_day": first_day.isoformat() if first_day else None, "last_day": last_day.isoformat() if last_day else None, "files_meta": files_meta}

def build_rows(daily: dict[str, DailyAgg], contract: dict) -> list[dict[str, str]]:
    days = sorted(daily)
    if not days: raise ValueError("empty daily aggregate")
    warmup = int(contract["classification"]["min_prior_feature_sessions"]); next_after_target = contract["time_semantics"]["next_session_after_target"]
    five_ret = deque(maxlen=5); twenty_ret = deque(maxlen=20); five_breadth = deque(maxlen=5); twenty_amount = deque(maxlen=20)
    prior_ret20 = []; prior_breadth5 = []; prior_vol20 = []; rows = []
    for idx, day_s in enumerate(days):
        a = daily[day_s]
        if a.comparable <= 0: ew1 = 0.0; std1 = 0.0; adv_ratio = 0.5; breadth = 0.0
        else:
            ew1 = a.ret_sum / a.comparable; variance = max(a.ret_sq_sum / a.comparable - ew1 * ew1, 0.0); std1 = math.sqrt(variance)
            adv_ratio = a.adv / a.comparable; breadth = (a.adv - a.dec) / a.comparable
        five_ret.append(ew1); twenty_ret.append(ew1); five_breadth.append(breadth); twenty_amount.append(float(a.amount))
        ret5 = rolling_compound(list(five_ret)) if len(five_ret) == 5 else None; ret20 = rolling_compound(list(twenty_ret)) if len(twenty_ret) == 20 else None
        breadth5 = fmean(five_breadth) if len(five_breadth) == 5 else None; vol20 = pstdev(twenty_ret) if len(twenty_ret) == 20 else None; amount_ratio = None
        if len(twenty_amount) == 20:
            recent5, base20 = fmean(list(twenty_amount)[-5:]), fmean(twenty_amount); amount_ratio = recent5 / base20 if base20 > 0 else None
        q33r = q67r = q33b = q67b = q80v = None; state, reason = "WARMUP", "insufficient_prior_feature_sessions"
        if ret20 is not None and breadth5 is not None and vol20 is not None and len(prior_ret20) >= warmup:
            q33r = quantile_linear(prior_ret20, 0.33); q67r = quantile_linear(prior_ret20, 0.67); q33b = quantile_linear(prior_breadth5, 0.33); q67b = quantile_linear(prior_breadth5, 0.67); q80v = quantile_linear(prior_vol20, 0.80)
            state, reason = classify_state(ret20, breadth5, vol20, q33r, q67r, q33b, q67b, q80v)
        effective = days[idx + 1] if idx + 1 < len(days) else next_after_target
        available = datetime.combine(date.fromisoformat(day_s), time(15, 30), tzinfo=TZ).isoformat()
        rows.append({"trade_date": day_s, "available_at": available, "effective_session": effective, "traded_count": str(a.traded), "comparable_count": str(a.comparable), "advancers": str(a.adv), "decliners": str(a.dec), "unchanged": str(a.unchanged), "advance_ratio": fmt(adv_ratio), "net_breadth": fmt(breadth), "ew_return_1d": fmt(ew1), "ew_return_5d": fmt(ret5), "ew_return_20d": fmt(ret20), "net_breadth_5d_mean": fmt(breadth5), "ew_return_vol_20d": fmt(vol20), "cross_sectional_return_std_1d": fmt(std1), "total_volume_shares": str(a.volume), "total_amount_cny": str(a.amount), "amount_ratio_5d_20d": fmt(amount_ratio), "prior_threshold_observations": str(len(prior_ret20)), "q33_ret20_prior": fmt(q33r), "q67_ret20_prior": fmt(q67r), "q33_breadth5_prior": fmt(q33b), "q67_breadth5_prior": fmt(q67b), "q80_vol20_prior": fmt(q80v), "regime_state": state, "state_reason": reason, "data_status": "AVAILABLE"})
        if ret20 is not None and breadth5 is not None and vol20 is not None: prior_ret20.append(ret20); prior_breadth5.append(breadth5); prior_vol20.append(vol20)
    return rows

def write_csv(path: Path, rows: list[dict[str, str]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="", compresslevel=9) as f: w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS); w.writeheader(); w.writerows(rows)
    return sha256(path.read_bytes())

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--historical-root", required=True); ap.add_argument("--forward-root", required=True); ap.add_argument("--contract", required=True); ap.add_argument("--out", required=True); args = ap.parse_args()
    contract_path = Path(args.contract); contract = json.loads(contract_path.read_text(encoding="utf-8")); hist_root, fwd_root = Path(args.historical_root), Path(args.forward_root)
    hist_files, fwd_files = discover_ohlcv_files(hist_root), discover_ohlcv_files(fwd_root); daily = defaultdict(DailyAgg); last_close = {}
    hist = consume_files(hist_files, daily, last_close, "FROZEN_STAGE2_G3"); frozen_end = date.fromisoformat(contract["sources"]["frozen_stage2_g3"]["coverage_end"])
    if hist["last_day"] != frozen_end.isoformat(): raise ValueError(f"historical end mismatch {hist['last_day']} != {frozen_end}")
    fwd = consume_files(fwd_files, daily, last_close, "FRESHNESS_V2_FORWARD_OHLCV", min_day_exclusive=frozen_end); target = contract["time_semantics"]["target_session"]
    if fwd["last_day"] != target: raise ValueError(f"forward end mismatch {fwd['last_day']} != {target}")
    rows = build_rows(daily, contract); outdir = Path(args.out); data_path = outdir / "market_regime_v1.csv.gz"; data_sha = write_csv(data_path, rows); states = defaultdict(int)
    for r in rows: states[r["regime_state"]] += 1
    manifest = {"schema_version": 1, "module_id": "market_regime_v1", "module_version": "V1", "lifecycle": "SHADOW", "enabled": False, "training_allowed": False, "live_allowed": False, "failure_policy": "ISOLATE_FAIL_CLOSED", "fallback_behavior": "BASELINE_UNCHANGED", "contract_sha256": sha256(contract_path.read_bytes()), "historical": hist, "forward": fwd, "source_rows": hist["rows"] + fwd["rows"], "output_rows": len(rows), "first_session": rows[0]["trade_date"], "last_session": rows[-1]["trade_date"], "last_effective_session": rows[-1]["effective_session"], "state_counts": dict(sorted(states.items())), "data_file": data_path.name, "data_sha256": data_sha, "pit_threshold_semantics": "all classification quantiles at t are computed from completed feature observations strictly before t", "effective_semantics": "close-derived row at t is SHADOW-eligible only from the next trading session", "authoritative": False, "stage3_frozen_unchanged": True, "alpha_training_allowed": False, "live_signal_allowed": False, "errors": []}
    outdir.mkdir(parents=True, exist_ok=True); (outdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"source_rows": manifest["source_rows"], "output_rows": len(rows), "first_session": manifest["first_session"], "last_session": manifest["last_session"], "state_counts": manifest["state_counts"], "data_sha256": data_sha}, ensure_ascii=False)); return 0

if __name__ == "__main__": raise SystemExit(main())
