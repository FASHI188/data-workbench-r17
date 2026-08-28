#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_file_list(paths: list[Path]) -> str:
    return "[" + ",".join(q(str(p)) for p in paths) + "]"


def one(con, sql: str):
    return con.execute(sql).fetchone()[0]


def row(con, sql: str) -> dict[str, Any]:
    cur = con.execute(sql)
    cols = [x[0] for x in cur.description]
    values = cur.fetchone()
    return dict(zip(cols, values))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True)
    ap.add_argument("--oof-root", required=True)
    ap.add_argument("--g3-root", required=True)
    ap.add_argument("--g4-root", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import duckdb

    contract_path = Path(args.contract)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    basis = contract["fingerprint_basis"]
    if canonical_hash(basis) != contract["fingerprint"]:
        raise ValueError("boundary contract fingerprint mismatch")
    if contract["status"] != "BOUNDARY_COMPILER_DEVELOPMENT_ONLY_NON_EVALUATION":
        raise ValueError("unexpected boundary contract status")

    scope = basis["scope"]
    required_true = [
        "post_development_rows_in_output_forbidden",
        "oos_prediction_forbidden",
        "oos_label_access_forbidden",
        "model_load_forbidden",
        "fit_retrain_tune_reselect_forbidden",
        "final_lockbox_evaluation_forbidden",
        "business_metrics_forbidden",
    ]
    if any(scope.get(k) is not True for k in required_true):
        raise ValueError("boundary compiler permissions are not fully closed")

    start = scope["development_start"]
    end = scope["development_end"]
    out = Path(args.out)
    work = Path(args.work_dir)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    oof_hits = sorted(Path(args.oof_root).rglob("oof_predictions.parquet"))
    if len(oof_hits) != 1:
        raise ValueError(f"expected exactly one frozen C007 OOF file, got {oof_hits}")
    source_oof = oof_hits[0]
    expected_oof_sha = basis["inputs"]["c007_oof"]["oof_file_sha256"]
    if sha256_file(source_oof) != expected_oof_sha:
        raise ValueError("frozen C007 OOF SHA mismatch")

    # G3 is physically year-partitioned upstream. Hand DuckDB only 2015-2022 files.
    year_re = re.compile(r"(?:2015|2016|2017|2018|2019|2020|2021|2022)")
    g3_all = sorted(Path(args.g3_root).rglob("*.csv.gz"))
    g3_files = [p for p in g3_all if year_re.search(p.name)]
    if not g3_files:
        raise ValueError("no 2015-2022 G3 files found")
    if any(re.search(r"202[3-9]|203\d", p.name) for p in g3_files):
        raise ValueError("post-development G3 file selected")

    # G4 is sharded by identity, not year, so this trusted boundary compiler must
    # read the frozen shards once and emit a physically date-bounded derivative.
    g4_files = sorted(Path(args.g4_root).rglob("g4_state_shard*.csv.gz"))
    if len(g4_files) != 16:
        raise ValueError(f"expected 16 frozen G4 state shards, got {len(g4_files)}")

    g3_cols = """{
      'exchange':'VARCHAR','code':'VARCHAR','trade_date':'DATE','open':'DOUBLE','high':'DOUBLE','low':'DOUBLE',
      'close':'DOUBLE','volume_shares':'DOUBLE','amount_cny':'DOUBLE'
    }"""
    g4_cols = """{
      'exchange':'VARCHAR','code':'VARCHAR','trade_date':'DATE','tradable':'INTEGER','risk_warning':'INTEGER',
      'preclose':'DOUBLE','pct_chg':'DOUBLE','limit_rule':'VARCHAR','limit_up_rate':'DOUBLE','limit_down_rate':'DOUBLE','evidence':'VARCHAR'
    }"""

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='7GB'")
    duck_tmp = work / "duckdb-tmp"
    duck_tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"PRAGMA temp_directory={q(str(duck_tmp))}")

    g3_list = sql_file_list(g3_files)
    g4_list = sql_file_list(g4_files)
    g3_out = out / basis["outputs"]["g3"]
    g4_out = out / basis["outputs"]["g4"]
    oof_out = out / basis["outputs"]["c007_oof"]

    con.execute(f"""
      COPY (
        SELECT upper(exchange) AS exchange, lpad(CAST(code AS VARCHAR),6,'0') AS code,
               trade_date, open, high, low, close, volume_shares, amount_cny
        FROM read_csv({g3_list}, header=true, columns={g3_cols}, compression='gzip', union_by_name=true)
        WHERE trade_date BETWEEN DATE {q(start)} AND DATE {q(end)}
        ORDER BY trade_date, exchange, code
      ) TO {q(str(g3_out))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    con.execute(f"""
      COPY (
        SELECT upper(exchange) AS exchange, lpad(CAST(code AS VARCHAR),6,'0') AS code,
               trade_date, tradable, risk_warning, preclose, pct_chg,
               limit_rule, limit_up_rate, limit_down_rate
        FROM read_csv({g4_list}, header=true, columns={g4_cols}, compression='gzip', union_by_name=true)
        WHERE trade_date BETWEEN DATE {q(start)} AND DATE {q(end)}
        ORDER BY trade_date, exchange, code
      ) TO {q(str(g4_out))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    shutil.copyfile(source_oof, oof_out)

    g3_stats = row(con, f"""
      SELECT count(*)::BIGINT AS rows,
             count(DISTINCT (trade_date,exchange,code))::BIGINT AS unique_keys,
             min(trade_date) AS date_min, max(trade_date) AS date_max
      FROM read_parquet({q(str(g3_out))})
    """)
    g4_stats = row(con, f"""
      SELECT count(*)::BIGINT AS rows,
             count(DISTINCT (trade_date,exchange,code))::BIGINT AS unique_keys,
             min(trade_date) AS date_min, max(trade_date) AS date_max
      FROM read_parquet({q(str(g4_out))})
    """)
    oof_stats = row(con, f"""
      SELECT count(*)::BIGINT AS rows,
             count(DISTINCT trade_date)::BIGINT AS decision_days,
             count(DISTINCT split_id)::BIGINT AS split_count,
             min(trade_date) AS date_min, max(trade_date) AS date_max,
             sum(CASE WHEN prediction IS NULL OR NOT isfinite(prediction) THEN 1 ELSE 0 END)::BIGINT AS invalid_prediction_rows
      FROM read_parquet({q(str(oof_out))})
    """)

    for name, stats in [("g3", g3_stats), ("g4", g4_stats), ("c007_oof", oof_stats)]:
        if str(stats["date_min"]) < start or str(stats["date_max"]) > end:
            raise ValueError(f"{name} escaped physical development boundary: {stats}")
    if int(g3_stats["rows"]) != int(g3_stats["unique_keys"]):
        raise ValueError("development G3 keys are not unique")
    if int(g4_stats["rows"]) != int(g4_stats["unique_keys"]):
        raise ValueError("development G4 keys are not unique")

    oof_expected = basis["inputs"]["c007_oof"]
    if int(oof_stats["rows"]) != int(oof_expected["expected_rows"]):
        raise ValueError("C007 OOF row count drift")
    if int(oof_stats["decision_days"]) != int(oof_expected["expected_decision_days"]):
        raise ValueError("C007 OOF decision-day count drift")
    if int(oof_stats["split_count"]) != int(oof_expected["expected_split_count"]):
        raise ValueError("C007 OOF split count drift")
    if int(oof_stats["invalid_prediction_rows"]) != 0:
        raise ValueError("C007 OOF contains invalid predictions")
    if sha256_file(oof_out) != expected_oof_sha:
        raise ValueError("copied C007 OOF is not byte-identical")

    universe_rows = int(one(con, f"SELECT count(*) FROM read_parquet({q(str(g3_out))}) WHERE close > 0 AND close < 70"))
    expected_universe_rows = int(basis["population_invariants"]["expected_development_universe_rows"])
    if universe_rows != expected_universe_rows:
        raise ValueError(f"development universe row mismatch expected={expected_universe_rows} actual={universe_rows}")

    # Structural downstream-readiness proof only: every frozen OOF decision and T+1
    # entry must resolve inside the physically bounded package. No return metric is computed.
    con.execute(f"""
      CREATE TEMP TABLE calendar_map AS
      WITH d AS (SELECT DISTINCT trade_date FROM read_parquet({q(str(g3_out))}))
      SELECT trade_date, lead(trade_date) OVER (ORDER BY trade_date) AS next_trade_date FROM d
    """)
    structural = row(con, f"""
      WITH o AS (
        SELECT trade_date, upper(exchange) AS exchange, lpad(CAST(code AS VARCHAR),6,'0') AS code
        FROM read_parquet({q(str(oof_out))})
      ), j AS (
        SELECT o.trade_date, cm.next_trade_date,
               d.close AS decision_close, gd.tradable AS decision_tradable,
               e.open AS entry_open, ge.tradable AS entry_tradable
        FROM o
        LEFT JOIN calendar_map cm ON o.trade_date=cm.trade_date
        LEFT JOIN read_parquet({q(str(g3_out))}) d USING(trade_date,exchange,code)
        LEFT JOIN read_parquet({q(str(g4_out))}) gd USING(trade_date,exchange,code)
        LEFT JOIN read_parquet({q(str(g3_out))}) e ON cm.next_trade_date=e.trade_date AND o.exchange=e.exchange AND o.code=e.code
        LEFT JOIN read_parquet({q(str(g4_out))}) ge ON cm.next_trade_date=ge.trade_date AND o.exchange=ge.exchange AND o.code=ge.code
      )
      SELECT count(*)::BIGINT AS rows,
             sum(next_trade_date IS NULL)::BIGINT AS missing_entry_date,
             sum(decision_close IS NULL)::BIGINT AS missing_decision_g3,
             sum(decision_tradable IS NULL)::BIGINT AS missing_decision_g4,
             sum(entry_open IS NULL)::BIGINT AS missing_entry_g3,
             sum(entry_tradable IS NULL)::BIGINT AS missing_entry_g4,
             max(next_trade_date) AS max_entry_date
      FROM j
    """)
    for key in ["missing_entry_date", "missing_decision_g3", "missing_decision_g4", "missing_entry_g3", "missing_entry_g4"]:
        if int(structural[key]) != 0:
            raise ValueError(f"physical package structural join failed {key}={structural[key]}")
    if str(structural["max_entry_date"]) > end:
        raise ValueError("physical package T+1 entry crossed development boundary")

    data_hashes = {
        basis["outputs"]["g3"]: sha256_file(g3_out),
        basis["outputs"]["g4"]: sha256_file(g4_out),
        basis["outputs"]["c007_oof"]: sha256_file(oof_out),
    }
    manifest = {
        "schema_version": 1,
        "status": "PHYSICALLY_DEVELOPMENT_ONLY",
        "boundary_contract_fingerprint": contract["fingerprint"],
        "integration_base_sha": basis["integration_base_sha"],
        "development_start": start,
        "development_end": end,
        "source_artifacts": basis["inputs"],
        "g3": {**g3_stats, "development_universe_rows": universe_rows},
        "g4": g4_stats,
        "c007_oof": oof_stats,
        "structural_readiness": structural,
        "data_sha256": data_hashes,
        "physical_guards": {
            "all_output_min_dates_gte_development_start": True,
            "all_output_max_dates_lte_development_end": True,
            "post_2022_output_rows": 0,
            "downstream_requires_broad_g3_artifact": False,
            "downstream_requires_broad_g4_artifact": False,
            "oos_prediction_executed": False,
            "oos_label_accessed": False,
            "model_loaded": False,
            "fit_retrain_tune_reselect_executed": False,
            "final_lockbox_evaluation_executed": False,
            "business_metrics_computed": False,
        },
    }
    manifest_path = out / basis["outputs"]["manifest"]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    hashes = {**data_hashes, basis["outputs"]["manifest"]: sha256_file(manifest_path)}
    hashes_path = out / basis["outputs"]["hashes"]
    hashes_path.write_text(json.dumps(hashes, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": manifest["status"],
        "boundary_contract_fingerprint": contract["fingerprint"],
        "development_start": start,
        "development_end": end,
        "g3_rows": int(g3_stats["rows"]),
        "g4_rows": int(g4_stats["rows"]),
        "c007_oof_rows": int(oof_stats["rows"]),
        "development_universe_rows": universe_rows,
        "post_2022_output_rows": 0,
        "structural_readiness": structural,
        "data_sha256": data_hashes,
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
