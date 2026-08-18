#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import pickle
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

AUTH_FP = "d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d"
EXEC_FP = "b61333a33870ac079cd2dc94c71cb53e3f1a267dc9ff8e26e2ef7d9fea95ed2e"
SOURCE_CV_AUTH_FP = "2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c"
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


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def qi(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def handling_rate(date_str: str) -> float:
    return 0.0000341 if date_str >= "2023-08-28" else 0.0000487


def stamp_rate(date_str: str) -> float:
    return 0.0005 if date_str >= "2023-08-28" else 0.001


def cohort_roundtrip_cost(entry_date: str, exit_date: str) -> float:
    return 0.0015 + 0.0015 + handling_rate(entry_date) + handling_rate(exit_date) + stamp_rate(exit_date)


def moving_block_bootstrap_mean_ci(values, *, block=20, resamples=10000, seed=20260817):
    import numpy as np
    x = np.asarray(values, dtype=np.float64)
    if x.ndim != 1 or len(x) < block or not np.isfinite(x).all():
        raise ValueError("invalid bootstrap series")
    rng = np.random.Generator(np.random.PCG64(seed))
    max_start = len(x) - block + 1
    blocks_needed = math.ceil(len(x) / block)
    means = np.empty(resamples, dtype=np.float64)
    for i in range(resamples):
        starts = rng.integers(0, max_start, size=blocks_needed)
        sample = np.concatenate([x[s:s + block] for s in starts])[: len(x)]
        means[i] = float(sample.mean())
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def synthetic_self_test() -> int:
    import numpy as np
    x = np.linspace(0.001, 0.05, 80)
    a = moving_block_bootstrap_mean_ci(x, resamples=250)
    b = moving_block_bootstrap_mean_ci(x, resamples=250)
    assert a == b and a[0] > 0
    assert abs(cohort_roundtrip_cost("2023-08-01", "2023-08-25") - (0.003 + 2 * 0.0000487 + 0.001)) < 1e-15
    assert abs(cohort_roundtrip_cost("2023-08-25", "2023-09-22") - (0.003 + 0.0000487 + 0.0000341 + 0.0005)) < 1e-15
    scores = [0.5, 0.5, 0.4]
    keys = [("SZSE", "000002"), ("SSE", "600001"), ("SSE", "600002")]
    ordered = sorted(range(3), key=lambda i: (-scores[i], keys[i][0], keys[i][1]))
    assert ordered == [1, 0, 2]
    print(json.dumps({"synthetic_self_test": "PASS", "bootstrap_ci": a, "fit_calls": 0}))
    return 0


def validate_authority(args):
    auth = json.loads(Path(args.authorization).read_text(encoding="utf-8"))
    exe = json.loads(Path(args.execution_contract).read_text(encoding="utf-8"))
    source = json.loads(Path(args.source_cv_authorization).read_text(encoding="utf-8"))
    state = json.loads(Path(args.accepted_state).read_text(encoding="utf-8"))
    if auth["fingerprint"] != AUTH_FP or canonical_hash(auth["fingerprint_basis"]) != AUTH_FP:
        raise ValueError("OOS authorization fingerprint mismatch")
    if exe["fingerprint"] != EXEC_FP or canonical_hash(exe["fingerprint_basis"]) != EXEC_FP:
        raise ValueError("OOS execution contract fingerprint mismatch")
    if source["fingerprint"] != SOURCE_CV_AUTH_FP or canonical_hash(source["fingerprint_basis"]) != SOURCE_CV_AUTH_FP:
        raise ValueError("source CV authorization mismatch")
    p = state["permissions"]
    if p.get("oos_execution_pr_creation_allowed") is not True:
        raise ValueError("accepted state does not permit OOS execution PR")
    if p.get("oos_label_access_allowed") is not False:
        raise ValueError("integration OOS label access must remain false before dispatch")
    if int(p.get("oos_label_bearing_execution_runs_remaining", -1)) != 1:
        raise ValueError("expected exactly one OOS label-bearing run remaining")
    for k in ["model_fit_allowed", "lockbox_label_access_allowed", "live_signal_allowed", "main_merge_allowed", "authoritative_model_output_allowed"]:
        if p.get(k) is not False:
            raise ValueError(f"sealed permission unexpectedly open: {k}")
    b = exe["fingerprint_basis"]
    if b["authority"]["oos_authorization_fingerprint"] != AUTH_FP:
        raise ValueError("execution contract not bound to OOS authorization")
    if b["authority"]["integration_base_sha"] != "c484b6f8e0b404f790995274b768fdde3000bd8d":
        raise ValueError("execution integration base mismatch")
    if b["hard_boundaries"]["fit"] or b["hard_boundaries"]["lockbox_access"] or b["hard_boundaries"]["main_merge"]:
        raise ValueError("execution hard boundary drift")
    return auth, exe, source, state


def runtime_check(exe):
    import duckdb
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import scipy
    import sklearn
    got = {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
        "pyarrow": pa.__version__,
        "duckdb": duckdb.__version__,
        "pandas": pd.__version__,
        "thread_env": {k: os.getenv(k) for k in ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"]},
    }
    expected = exe["fingerprint_basis"]["runtime"]
    if got != expected:
        raise ValueError(f"runtime mismatch: {got} != {expected}")
    return got


def transform_frame(df, preprocess, source):
    import numpy as np
    features = list(preprocess["feature_columns"])
    names_expected = list(preprocess["model_input_feature_names"])
    stats = preprocess["continuous_stats"]
    levels = list(preprocess["regime_levels"])
    roles = source["fingerprint_basis"]["feature_roles"]
    continuous = set(roles["continuous_clip_train_only"])
    binary = set(roles["binary_missing_indicators"])
    financial = set(roles["financial_signed_log1p"])
    cols = []
    names = []
    for c in features:
        if c == "regime_state":
            s = df[c]
            for i, lev in enumerate(levels):
                cols.append((s.astype("string") == str(lev)).to_numpy(dtype=np.float32))
                names.append(f"regime__{i}")
            unknown = s.isna() | ~s.astype("string").isin([str(x) for x in levels])
            cols.append(unknown.to_numpy(dtype=np.float32))
            names.append("regime__unknown")
        elif c in binary:
            cols.append(df[c].to_numpy(dtype=np.float32, na_value=np.nan))
            names.append(c)
        elif c in continuous:
            x = df[c].to_numpy(dtype=np.float64, na_value=np.nan)
            if c in financial:
                x = np.sign(x) * np.log1p(np.abs(x))
            st = stats[c]
            x = np.where(np.isnan(x), np.nan, np.clip(x, float(st["q001"]), float(st["q999"])))
            cols.append(x.astype(np.float32))
            names.append(c)
        else:
            raise ValueError(f"unclassified feature {c}")
    if names != names_expected:
        raise ValueError("transformed feature names drift")
    X = np.column_stack(cols).astype(np.float32, copy=False)
    if np.isinf(X).any():
        raise ValueError("infinite transformed OOS feature")
    return X


def materialize_predictions(args, source, preprocess, model, work: Path, out: Path, execution_head: str):
    import duckdb
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    matrix = Path(args.matrix)
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='6GB'")
    (work / "duckdb-pred-tmp").mkdir(parents=True, exist_ok=True)
    con.execute(f"PRAGMA temp_directory={q(str(work / 'duckdb-pred-tmp'))}")
    raw = work / "oos_features_raw.parquet"
    features = list(preprocess["feature_columns"])
    feat_sql = ",".join(qi(c) for c in features)
    con.execute(f"""
      COPY (
        SELECT CAST(trade_date AS DATE) AS trade_date,
               upper(CAST(exchange AS VARCHAR)) AS exchange,
               lpad(CAST(code AS VARCHAR),6,'0') AS code,
               {feat_sql}
        FROM read_parquet({q(str(matrix))})
        WHERE CAST(trade_date AS DATE) BETWEEN DATE '{OOS_START}' AND DATE '{OOS_END}'
        ORDER BY trade_date,exchange,code
      ) TO {q(str(raw))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    rows, uniq, dmin, dmax = con.execute(
        f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date) FROM read_parquet({q(str(raw))})"
    ).fetchone()
    if rows <= 0 or rows != uniq or str(dmin) != OOS_START or str(dmax) != OOS_END:
        raise ValueError(f"OOS prediction population mismatch rows={rows} uniq={uniq} dates={dmin}..{dmax}")
    pf = pq.ParquetFile(raw)
    pred_path = out / "oos_predictions.parquet"
    writer = None
    consumed = False
    pred_rows = 0
    try:
        for batch in pf.iter_batches(batch_size=100000):
            df = pa.Table.from_batches([batch]).to_pandas()
            X = transform_frame(df, preprocess, source)
            if not consumed:
                consumption = {
                    "schema_version": 1,
                    "status": "CONSUMED",
                    "authorization_fingerprint": AUTH_FP,
                    "execution_contract_fingerprint": EXEC_FP,
                    "execution_head": execution_head,
                    "consumption_event": "FIRST_OOS_PREDICTION_COMPUTATION",
                    "consumed_at_utc": datetime.now(timezone.utc).isoformat(),
                    "oos_label_read_before_consumption": False,
                    "lockbox_accessed": False,
                    "fit_executed": False,
                }
                (out / "authorization_consumption.json").write_text(json.dumps(consumption, indent=2) + "\n", encoding="utf-8")
                consumed = True
            pred = np.asarray(model.predict(X), dtype=np.float64)
            if pred.shape[0] != len(df) or not np.isfinite(pred).all():
                raise ValueError("invalid OOS predictions")
            table = pa.table({
                "trade_date": pa.array(df["trade_date"]),
                "exchange": pa.array(df["exchange"].astype(str)),
                "code": pa.array(df["code"].astype(str)),
                "prediction": pa.array(pred),
            })
            if writer is None:
                writer = pq.ParquetWriter(pred_path, table.schema, compression="zstd")
            writer.write_table(table)
            pred_rows += len(df)
            del df, X, pred, table
            gc.collect()
    finally:
        if writer is not None:
            writer.close()
    if not consumed or pred_rows != rows:
        raise ValueError("prediction execution did not consume authorization exactly as expected")
    return {"prediction_rows": int(pred_rows), "prediction_date_min": str(dmin), "prediction_date_max": str(dmax)}


def market_source_files(g3_root: Path):
    rx = re.compile(r"(?:sse|szse)_(20\d\d)(?:_shard\d+)?\.csv\.gz$", re.I)
    files = []
    years = set()
    for p in g3_root.rglob("*.csv.gz"):
        m = rx.search(p.name)
        if not m:
            continue
        year = int(m.group(1))
        if year in (2023, 2024):
            files.append(p)
            years.add(year)
    files = sorted(files)
    if not files or years != {2023, 2024}:
        raise ValueError(f"missing exact 2023/2024 physical market sources, years={sorted(years)}")
    if any(int(rx.search(p.name).group(1)) >= 2025 for p in files):
        raise ValueError("lockbox-year market file entered OOS source list")
    return files


def materialize_labels(args, work: Path):
    import duckdb
    files = market_source_files(Path(args.g3_root))
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='7GB'")
    (work / "duckdb-label-tmp").mkdir(parents=True, exist_ok=True)
    con.execute(f"PRAGMA temp_directory={q(str(work / 'duckdb-label-tmp'))}")
    flist = "[" + ",".join(q(str(p)) for p in files) + "]"
    con.execute(f"""
      CREATE TEMP TABLE market_raw AS
      SELECT upper(exchange) AS exchange,
             lpad(CAST(code AS VARCHAR),6,'0') AS code,
             CAST(trade_date AS DATE) AS trade_date,
             CAST(open AS DOUBLE) AS open,
             CAST(close AS DOUBLE) AS close
      FROM read_csv({flist}, header=true, auto_detect=true, union_by_name=true)
      WHERE CAST(trade_date AS DATE) >= DATE '{OOS_START}'
        AND CAST(trade_date AS DATE) < DATE '{LOCKBOX_START}'
    """)
    market_rows, mmin, mmax = con.execute("SELECT count(*),min(trade_date),max(trade_date) FROM market_raw").fetchone()
    if market_rows <= 0 or str(mmax) >= LOCKBOX_START or str(mmax) > OOS_END:
        raise ValueError(f"market boundary violation {mmin}..{mmax}")
    con.execute(f"""
      CREATE TEMP TABLE g5 AS
      SELECT upper(exchange) AS exchange,
             lpad(CAST(code AS VARCHAR),6,'0') AS code,
             CAST(ex_date AS DATE) AS ex_date,
             CAST(cumulative_back_adjust_multiplier AS DOUBLE) AS factor
      FROM read_csv({q(str(Path(args.g5_chain)))},header=true,auto_detect=true,compression='gzip')
      WHERE CAST(ex_date AS DATE) < DATE '{LOCKBOX_START}'
      ORDER BY exchange,code,ex_date
    """)
    con.execute("""
      CREATE TEMP TABLE market AS
      SELECT m.exchange,m.code,m.trade_date,m.open,m.close,coalesce(g.factor,1.0) AS factor
      FROM (SELECT * FROM market_raw ORDER BY exchange,code,trade_date) m
      ASOF LEFT JOIN g5 g
        ON m.exchange=g.exchange AND m.code=g.code AND m.trade_date>=g.ex_date
    """)
    con.execute(f"""
      CREATE TEMP TABLE lifecycle AS
      SELECT upper(exchange) AS exchange,
             lpad(CAST(code AS VARCHAR),6,'0') AS code,
             CAST(listed_from AS DATE) AS listed_from,
             CASE WHEN listed_to_exclusive IS NULL OR trim(CAST(listed_to_exclusive AS VARCHAR))=''
                  THEN NULL ELSE CAST(listed_to_exclusive AS DATE) END AS listed_to_exclusive
      FROM read_csv({q(str(Path(args.g2_intervals)))},header=true,auto_detect=true)
    """)
    con.execute(f"""
      CREATE TEMP TABLE decisions AS
      SELECT CAST(trade_date AS DATE) AS decision_date,
             upper(CAST(exchange AS VARCHAR)) AS exchange,
             lpad(CAST(code AS VARCHAR),6,'0') AS code
      FROM read_parquet({q(str(Path(args.matrix)))})
      WHERE CAST(trade_date AS DATE) BETWEEN DATE '{OOS_START}' AND DATE '{OOS_END}'
    """)
    drows, duniq = con.execute("SELECT count(*),count(DISTINCT (decision_date,exchange,code)) FROM decisions").fetchone()
    if drows != duniq:
        raise ValueError("OOS decision keys not unique")
    con.execute("""
      CREATE TEMP TABLE calendar AS
      SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 AS session_idx
      FROM (SELECT DISTINCT trade_date FROM market_raw)
      ORDER BY trade_date
    """)
    con.execute("""
      CREATE TEMP TABLE schedule AS
      SELECT d.*, c.session_idx,
             e.trade_date AS entry_date,
             x5.trade_date AS exit_date_5d,
             x20.trade_date AS exit_date_20d
      FROM decisions d
      JOIN calendar c ON c.trade_date=d.decision_date
      LEFT JOIN calendar e ON e.session_idx=c.session_idx+1
      LEFT JOIN calendar x5 ON x5.session_idx=c.session_idx+5
      LEFT JOIN calendar x20 ON x20.session_idx=c.session_idx+20
    """)
    con.execute(f"""
      CREATE TEMP TABLE raw_labels AS
      SELECT s.decision_date,s.exchange,s.code,s.entry_date,s.exit_date_5d,s.exit_date_20d,
             ep.open AS entry_open_raw,ep.factor AS entry_factor,
             p5.close AS exit_close_5d_raw,p5.factor AS exit_factor_5d,
             p20.close AS exit_close_20d_raw,p20.factor AS exit_factor_20d,
             lc.listed_to_exclusive,
             CASE
               WHEN s.exit_date_5d IS NULL THEN 'PARTITION_BOUNDARY_INCOMPLETE_HORIZON'
               WHEN lc.listed_to_exclusive IS NOT NULL AND lc.listed_to_exclusive>s.decision_date AND lc.listed_to_exclusive<=s.exit_date_5d THEN 'DELISTING_HORIZON_CENSOR_NO_TERMINAL_IMPUTATION'
               WHEN ep.open IS NULL OR ep.open<=0 THEN 'MISSING_ENTRY_OPEN'
               WHEN p5.close IS NULL OR p5.close<=0 THEN 'MISSING_EXIT_CLOSE'
               ELSE 'VALID'
             END AS censor_reason_5d,
             CASE
               WHEN s.exit_date_20d IS NULL OR s.decision_date>DATE '{LATEST_VALID20}' THEN 'PARTITION_BOUNDARY_INCOMPLETE_HORIZON'
               WHEN lc.listed_to_exclusive IS NOT NULL AND lc.listed_to_exclusive>s.decision_date AND lc.listed_to_exclusive<=s.exit_date_20d THEN 'DELISTING_HORIZON_CENSOR_NO_TERMINAL_IMPUTATION'
               WHEN ep.open IS NULL OR ep.open<=0 THEN 'MISSING_ENTRY_OPEN'
               WHEN p20.close IS NULL OR p20.close<=0 THEN 'MISSING_EXIT_CLOSE'
               ELSE 'VALID'
             END AS censor_reason_20d
      FROM schedule s
      LEFT JOIN market ep ON ep.exchange=s.exchange AND ep.code=s.code AND ep.trade_date=s.entry_date
      LEFT JOIN market p5 ON p5.exchange=s.exchange AND p5.code=s.code AND p5.trade_date=s.exit_date_5d
      LEFT JOIN market p20 ON p20.exchange=s.exchange AND p20.code=s.code AND p20.trade_date=s.exit_date_20d
      LEFT JOIN lifecycle lc ON lc.exchange=s.exchange AND lc.code=s.code
        AND s.decision_date>=lc.listed_from
        AND (lc.listed_to_exclusive IS NULL OR s.decision_date<lc.listed_to_exclusive)
    """)
    con.execute("""
      CREATE TEMP TABLE stock_returns AS
      SELECT *,
        CASE WHEN censor_reason_5d='VALID'
             THEN (exit_close_5d_raw*exit_factor_5d)/(entry_open_raw*entry_factor)-1 END AS stock_total_return_5d,
        CASE WHEN censor_reason_20d='VALID'
             THEN (exit_close_20d_raw*exit_factor_20d)/(entry_open_raw*entry_factor)-1 END AS stock_total_return_20d
      FROM raw_labels
    """)
    con.execute("""
      CREATE TEMP TABLE benchmarks AS
      SELECT decision_date,
             avg(stock_total_return_5d) FILTER(WHERE censor_reason_5d='VALID') AS benchmark_return_5d,
             count(stock_total_return_5d) FILTER(WHERE censor_reason_5d='VALID') AS benchmark_n_5d,
             avg(stock_total_return_20d) FILTER(WHERE censor_reason_20d='VALID') AS benchmark_return_20d,
             count(stock_total_return_20d) FILTER(WHERE censor_reason_20d='VALID') AS benchmark_n_20d
      FROM stock_returns GROUP BY decision_date
    """)
    labels = work / "oos_labels.parquet"
    con.execute(f"""
      COPY (
        SELECT r.decision_date AS trade_date,r.exchange,r.code,
               r.entry_date,r.exit_date_5d,r.exit_date_20d,
               r.censor_reason_5d='VALID' AS valid_label_5d,
               r.censor_reason_20d='VALID' AS valid_label_20d,
               r.censor_reason_5d,r.censor_reason_20d,
               r.stock_total_return_5d,b.benchmark_return_5d,
               CASE WHEN r.censor_reason_5d='VALID' THEN r.stock_total_return_5d-b.benchmark_return_5d END AS excess_return_5d,
               r.stock_total_return_20d,b.benchmark_return_20d,
               CASE WHEN r.censor_reason_20d='VALID' THEN r.stock_total_return_20d-b.benchmark_return_20d END AS excess_return_20d
        FROM stock_returns r JOIN benchmarks b USING(decision_date)
        ORDER BY trade_date,exchange,code
      ) TO {q(str(labels))} (FORMAT PARQUET,COMPRESSION ZSTD)
    """)
    rows, uniq, valid20, maxvalid20, maxexit20 = con.execute(
        f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),count(*) FILTER(WHERE valid_label_20d),max(trade_date) FILTER(WHERE valid_label_20d),max(exit_date_20d) FILTER(WHERE valid_label_20d) FROM read_parquet({q(str(labels))})"
    ).fetchone()
    if rows != drows or uniq != drows or str(maxvalid20) > LATEST_VALID20 or str(maxexit20) > OOS_END:
        raise ValueError(f"OOS label boundary/population violation rows={rows}/{drows} maxvalid={maxvalid20} maxexit={maxexit20}")
    return {
        "label_rows": int(rows),
        "valid_20d_rows": int(valid20),
        "latest_valid_20d_decision": str(maxvalid20),
        "latest_valid_20d_exit": str(maxexit20),
        "market_source_file_count": len(files),
        "market_source_file_names": [p.name for p in files],
        "market_source_rows": int(market_rows),
        "market_source_min_date": str(mmin),
        "market_source_max_date": str(mmax),
    }


def evaluate(args, work: Path, out: Path, exe):
    import duckdb
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    from scipy.stats import spearmanr

    pred = out / "oos_predictions.parquet"
    labels = work / "oos_labels.parquet"
    eval_path = work / "oos_evaluation_rows.parquet"
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='7GB'")
    (work / "duckdb-eval-tmp").mkdir(parents=True, exist_ok=True)
    con.execute(f"PRAGMA temp_directory={q(str(work / 'duckdb-eval-tmp'))}")
    con.execute(f"""
      COPY (
        SELECT p.trade_date,p.exchange,p.code,p.prediction,
               l.entry_date,l.exit_date_20d,l.excess_return_20d,l.stock_total_return_20d,l.benchmark_return_20d
        FROM read_parquet({q(str(pred))}) p
        JOIN read_parquet({q(str(labels))}) l USING(trade_date,exchange,code)
        WHERE l.valid_label_20d
        ORDER BY p.trade_date,p.exchange,p.code
      ) TO {q(str(eval_path))} (FORMAT PARQUET,COMPRESSION ZSTD)
    """)
    erows, emin, emax = con.execute(f"SELECT count(*),min(trade_date),max(trade_date) FROM read_parquet({q(str(eval_path))})").fetchone()
    if erows <= 0 or str(emax) > LATEST_VALID20:
        raise ValueError("invalid evaluation population")
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
        daily.append({"trade_date": str(d), "n20": int(ok.sum()), "daily_ic_20d": ic})
    valid_daily = [r for r in daily if r["daily_ic_20d"] is not None and math.isfinite(r["daily_ic_20d"])]
    if not valid_daily:
        raise ValueError("no valid daily IC values")
    ic_series = np.asarray([r["daily_ic_20d"] for r in valid_daily], dtype=np.float64)
    mean_ic = float(ic_series.mean())
    ci_lo, ci_hi = moving_block_bootstrap_mean_ci(ic_series)

    ddf = pd.DataFrame(valid_daily)
    ddf["period"] = pd.PeriodIndex(pd.to_datetime(ddf["trade_date"]), freq="Q").astype(str)
    qmeans = ddf.groupby("period", sort=True)["daily_ic_20d"].mean().to_dict()
    expected_q = exe["fingerprint_basis"]["metric_semantics"]["expected_quarters"]
    quarter_rows = []
    for qtr in expected_q:
        v = qmeans.get(qtr)
        quarter_rows.append({"quarter": qtr, "mean_daily_ic_20d": None if v is None else float(v), "positive": bool(v is not None and v > 0)})
    positive_q = sum(r["positive"] for r in quarter_rows)

    dates = [str(r[0]) for r in con.execute(
        f"SELECT DISTINCT trade_date FROM read_parquet({q(str(pred))}) WHERE trade_date<=DATE '{LATEST_VALID20}' ORDER BY trade_date"
    ).fetchall()]
    if not dates or dates[0] != OOS_START:
        raise ValueError("rebalance anchor missing")
    rebalances = dates[::20]
    econ = {"rebalance_anchor": OOS_START, "rebalance_every_sessions": 20, "rebalance_dates": rebalances, "coverages": {}}
    df["trade_date_str"] = df["trade_date"].astype(str)
    for cov in [0.05, 0.10, 0.20]:
        cohorts = []
        for d in rebalances:
            g = df[df["trade_date_str"] == d].copy()
            if g.empty:
                raise ValueError(f"missing valid20 evaluation rows on rebalance date {d}")
            g.sort_values(["prediction", "exchange", "code"], ascending=[False, True, True], kind="mergesort", inplace=True)
            k = max(1, int(math.ceil(cov * len(g))))
            top = g.iloc[:k]
            gross = float(top["excess_return_20d"].mean())
            entry_dates = sorted({str(x) for x in top["entry_date"]})
            exit_dates = sorted({str(x) for x in top["exit_date_20d"]})
            if len(entry_dates) != 1 or len(exit_dates) != 1:
                raise ValueError("cohort entry/exit dates are not common market sessions")
            cost = cohort_roundtrip_cost(entry_dates[0], exit_dates[0])
            net = gross - cost
            cohorts.append({
                "decision_date": d,
                "entry_date": entry_dates[0],
                "exit_date": exit_dates[0],
                "eligible_valid20_rows": int(len(g)),
                "selected_rows": int(k),
                "gross_excess_return_20d": gross,
                "roundtrip_cost": cost,
                "net_excess_return_20d": net,
            })
        agg = float(np.mean([x["net_excess_return_20d"] for x in cohorts]))
        econ["coverages"][f"{int(cov*100):02d}pct"] = {"aggregate_net_excess_return_20d": agg, "cohort_count": len(cohorts), "cohorts": cohorts}

    gate_checks = {
        "mean_daily_spearman_ic_20d_gt_0": mean_ic > 0,
        "block_bootstrap_95pct_ci_lower_bound_mean_daily_ic_20d_gt_0": ci_lo > 0,
        "positive_mean_ic_in_at_least_6_of_8_calendar_quarters": positive_q >= 6 and len(quarter_rows) == 8 and all(r["mean_daily_ic_20d"] is not None for r in quarter_rows),
        "top_10pct_net_excess_return_20d_at_15bps_per_side_gt_0": econ["coverages"]["10pct"]["aggregate_net_excess_return_20d"] > 0,
        "no_sign_inversion_5pct_or_20pct_coverage": econ["coverages"]["05pct"]["aggregate_net_excess_return_20d"] >= 0 and econ["coverages"]["20pct"]["aggregate_net_excess_return_20d"] >= 0,
        "pbo_le_0_20_carried_from_development": 0.11904761904761904 <= 0.20,
        "dsr_ge_0_95_carried_from_development": 0.9999989891602007 >= 0.95,
    }
    gate_pass = all(gate_checks.values())
    daily_table = pa.Table.from_pylist(daily)
    pq.write_table(daily_table, out / "oos_daily_metrics.parquet", compression="zstd")
    quarter_payload = {
        "schema_version": 1,
        "expected_quarters": expected_q,
        "positive_quarter_count": positive_q,
        "quarters": quarter_rows,
    }
    (out / "oos_quarter_metrics.json").write_text(json.dumps(quarter_payload, indent=2) + "\n", encoding="utf-8")
    econ["cost_semantics"] = exe["fingerprint_basis"]["metric_semantics"]
    (out / "oos_economic_metrics.json").write_text(json.dumps(econ, indent=2) + "\n", encoding="utf-8")
    gate = {
        "schema_version": 1,
        "status": "PASS" if gate_pass else "FAIL",
        "mean_daily_ic_20d": mean_ic,
        "bootstrap_95pct_ci": {"lower": ci_lo, "upper": ci_hi},
        "positive_quarters": positive_q,
        "checks": gate_checks,
        "gate_logic": "ALL_REQUIRED_MUST_PASS",
        "oos_failure_action": "NO_PROMOTION_NO_RETUNING_ON_OOS",
        "final_lockbox_open_allowed": False,
    }
    (out / "oos_gate_result.json").write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
    return {
        "evaluation_rows": int(erows),
        "evaluation_date_min": str(emin),
        "evaluation_date_max": str(emax),
        "valid_daily_ic_days": len(valid_daily),
        "mean_daily_ic_20d": mean_ic,
        "bootstrap_ci_lower": ci_lo,
        "bootstrap_ci_upper": ci_hi,
        "positive_quarters": positive_q,
        "gate_pass": gate_pass,
    }


def main() -> int:
    if "--synthetic-self-test" in sys.argv:
        return synthetic_self_test()
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--preprocess", required=True)
    ap.add_argument("--g3-root", required=True)
    ap.add_argument("--g5-chain", required=True)
    ap.add_argument("--g2-intervals", required=True)
    ap.add_argument("--authorization", required=True)
    ap.add_argument("--execution-contract", required=True)
    ap.add_argument("--source-cv-authorization", required=True)
    ap.add_argument("--accepted-state", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--execution-head", required=True)
    args = ap.parse_args()

    auth, exe, source, state = validate_authority(args)
    runtime = runtime_check(exe)
    if not re.fullmatch(r"[0-9a-f]{40}", args.execution_head):
        raise ValueError("invalid exact execution head")
    if os.environ.get("EXECUTION_HEAD") != args.execution_head:
        raise ValueError("EXECUTION_HEAD environment mismatch")
    if sha256_file(Path(args.matrix)) != MATRIX_SHA:
        raise ValueError("feature matrix hash mismatch")
    if sha256_file(Path(args.model)) != MODEL_SHA:
        raise ValueError("frozen C007 model hash mismatch")
    if sha256_file(Path(args.preprocess)) != PREPROCESS_SHA:
        raise ValueError("frozen preprocess manifest hash mismatch")
    preprocess = json.loads(Path(args.preprocess).read_text(encoding="utf-8"))
    if preprocess.get("oos_rows_used") is not False or preprocess.get("lockbox_rows_used") is not False:
        raise ValueError("preprocessor not development-only")
    if preprocess.get("fit_rows") != 5103016:
        raise ValueError("preprocessor fit population drift")
    if preprocess.get("model_input_feature_count") != 45:
        raise ValueError("model input feature count drift")
    with Path(args.model).open("rb") as f:
        model = pickle.load(f)
    if int(getattr(model, "n_features_in_", -1)) != 45:
        raise ValueError("frozen model feature count mismatch")
    work = Path(args.work_dir); out = Path(args.out)
    work.mkdir(parents=True, exist_ok=True); out.mkdir(parents=True, exist_ok=True)

    pred_meta = materialize_predictions(args, source, preprocess, model, work, out, args.execution_head)
    label_meta = materialize_labels(args, work)
    eval_meta = evaluate(args, work, out, exe)

    consumption = json.loads((out / "authorization_consumption.json").read_text(encoding="utf-8"))
    manifest = {
        "schema_version": 1,
        "gate": "STAGE4_ALPHA_V1_OOS_VALIDATION_SINGLE_USE_EXECUTION",
        "execution_head": args.execution_head,
        "authorization_fingerprint": AUTH_FP,
        "execution_contract_fingerprint": EXEC_FP,
        "authorization_consumed": True,
        "consumption_event": consumption["consumption_event"],
        "runtime": runtime,
        "model_sha256": sha256_file(Path(args.model)),
        "preprocess_manifest_sha256": sha256_file(Path(args.preprocess)),
        "feature_matrix_sha256": sha256_file(Path(args.matrix)),
        **pred_meta,
        **label_meta,
        **eval_meta,
        "fit_executed": False,
        "retraining_executed": False,
        "hyperparameter_search_executed": False,
        "candidate_reselection_executed": False,
        "oos_fitted_preprocessor": False,
        "oos_accessed": True,
        "lockbox_accessed": False,
        "live_signal_allowed": False,
        "authoritative_model_output": False,
        "main_merge_allowed": False,
        "next_gate_if_pass": "SEPARATE_OOS_EVIDENCE_ACCEPTANCE_THEN_SEPARATE_LOCKBOX_AUTHORIZATION",
        "next_gate_if_fail": "REGISTER_OOS_FAILURE_NO_PROMOTION_NO_RETUNING",
    }
    (out / "oos_execution_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    required = [
        "oos_execution_manifest.json", "oos_predictions.parquet", "oos_daily_metrics.parquet",
        "oos_quarter_metrics.json", "oos_economic_metrics.json", "oos_gate_result.json",
        "authorization_consumption.json",
    ]
    hashes = {n: sha256_file(out / n) for n in required}
    (out / "artifact_hashes.json").write_text(json.dumps(hashes, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_head": args.execution_head,
        "authorization_consumed": True,
        "prediction_rows": pred_meta["prediction_rows"],
        "valid_20d_rows": label_meta["valid_20d_rows"],
        "mean_daily_ic_20d": eval_meta["mean_daily_ic_20d"],
        "positive_quarters": eval_meta["positive_quarters"],
        "gate_pass": eval_meta["gate_pass"],
        "lockbox_accessed": False,
        "fit_executed": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
