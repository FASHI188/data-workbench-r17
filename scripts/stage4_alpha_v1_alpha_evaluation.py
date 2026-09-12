#!/usr/bin/env python3
from __future__ import annotations
import json,math
from pathlib import Path
from typing import Any
from stage4_alpha_v1_label_materialization import q

def handling_rate(date_str: str) -> float:
    return 0.0000341 if date_str >= "2023-08-28" else 0.0000487

def stamp_rate(date_str: str) -> float:
    return 0.0005 if date_str >= "2023-08-28" else 0.001

def cohort_roundtrip_cost(entry_date: str, exit_date: str) -> float:
    return 0.003 + handling_rate(entry_date) + handling_rate(exit_date) + stamp_rate(exit_date)

def moving_block_bootstrap_mean_ci(values, block: int = 20, resamples: int = 10000, seed: int = 20260817):
    import numpy as np

    x = np.asarray(values, dtype=np.float64)
    if x.ndim != 1 or len(x) < block or not np.isfinite(x).all():
        raise ValueError("invalid bootstrap series")
    rng = np.random.Generator(np.random.PCG64(seed))
    need = math.ceil(len(x) / block)
    max_start = len(x) - block + 1
    means = np.empty(resamples, dtype=np.float64)
    for i in range(resamples):
        starts = rng.integers(0, max_start, size=need)
        sample = np.concatenate([x[s : s + block] for s in starts])[: len(x)]
        means[i] = sample.mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))

def evaluate_alpha(predictions: Path, labels: Path, out: Path, *, latest_valid20: str, expected_start: str, expected_quarters: list[str], positive_quarters_required: int, bootstrap_resamples: int = 10000) -> dict[str, Any]:
    import duckdb
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    from scipy.stats import spearmanr

    con = duckdb.connect()
    allp = out / "oos_all_economic_rows.parquet"
    icp = out / "oos_evaluation_rows.parquet"
    con.execute(f"COPY (SELECT p.trade_date,p.exchange,p.code,p.prediction,l.valid_label_20d,l.censor_reason_20d,l.entry_date,l.exit_date_20d,l.excess_return_20d,l.stock_total_return_20d,l.benchmark_return_20d FROM read_parquet({q(str(predictions))}) p JOIN read_parquet({q(str(labels))}) l USING(trade_date,exchange,code) WHERE p.trade_date<=DATE '{latest_valid20}' ORDER BY p.trade_date,p.exchange,p.code) TO {q(str(allp))} (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.execute(f"COPY (SELECT trade_date,exchange,code,prediction,entry_date,exit_date_20d,excess_return_20d,stock_total_return_20d,benchmark_return_20d FROM read_parquet({q(str(allp))}) WHERE valid_label_20d ORDER BY trade_date,exchange,code) TO {q(str(icp))} (FORMAT PARQUET,COMPRESSION ZSTD)")
    er, emin, emax = con.execute(f"SELECT count(*),min(trade_date),max(trade_date) FROM read_parquet({q(str(icp))})").fetchone()
    if er <= 0 or str(emax) > latest_valid20:
        raise ValueError("invalid IC population")
    df = pq.read_table(icp).to_pandas()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    daily = []
    for d, g in df.groupby("trade_date", sort=True):
        p = g["prediction"].to_numpy(dtype=float)
        y = g["excess_return_20d"].to_numpy(dtype=float)
        ok = np.isfinite(p) & np.isfinite(y)
        ic = None
        if int(ok.sum()) >= 20 and np.unique(p[ok]).size > 1 and np.unique(y[ok]).size > 1:
            ic = float(spearmanr(p[ok], y[ok]).statistic)
        daily.append({"trade_date": str(d), "n20": int(ok.sum()), "daily_ic_20d": ic})
    valid_daily = [r for r in daily if r["daily_ic_20d"] is not None and math.isfinite(r["daily_ic_20d"])]
    ics = np.asarray([r["daily_ic_20d"] for r in valid_daily], dtype=np.float64)
    if not len(ics):
        raise ValueError("no valid daily IC")
    mean_ic = float(ics.mean())
    lo, hi = moving_block_bootstrap_mean_ci(ics, resamples=bootstrap_resamples)
    ddf = pd.DataFrame(valid_daily)
    ddf["period"] = pd.PeriodIndex(pd.to_datetime(ddf["trade_date"]), freq="Q").astype(str)
    qmeans = ddf.groupby("period", sort=True)["daily_ic_20d"].mean().to_dict()
    quarters = []
    for quarter in expected_quarters:
        value = qmeans.get(quarter)
        quarters.append({"quarter": quarter, "mean_daily_ic_20d": None if value is None else float(value), "positive": bool(value is not None and value > 0)})
    positive_quarters = sum(x["positive"] for x in quarters)
    pq.write_table(pa.Table.from_pylist(daily), out / "oos_daily_metrics.parquet", compression="zstd")
    (out / "oos_quarter_metrics.json").write_text(json.dumps({"schema_version": 1, "expected_quarters": expected_quarters, "positive_quarter_count": positive_quarters, "quarters": quarters}, indent=2) + "\n", encoding="utf-8")

    alldf = pq.read_table(allp).to_pandas()
    alldf["trade_date"] = pd.to_datetime(alldf["trade_date"]).dt.date
    alldf["trade_date_str"] = alldf["trade_date"].astype(str)
    dates = sorted(alldf["trade_date_str"].unique().tolist())
    if not dates or dates[0] != expected_start:
        raise ValueError("rebalance anchor missing")
    rebalances = dates[::20]
    econ = {
        "selection_population": "ALL_PREDICTED_ROWS_BEFORE_LABEL_VALIDITY_FILTER",
        "selected_invalid_label_action": "FAIL_CLOSED_NO_BACKFILL_NO_POST_SELECTION_DROP",
        "rebalance_anchor": expected_start,
        "rebalance_every_sessions": 20,
        "rebalance_dates": rebalances,
        "coverages": {},
    }
    for cov in (0.05, 0.10, 0.20):
        cohorts = []
        coverage_valid = True
        for date in rebalances:
            g = alldf[alldf["trade_date_str"] == date].copy()
            g.sort_values(["prediction", "exchange", "code"], ascending=[False, True, True], kind="mergesort", inplace=True)
            k = max(1, int(math.ceil(cov * len(g))))
            top = g.iloc[:k].copy()
            mask = top["valid_label_20d"].fillna(False).astype(bool) & np.isfinite(top["excess_return_20d"].to_numpy(dtype=float, na_value=np.nan))
            invalid = int((~mask).sum())
            row = {"decision_date": date, "eligible_prediction_rows": int(len(g)), "selected_rows": k, "selected_invalid_20d_rows": invalid, "cohort_valid": invalid == 0}
            if invalid:
                coverage_valid = False
                row.update({"entry_date": None, "exit_date": None, "gross_excess_return_20d": None, "roundtrip_cost": None, "net_excess_return_20d": None})
            else:
                entries = sorted({str(x) for x in top["entry_date"]})
                exits = sorted({str(x) for x in top["exit_date_20d"]})
                if len(entries) != 1 or len(exits) != 1:
                    raise ValueError("cohort dates not common")
                gross = float(top["excess_return_20d"].mean())
                cost = cohort_roundtrip_cost(entries[0], exits[0])
                row.update({"entry_date": entries[0], "exit_date": exits[0], "gross_excess_return_20d": gross, "roundtrip_cost": cost, "net_excess_return_20d": gross - cost})
            cohorts.append(row)
        aggregate = None if not coverage_valid else float(np.mean([x["net_excess_return_20d"] for x in cohorts]))
        econ["coverages"][f"{int(cov * 100):02d}pct"] = {"coverage_valid": coverage_valid, "aggregate_net_excess_return_20d": aggregate, "cohort_count": len(cohorts), "cohorts": cohorts}
    c05, c10, c20 = econ["coverages"]["05pct"], econ["coverages"]["10pct"], econ["coverages"]["20pct"]
    checks = {
        "mean_daily_spearman_ic_20d_gt_0": mean_ic > 0,
        "block_bootstrap_95pct_ci_lower_bound_mean_daily_ic_20d_gt_0": lo > 0,
        "positive_mean_ic_in_at_least_6_of_8_calendar_quarters": positive_quarters >= positive_quarters_required and len(quarters) == len(expected_quarters) and all(r["mean_daily_ic_20d"] is not None for r in quarters),
        "top_10pct_net_excess_return_20d_at_15bps_per_side_gt_0": c10["coverage_valid"] and c10["aggregate_net_excess_return_20d"] > 0,
        "no_sign_inversion_5pct_or_20pct_coverage": c05["coverage_valid"] and c20["coverage_valid"] and c05["aggregate_net_excess_return_20d"] >= 0 and c20["aggregate_net_excess_return_20d"] >= 0,
        "pbo_le_0_20_carried_from_development": 0.11904761904761904 <= 0.20,
        "dsr_ge_0_95_carried_from_development": 0.9999989891602007 >= 0.95,
    }
    gate_pass = all(checks.values())
    (out / "oos_economic_metrics.json").write_text(json.dumps(econ, indent=2) + "\n", encoding="utf-8")
    (out / "oos_gate_result.json").write_text(json.dumps({"schema_version": 1, "status": "PASS" if gate_pass else "FAIL", "mean_daily_ic_20d": mean_ic, "bootstrap_95pct_ci": {"lower": lo, "upper": hi}, "positive_quarters": positive_quarters, "checks": checks, "gate_logic": "ALL_REQUIRED_MUST_PASS", "oos_failure_action": "NO_PROMOTION_NO_RETUNING_ON_OOS", "final_lockbox_open_allowed": False}, indent=2) + "\n", encoding="utf-8")
    return {"evaluation_rows": int(er), "evaluation_date_min": str(emin), "evaluation_date_max": str(emax), "valid_daily_ic_days": len(valid_daily), "mean_daily_ic_20d": mean_ic, "bootstrap_ci_lower": lo, "bootstrap_ci_upper": hi, "positive_quarters": positive_quarters, "economic_05pct_coverage_valid": c05["coverage_valid"], "economic_10pct_coverage_valid": c10["coverage_valid"], "economic_20pct_coverage_valid": c20["coverage_valid"], "gate_pass": gate_pass}

