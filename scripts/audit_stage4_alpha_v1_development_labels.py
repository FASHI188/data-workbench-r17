#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def canonical_fp(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc["fingerprint_basis"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--g3-root", required=True)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--prereg-v12", required=True)
    ap.add_argument("--materialization-audit", required=True)
    ap.add_argument("--split-seal", required=True)
    ap.add_argument("--censoring", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import duckdb

    labels = Path(args.labels)
    matrix = Path(args.matrix)
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    prereg = json.loads(Path(args.prereg_v12).read_text(encoding="utf-8"))
    mat = json.loads(Path(args.materialization_audit).read_text(encoding="utf-8"))
    split = json.loads(Path(args.split_seal).read_text(encoding="utf-8"))
    censor = json.loads(Path(args.censoring).read_text(encoding="utf-8"))
    checks: dict[str, bool] = {}

    checks["contract_fingerprint_exact"] = canonical_fp(contract) == contract["fingerprint"] == "6ac17734a3a53cfa8dd80deeea020f9acdffa0e4552546e0855056c4b099caf8"
    checks["prereg_v1_2_exact"] = prereg["fingerprint"] == contract["fingerprint_basis"]["effective_preregistration"]["fingerprint"] == "b73f9b55efb04fac5416f6fdd39c17780b3f9e46c82d0da6b111547e3d258cf8"
    checks["materialization_self_audit_pass"] = mat["pass"] is True

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='6GB'")
    con.execute("PRAGMA temp_directory='build/duckdb-audit-tmp'")

    allowed = {
        "trade_date","exchange","code","entry_date","exit_date_5d","exit_date_20d",
        "valid_label_5d","valid_label_20d","censor_reason_5d","censor_reason_20d",
        "known_code_transition_security","finite_lifecycle_interval",
        "stock_total_return_5d","benchmark_return_5d","excess_return_5d","benchmark_n_5d",
        "stock_total_return_20d","benchmark_return_20d","excess_return_20d","benchmark_n_20d",
    }
    cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(str(labels))})").fetchall()}
    checks["label_schema_minimal_exact"] = cols == allowed

    stats = con.execute(f"""
      SELECT count(*), count(DISTINCT (trade_date,exchange,code)), min(trade_date), max(trade_date),
             count(*) FILTER (WHERE valid_label_5d),
             count(*) FILTER (WHERE valid_label_20d),
             max(trade_date) FILTER (WHERE valid_label_5d),
             max(trade_date) FILTER (WHERE valid_label_20d),
             count(*) FILTER (WHERE NOT valid_label_5d AND (stock_total_return_5d IS NOT NULL OR excess_return_5d IS NOT NULL)),
             count(*) FILTER (WHERE NOT valid_label_20d AND (stock_total_return_20d IS NOT NULL OR excess_return_20d IS NOT NULL)),
             count(*) FILTER (WHERE valid_label_5d AND (benchmark_n_5d IS NULL OR benchmark_n_5d<=0)),
             count(*) FILTER (WHERE valid_label_20d AND (benchmark_n_20d IS NULL OR benchmark_n_20d<=0))
      FROM read_parquet({q(str(labels))})
    """).fetchone()
    rows, unique_keys, dmin, dmax, valid5, valid20, max5, max20, bad_invalid5, bad_invalid20, bad_bench5, bad_bench20 = stats
    checks["label_population_unique"] = rows == unique_keys == mat["label_rows"]
    checks["development_dates_only"] = str(dmin) == "2015-01-05" and str(dmax) == "2022-12-30"
    checks["horizon_boundaries_exact"] = str(max20) <= "2022-12-02" and str(max5) <= "2022-12-23"
    checks["invalid_labels_are_null"] = bad_invalid5 == 0 and bad_invalid20 == 0
    checks["valid_benchmarks_have_population"] = bad_bench5 == 0 and bad_bench20 == 0

    matrix_count, missing_in_labels, extra_labels = con.execute(f"""
      WITH m AS (
        SELECT CAST(trade_date AS DATE) trade_date, upper(exchange) exchange, lpad(CAST(code AS VARCHAR),6,'0') code
        FROM read_parquet({q(str(matrix))})
        WHERE CAST(trade_date AS DATE) BETWEEN DATE '2015-01-05' AND DATE '2022-12-30'
      ), l AS (SELECT trade_date,exchange,code FROM read_parquet({q(str(labels))}))
      SELECT (SELECT count(*) FROM m),
             (SELECT count(*) FROM m ANTI JOIN l USING(trade_date,exchange,code)),
             (SELECT count(*) FROM l ANTI JOIN m USING(trade_date,exchange,code))
    """).fetchone()
    checks["feature_matrix_key_population_exact"] = matrix_count == rows and missing_in_labels == 0 and extra_labels == 0

    bench5_err, bench20_err, excess5_err, excess20_err = con.execute(f"""
      WITH x AS (SELECT * FROM read_parquet({q(str(labels))})),
      b AS (
        SELECT trade_date,
          avg(stock_total_return_5d) FILTER (WHERE valid_label_5d) exp_b5,
          avg(stock_total_return_20d) FILTER (WHERE valid_label_20d) exp_b20
        FROM x GROUP BY trade_date
      )
      SELECT
        coalesce(max(abs(x.benchmark_return_5d-b.exp_b5)) FILTER (WHERE x.valid_label_5d),0),
        coalesce(max(abs(x.benchmark_return_20d-b.exp_b20)) FILTER (WHERE x.valid_label_20d),0),
        coalesce(max(abs(x.excess_return_5d-(x.stock_total_return_5d-x.benchmark_return_5d))) FILTER (WHERE x.valid_label_5d),0),
        coalesce(max(abs(x.excess_return_20d-(x.stock_total_return_20d-x.benchmark_return_20d))) FILTER (WHERE x.valid_label_20d),0)
      FROM x JOIN b USING(trade_date)
    """).fetchone()
    checks["benchmark_recomputed_exact"] = bench5_err < 1e-12 and bench20_err < 1e-12
    checks["excess_return_recomputed_exact"] = excess5_err < 1e-12 and excess20_err < 1e-12

    rx = re.compile(r"(?:sse|szse)_(20\d\d)(?:_shard\d+)?\.csv\.gz$")
    source_years = []
    for p in Path(args.g3_root).rglob("*.csv.gz"):
        m = rx.search(p.name.lower())
        if m:
            source_years.append(int(m.group(1)))
    checks["physical_market_source_guard"] = bool(source_years) and min(source_years) <= 2015 and mat["market_source_max_date"] <= "2022-12-30"
    checks["no_future_market_rows_read"] = mat["market_source_max_date"] < "2023-01-03"

    blocks = split["blocks"]
    splits = split["splits"]
    checks["split_seal_structure_exact"] = (
        split["method"] == "ANCHORED_PURGED_EXPANDING_WINDOW_BLOCK_CV"
        and split["label_value_blind"] is True
        and len(blocks) == 6 and len(splits) == 5
        and split["purge_sessions_before_test"] == 20
        and split["post_test_embargo_sessions"] == 20
        and split["future_train_to_past_test_forbidden"] is True
    )
    checks["blocks_contiguous_chronological"] = all(
        blocks[i]["block_id"] == i and blocks[i]["end"] < blocks[i+1]["start"] for i in range(5)
    )
    checks["splits_strictly_causal"] = all(
        s["split_id"] == k and s["test_block"] == k and s["train_end"] < s["test_start"] and s["future_train_to_past_test"] is False
        for k, s in enumerate(splits, start=1)
    )
    checks["primary_split_calendar_ends_at_labelable_boundary"] = split["calendar_end"] == "2022-12-02"

    checks["censoring_report_population_exact"] = censor["rows"] == rows and censor["valid_5d"] == valid5 and censor["valid_20d"] == valid20
    checks["no_imputation_policy"] = censor["no_terminal_value_imputation"] is True and censor["no_forward_fill"] is True
    checks["permissions_remain_closed"] = (
        contract["fingerprint_basis"]["permissions"]["model_fit_allowed"] is False
        and contract["fingerprint_basis"]["permissions"]["oos_label_access_allowed"] is False
        and contract["fingerprint_basis"]["permissions"]["lockbox_label_access_allowed"] is False
        and contract["fingerprint_basis"]["permissions"]["live_signal_allowed"] is False
        and contract["fingerprint_basis"]["permissions"]["main_merge_allowed"] is False
    )

    failed = [k for k,v in checks.items() if not v]
    report = {
        "gate": "STAGE4_ALPHA_V1_DEVELOPMENT_LABELS_INDEPENDENT_AUDIT",
        "pass": not failed,
        "checks": checks,
        "failed_checks": failed,
        "label_rows": rows,
        "valid_5d_rows": valid5,
        "valid_20d_rows": valid20,
        "benchmark_5d_max_abs_error": bench5_err,
        "benchmark_20d_max_abs_error": bench20_err,
        "excess_5d_max_abs_error": excess5_err,
        "excess_20d_max_abs_error": excess20_err,
        "labels_sha256": sha256_file(labels),
        "split_seal_sha256": sha256_file(Path(args.split_seal)),
        "censoring_sha256": sha256_file(Path(args.censoring)),
        "model_fit_allowed": False,
        "oos_label_access_allowed": False,
        "lockbox_label_access_allowed": False,
        "live_signal_allowed": False,
        "next_gate": "SEPARATE_ALPHA_V1_DEVELOPMENT_TRAINING_EXECUTION_AUTHORIZATION"
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
