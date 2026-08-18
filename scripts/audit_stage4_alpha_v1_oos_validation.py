#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

AUTH_FP = "d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d"
EXEC_FP = "b61333a33870ac079cd2dc94c71cb53e3f1a267dc9ff8e26e2ef7d9fea95ed2e"
MODEL_SHA = "e85aabf694799a16f8c5a1dea017e3489a9025ecf3d484d7a4f3fd931b0d702c"
PREPROCESS_SHA = "4b7833e4c4bdba9b956dba190f7337003ae944a624b59ddad7654b1457608330"
MATRIX_SHA = "c5fca80bc0f35c008590fe8f6cd7b8a16ab22e13b4978314a812f1ecb60b391c"
OOS_START = "2023-01-03"
OOS_END = "2024-12-31"
LATEST_VALID20 = "2024-12-03"
LOCKBOX_START = "2025-01-02"


def canonical_hash(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def close(a, b, tol=1e-12):
    return abs(float(a) - float(b)) <= tol + tol * max(abs(float(a)), abs(float(b)))


def handling_rate(date_str: str) -> float:
    return 0.0000341 if date_str >= "2023-08-28" else 0.0000487


def stamp_rate(date_str: str) -> float:
    return 0.0005 if date_str >= "2023-08-28" else 0.001


def roundtrip_cost(entry_date: str, exit_date: str) -> float:
    return 0.003 + handling_rate(entry_date) + handling_rate(exit_date) + stamp_rate(exit_date)


def bootstrap(values, *, block=20, resamples=10000, seed=20260817):
    import numpy as np
    x = np.asarray(values, dtype=np.float64)
    if x.ndim != 1 or len(x) < block or not np.isfinite(x).all():
        raise ValueError("invalid bootstrap input")
    rng = np.random.Generator(np.random.PCG64(seed))
    max_start = len(x) - block + 1
    blocks_needed = math.ceil(len(x) / block)
    means = np.empty(resamples, dtype=np.float64)
    for i in range(resamples):
        starts = rng.integers(0, max_start, size=blocks_needed)
        sample = np.concatenate([x[s:s + block] for s in starts])[: len(x)]
        means[i] = sample.mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def synthetic_self_test() -> int:
    import numpy as np
    x = np.linspace(0.002, 0.04, 80)
    a = bootstrap(x, resamples=250)
    b = bootstrap(x, resamples=250)
    assert a == b and a[0] > 0
    assert close(roundtrip_cost("2023-08-01", "2023-08-25"), 0.003 + 2 * 0.0000487 + 0.001)
    assert close(roundtrip_cost("2023-08-25", "2023-09-22"), 0.003 + 0.0000487 + 0.0000341 + 0.0005)
    print(json.dumps({"synthetic_audit_self_test": "PASS", "bootstrap_ci": a, "fit_calls": 0}))
    return 0


def main() -> int:
    if "--synthetic-self-test" in sys.argv:
        return synthetic_self_test()

    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--preprocess", required=True)
    ap.add_argument("--authorization", required=True)
    ap.add_argument("--execution-contract", required=True)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--evaluation", required=True)
    ap.add_argument("--execution-dir", required=True)
    ap.add_argument("--execution-head", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import duckdb
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq
    from scipy.stats import spearmanr

    out = Path(args.execution_dir)
    auth = json.loads(Path(args.authorization).read_text(encoding="utf-8"))
    exe = json.loads(Path(args.execution_contract).read_text(encoding="utf-8"))
    manifest = json.loads((out / "oos_execution_manifest.json").read_text(encoding="utf-8"))
    consumption = json.loads((out / "authorization_consumption.json").read_text(encoding="utf-8"))
    gate_actual = json.loads((out / "oos_gate_result.json").read_text(encoding="utf-8"))
    quarter_actual = json.loads((out / "oos_quarter_metrics.json").read_text(encoding="utf-8"))
    econ_actual = json.loads((out / "oos_economic_metrics.json").read_text(encoding="utf-8"))

    failures = []
    checks = {}

    def ck(name, condition):
        ok = bool(condition)
        checks[name] = ok
        if not ok:
            failures.append(name)

    ck("authorization_fingerprint", auth.get("fingerprint") == AUTH_FP and canonical_hash(auth["fingerprint_basis"]) == AUTH_FP)
    ck("execution_contract_fingerprint", exe.get("fingerprint") == EXEC_FP and canonical_hash(exe["fingerprint_basis"]) == EXEC_FP)
    ck("execution_head_exact", bool(re.fullmatch(r"[0-9a-f]{40}", args.execution_head)) and manifest.get("execution_head") == args.execution_head and consumption.get("execution_head") == args.execution_head)
    ck("matrix_sha", sha256_file(Path(args.matrix)) == MATRIX_SHA == manifest.get("feature_matrix_sha256"))
    ck("model_sha", sha256_file(Path(args.model)) == MODEL_SHA == manifest.get("model_sha256"))
    ck("preprocess_sha", sha256_file(Path(args.preprocess)) == PREPROCESS_SHA == manifest.get("preprocess_manifest_sha256"))
    ck("authorization_consumed_once", consumption.get("status") == "CONSUMED" and consumption.get("authorization_fingerprint") == AUTH_FP and consumption.get("execution_contract_fingerprint") == EXEC_FP and consumption.get("consumption_event") == "FIRST_OOS_PREDICTION_COMPUTATION")
    ck("zero_preconsumption_label_read", consumption.get("oos_label_read_before_consumption") is False)
    ck("no_fit", manifest.get("fit_executed") is False and manifest.get("retraining_executed") is False and manifest.get("hyperparameter_search_executed") is False and manifest.get("candidate_reselection_executed") is False and consumption.get("fit_executed") is False)
    ck("no_lockbox", manifest.get("lockbox_accessed") is False and consumption.get("lockbox_accessed") is False)
    ck("no_live_main_authoritative", manifest.get("live_signal_allowed") is False and manifest.get("main_merge_allowed") is False and manifest.get("authoritative_model_output") is False)

    con = duckdb.connect()
    pred_path = Path(args.predictions)
    labels_path = Path(args.labels)
    eval_path = Path(args.evaluation)
    prow, pu, pmin, pmax = con.execute(
        f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date) FROM read_parquet('{str(pred_path).replace(chr(39), chr(39)*2)}')"
    ).fetchone()
    lrow, lu, lmin, lmax, valid20, max_valid20, max_exit20 = con.execute(
        f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date),count(*) FILTER(WHERE valid_label_20d),max(trade_date) FILTER(WHERE valid_label_20d),max(exit_date_20d) FILTER(WHERE valid_label_20d) FROM read_parquet('{str(labels_path).replace(chr(39), chr(39)*2)}')"
    ).fetchone()
    erow, eu, emin, emax = con.execute(
        f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date) FROM read_parquet('{str(eval_path).replace(chr(39), chr(39)*2)}')"
    ).fetchone()
    ck("prediction_population_unique", prow > 0 and prow == pu and str(pmin) == OOS_START and str(pmax) == OOS_END and manifest.get("prediction_rows") == prow)
    ck("label_population_unique", lrow == lu == prow and str(lmin) == OOS_START and str(lmax) == OOS_END and manifest.get("label_rows") == lrow)
    ck("valid20_boundary", valid20 == erow and str(max_valid20) <= LATEST_VALID20 and str(max_exit20) <= OOS_END and str(emax) <= LATEST_VALID20 and manifest.get("valid_20d_rows") == valid20)
    ck("evaluation_population_unique", erow > 0 and erow == eu and manifest.get("evaluation_rows") == erow)
    ck("market_physical_years_only", set(manifest.get("market_source_file_names", [])) and all(re.search(r"_(2023|2024)(?:_shard\d+)?\.csv\.gz$", n, re.I) for n in manifest.get("market_source_file_names", [])))
    ck("market_lockbox_boundary", str(manifest.get("market_source_max_date")) < LOCKBOX_START and str(manifest.get("market_source_max_date")) <= OOS_END)

    df = pq.read_table(eval_path).to_pandas()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    daily = []
    for d, g in df.groupby("trade_date", sort=True):
        p = g["prediction"].to_numpy(dtype=float)
        y = g["excess_return_20d"].to_numpy(dtype=float)
        ok = np.isfinite(p) & np.isfinite(y)
        ic = None
        if int(ok.sum()) >= 20 and np.unique(p[ok]).size > 1 and np.unique(y[ok]).size > 1:
            ic = float(spearmanr(p[ok], y[ok]).statistic)
        daily.append({"trade_date": str(d), "daily_ic_20d": ic})
    valid_daily = [r for r in daily if r["daily_ic_20d"] is not None and math.isfinite(r["daily_ic_20d"])]
    ics = np.asarray([r["daily_ic_20d"] for r in valid_daily], dtype=np.float64)
    mean_ic = float(ics.mean())
    ci_lo, ci_hi = bootstrap(ics)
    ck("mean_ic_recomputed", close(mean_ic, gate_actual["mean_daily_ic_20d"]))
    ck("bootstrap_recomputed", close(ci_lo, gate_actual["bootstrap_95pct_ci"]["lower"]) and close(ci_hi, gate_actual["bootstrap_95pct_ci"]["upper"]))

    ddf = pd.DataFrame(valid_daily)
    ddf["quarter"] = pd.PeriodIndex(pd.to_datetime(ddf["trade_date"]), freq="Q").astype(str)
    qmeans = ddf.groupby("quarter", sort=True)["daily_ic_20d"].mean().to_dict()
    expected_q = exe["fingerprint_basis"]["metric_semantics"]["expected_quarters"]
    q_recomputed = []
    for qtr in expected_q:
        v = qmeans.get(qtr)
        q_recomputed.append({"quarter": qtr, "mean_daily_ic_20d": None if v is None else float(v), "positive": bool(v is not None and v > 0)})
    ck("quarter_count_exact", [x["quarter"] for x in quarter_actual["quarters"]] == expected_q and len(expected_q) == 8)
    q_ok = len(q_recomputed) == len(quarter_actual["quarters"])
    if q_ok:
        for a, b in zip(q_recomputed, quarter_actual["quarters"]):
            if a["quarter"] != b["quarter"] or a["positive"] != b["positive"]:
                q_ok = False; break
            if a["mean_daily_ic_20d"] is None or b["mean_daily_ic_20d"] is None:
                if a["mean_daily_ic_20d"] is not b["mean_daily_ic_20d"]:
                    q_ok = False; break
            elif not close(a["mean_daily_ic_20d"], b["mean_daily_ic_20d"]):
                q_ok = False; break
    ck("quarters_recomputed", q_ok)
    positive_q = sum(x["positive"] for x in q_recomputed)

    pred_dates = [str(r[0]) for r in con.execute(
        f"SELECT DISTINCT trade_date FROM read_parquet('{str(pred_path).replace(chr(39), chr(39)*2)}') WHERE trade_date<=DATE '{LATEST_VALID20}' ORDER BY trade_date"
    ).fetchall()]
    rebalances = pred_dates[::20]
    ck("rebalance_anchor_exact", bool(rebalances) and rebalances[0] == OOS_START and econ_actual.get("rebalance_dates") == rebalances)
    df["trade_date_str"] = df["trade_date"].astype(str)
    aggregate = {}
    econ_ok = True
    for cov in [0.05, 0.10, 0.20]:
        actual_cov = econ_actual["coverages"][f"{int(cov*100):02d}pct"]
        cohorts = []
        for d in rebalances:
            g = df[df["trade_date_str"] == d].copy()
            if g.empty:
                econ_ok = False; break
            g.sort_values(["prediction", "exchange", "code"], ascending=[False, True, True], kind="mergesort", inplace=True)
            k = max(1, int(math.ceil(cov * len(g))))
            top = g.iloc[:k]
            entry = sorted({str(x) for x in top["entry_date"]})
            exitd = sorted({str(x) for x in top["exit_date_20d"]})
            if len(entry) != 1 or len(exitd) != 1:
                econ_ok = False; break
            gross = float(top["excess_return_20d"].mean())
            cost = roundtrip_cost(entry[0], exitd[0])
            cohorts.append((d, len(g), k, gross, cost, gross - cost))
        if not econ_ok:
            break
        aggregate[f"{int(cov*100):02d}pct"] = float(np.mean([x[5] for x in cohorts]))
        if not close(aggregate[f"{int(cov*100):02d}pct"], actual_cov["aggregate_net_excess_return_20d"]):
            econ_ok = False; break
        if len(cohorts) != actual_cov["cohort_count"]:
            econ_ok = False; break
        for x, y in zip(cohorts, actual_cov["cohorts"]):
            if x[0] != y["decision_date"] or x[1] != y["eligible_valid20_rows"] or x[2] != y["selected_rows"] or not close(x[3], y["gross_excess_return_20d"]) or not close(x[4], y["roundtrip_cost"]) or not close(x[5], y["net_excess_return_20d"]):
                econ_ok = False; break
    ck("economic_metrics_recomputed", econ_ok)

    gate_recomputed = {
        "mean_daily_spearman_ic_20d_gt_0": mean_ic > 0,
        "block_bootstrap_95pct_ci_lower_bound_mean_daily_ic_20d_gt_0": ci_lo > 0,
        "positive_mean_ic_in_at_least_6_of_8_calendar_quarters": positive_q >= 6 and len(q_recomputed) == 8 and all(x["mean_daily_ic_20d"] is not None for x in q_recomputed),
        "top_10pct_net_excess_return_20d_at_15bps_per_side_gt_0": aggregate.get("10pct", float("-inf")) > 0,
        "no_sign_inversion_5pct_or_20pct_coverage": aggregate.get("05pct", float("-inf")) >= 0 and aggregate.get("20pct", float("-inf")) >= 0,
        "pbo_le_0_20_carried_from_development": 0.11904761904761904 <= 0.20,
        "dsr_ge_0_95_carried_from_development": 0.9999989891602007 >= 0.95,
    }
    ck("gate_checks_recomputed", gate_actual.get("checks") == gate_recomputed)
    ck("gate_status_recomputed", gate_actual.get("status") == ("PASS" if all(gate_recomputed.values()) else "FAIL"))
    ck("lockbox_not_opened_on_oos_result", gate_actual.get("final_lockbox_open_allowed") is False)

    required = [
        "oos_execution_manifest.json", "oos_predictions.parquet", "oos_daily_metrics.parquet",
        "oos_quarter_metrics.json", "oos_economic_metrics.json", "oos_gate_result.json",
        "authorization_consumption.json"
    ]
    hashes = json.loads((out / "artifact_hashes.json").read_text(encoding="utf-8"))
    ck("artifact_hashes_match", all(hashes.get(n) == sha256_file(out / n) for n in required))

    audit = {
        "schema_version": 1,
        "gate": "STAGE4_ALPHA_V1_OOS_VALIDATION_INDEPENDENT_AUDIT",
        "execution_head": args.execution_head,
        "pass": len(failures) == 0,
        "failed_checks": failures,
        "checks": checks,
        "recomputed": {
            "prediction_rows": int(prow),
            "label_rows": int(lrow),
            "valid_20d_rows": int(valid20),
            "evaluation_rows": int(erow),
            "mean_daily_ic_20d": mean_ic,
            "bootstrap_95pct_ci": {"lower": ci_lo, "upper": ci_hi},
            "positive_quarters": positive_q,
            "coverage_net_excess": aggregate,
            "gate_pass": all(gate_recomputed.values()),
        },
        "model_fit_executed_by_audit": False,
        "oos_predictions_recomputed_by_audit": False,
        "oos_labels_rebuilt_by_audit": False,
        "lockbox_accessed": False,
        "authoritative_model_output": False,
    }
    Path(args.out).write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))
    return 0 if audit["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
