#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def qlist(paths: list[Path]) -> str:
    return "[" + ",".join(q(str(p)) for p in paths) + "]"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--g3-root", required=True)
    ap.add_argument("--g5-chain", required=True)
    ap.add_argument("--g2-intervals", required=True)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--prereg-v12", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import duckdb

    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    cb = contract["fingerprint_basis"]
    prereg = json.loads(Path(args.prereg_v12).read_text(encoding="utf-8"))
    if contract["fingerprint"] != "6ac17734a3a53cfa8dd80deeea020f9acdffa0e4552546e0855056c4b099caf8":
        raise ValueError("unexpected development label contract fingerprint")
    if prereg["fingerprint"] != cb["effective_preregistration"]["fingerprint"]:
        raise ValueError("effective preregistration fingerprint mismatch")

    matrix = Path(args.matrix)
    g3_root = Path(args.g3_root)
    g5 = Path(args.g5_chain)
    g2 = Path(args.g2_intervals)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # Physical source guard: only G3 market files whose filename year is 2015..2022
    # are ever handed to DuckDB. Files from 2023+ remain invisible to the builder.
    market_files: list[Path] = []
    rx = re.compile(r"(?:sse|szse)_(20\d\d)(?:_shard\d+)?\.csv\.gz$")
    for p in g3_root.rglob("*.csv.gz"):
        m = rx.search(p.name.lower())
        if not m:
            continue
        year = int(m.group(1))
        if 2015 <= year <= 2022:
            market_files.append(p)
    market_files = sorted(market_files)
    if not market_files:
        raise ValueError("no guarded 2015-2022 G3 market files")
    bad_files = [p for p in market_files if int(rx.search(p.name.lower()).group(1)) >= 2023]
    if bad_files:
        raise ValueError(f"future G3 files entered source list: {bad_files[:3]}")

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='6GB'")
    con.execute("PRAGMA temp_directory='build/duckdb-tmp'")

    con.execute(f"""
      CREATE TEMP TABLE market_raw AS
      SELECT upper(exchange) AS exchange,
             lpad(CAST(code AS VARCHAR), 6, '0') AS code,
             CAST(trade_date AS DATE) AS trade_date,
             CAST(open AS DOUBLE) AS open,
             CAST(close AS DOUBLE) AS close
      FROM read_csv({qlist(market_files)}, header=true, auto_detect=true, union_by_name=true)
      WHERE CAST(trade_date AS DATE) >= DATE '2015-01-01'
        AND CAST(trade_date AS DATE) < DATE '2023-01-03'
    """)
    market_rows, source_min, source_max = con.execute(
        "SELECT count(*), min(trade_date), max(trade_date) FROM market_raw"
    ).fetchone()
    if str(source_max) > "2022-12-30":
        raise ValueError(f"future market row read: {source_max}")

    con.execute(f"""
      CREATE TEMP TABLE g5 AS
      SELECT upper(exchange) AS exchange,
             lpad(CAST(code AS VARCHAR), 6, '0') AS code,
             CAST(ex_date AS DATE) AS ex_date,
             CAST(cumulative_back_adjust_multiplier AS DOUBLE) AS factor
      FROM read_csv({q(str(g5))}, header=true, auto_detect=true, compression='gzip')
      WHERE CAST(ex_date AS DATE) < DATE '2023-01-03'
      ORDER BY exchange, code, ex_date
    """)
    con.execute("""
      CREATE TEMP TABLE market AS
      SELECT m.exchange, m.code, m.trade_date, m.open, m.close,
             coalesce(g.factor, 1.0) AS factor
      FROM (SELECT * FROM market_raw ORDER BY exchange, code, trade_date) m
      ASOF LEFT JOIN g5 g
        ON m.exchange = g.exchange
       AND m.code = g.code
       AND m.trade_date >= g.ex_date
    """)

    con.execute(f"""
      CREATE TEMP TABLE lifecycle AS
      SELECT upper(exchange) AS exchange,
             lpad(CAST(code AS VARCHAR), 6, '0') AS code,
             CAST(listed_from AS DATE) AS listed_from,
             CASE WHEN listed_to_exclusive IS NULL OR trim(CAST(listed_to_exclusive AS VARCHAR))=''
                  THEN NULL ELSE CAST(listed_to_exclusive AS DATE) END AS listed_to_exclusive
      FROM read_csv({q(str(g2))}, header=true, auto_detect=true)
    """)

    con.execute(f"""
      CREATE TEMP TABLE decisions AS
      SELECT CAST(trade_date AS DATE) AS decision_date,
             upper(exchange) AS exchange,
             lpad(CAST(code AS VARCHAR), 6, '0') AS code
      FROM read_parquet({q(str(matrix))})
      WHERE CAST(trade_date AS DATE) BETWEEN DATE '2015-01-05' AND DATE '2022-12-30'
    """)
    decision_rows, unique_keys = con.execute(
        "SELECT count(*), count(DISTINCT (decision_date,exchange,code)) FROM decisions"
    ).fetchone()
    if decision_rows != unique_keys:
        raise ValueError("development decision keys are not unique")

    con.execute("""
      CREATE TEMP TABLE calendar AS
      SELECT trade_date,
             row_number() OVER (ORDER BY trade_date) - 1 AS session_idx
      FROM (SELECT DISTINCT trade_date FROM market_raw)
      ORDER BY trade_date
    """)
    cal_min, cal_max, cal_n = con.execute(
        "SELECT min(trade_date), max(trade_date), count(*) FROM calendar"
    ).fetchone()

    transitions = cb["censoring"]["known_code_transitions"]
    values = ",".join(
        f"({q(t['exchange'])},{q(t['old_code'])},{q(t['new_code'])},DATE {q(t['effective_date'])})"
        for t in transitions
    )
    con.execute(f"""
      CREATE TEMP TABLE code_transitions(exchange,old_code,new_code,effective_date) AS
      SELECT * FROM (VALUES {values})
    """)

    con.execute("""
      CREATE TEMP TABLE schedule AS
      SELECT d.*,
             c.session_idx AS decision_idx,
             e.trade_date AS entry_date,
             x5.trade_date AS exit_date_5d,
             x20.trade_date AS exit_date_20d
      FROM decisions d
      JOIN calendar c ON c.trade_date=d.decision_date
      LEFT JOIN calendar e ON e.session_idx=c.session_idx+1
      LEFT JOIN calendar x5 ON x5.session_idx=c.session_idx+5
      LEFT JOIN calendar x20 ON x20.session_idx=c.session_idx+20
    """)

    con.execute("""
      CREATE TEMP TABLE raw_labels AS
      SELECT s.decision_date, s.exchange, s.code,
             s.entry_date, s.exit_date_5d, s.exit_date_20d,
             ep.open AS entry_open_raw, ep.factor AS entry_factor,
             p5.close AS exit_close_5d_raw, p5.factor AS exit_factor_5d,
             p20.close AS exit_close_20d_raw, p20.factor AS exit_factor_20d,
             lc.listed_to_exclusive,
             ct.effective_date AS code_transition_date,
             CASE
               WHEN s.exit_date_5d IS NULL OR s.decision_date > DATE '2022-12-23' THEN 'PARTITION_BOUNDARY_INCOMPLETE_HORIZON'
               WHEN ct.effective_date IS NOT NULL AND ct.effective_date > s.decision_date AND ct.effective_date <= s.exit_date_5d THEN 'CODE_TRANSITION_HORIZON_CENSOR'
               WHEN lc.listed_to_exclusive IS NOT NULL AND lc.listed_to_exclusive > s.decision_date AND lc.listed_to_exclusive <= s.exit_date_5d THEN 'DELISTING_HORIZON_CENSOR_NO_TERMINAL_IMPUTATION'
               WHEN ep.open IS NULL OR ep.open <= 0 THEN 'MISSING_ENTRY_OPEN'
               WHEN p5.close IS NULL OR p5.close <= 0 THEN 'MISSING_EXIT_CLOSE'
               ELSE 'VALID'
             END AS censor_reason_5d,
             CASE
               WHEN s.exit_date_20d IS NULL OR s.decision_date > DATE '2022-12-02' THEN 'PARTITION_BOUNDARY_INCOMPLETE_HORIZON'
               WHEN ct.effective_date IS NOT NULL AND ct.effective_date > s.decision_date AND ct.effective_date <= s.exit_date_20d THEN 'CODE_TRANSITION_HORIZON_CENSOR'
               WHEN lc.listed_to_exclusive IS NOT NULL AND lc.listed_to_exclusive > s.decision_date AND lc.listed_to_exclusive <= s.exit_date_20d THEN 'DELISTING_HORIZON_CENSOR_NO_TERMINAL_IMPUTATION'
               WHEN ep.open IS NULL OR ep.open <= 0 THEN 'MISSING_ENTRY_OPEN'
               WHEN p20.close IS NULL OR p20.close <= 0 THEN 'MISSING_EXIT_CLOSE'
               ELSE 'VALID'
             END AS censor_reason_20d
      FROM schedule s
      LEFT JOIN market ep ON ep.exchange=s.exchange AND ep.code=s.code AND ep.trade_date=s.entry_date
      LEFT JOIN market p5 ON p5.exchange=s.exchange AND p5.code=s.code AND p5.trade_date=s.exit_date_5d
      LEFT JOIN market p20 ON p20.exchange=s.exchange AND p20.code=s.code AND p20.trade_date=s.exit_date_20d
      LEFT JOIN lifecycle lc ON lc.exchange=s.exchange AND lc.code=s.code
        AND s.decision_date >= lc.listed_from
        AND (lc.listed_to_exclusive IS NULL OR s.decision_date < lc.listed_to_exclusive)
      LEFT JOIN code_transitions ct ON ct.exchange=s.exchange AND ct.old_code=s.code
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
             avg(stock_total_return_5d) FILTER (WHERE censor_reason_5d='VALID') AS benchmark_return_5d,
             count(stock_total_return_5d) FILTER (WHERE censor_reason_5d='VALID') AS benchmark_n_5d,
             avg(stock_total_return_20d) FILTER (WHERE censor_reason_20d='VALID') AS benchmark_return_20d,
             count(stock_total_return_20d) FILTER (WHERE censor_reason_20d='VALID') AS benchmark_n_20d
      FROM stock_returns GROUP BY decision_date
    """)

    labels = out / "development_labels.parquet"
    con.execute(f"""
      COPY (
        SELECT r.decision_date AS trade_date, r.exchange, r.code,
               r.entry_date, r.exit_date_5d, r.exit_date_20d,
               r.censor_reason_5d='VALID' AS valid_label_5d,
               r.censor_reason_20d='VALID' AS valid_label_20d,
               r.censor_reason_5d, r.censor_reason_20d,
               r.code_transition_date IS NOT NULL AS known_code_transition_security,
               r.listed_to_exclusive IS NOT NULL AS finite_lifecycle_interval,
               r.stock_total_return_5d,
               b.benchmark_return_5d,
               CASE WHEN r.censor_reason_5d='VALID' THEN r.stock_total_return_5d-b.benchmark_return_5d END AS excess_return_5d,
               b.benchmark_n_5d,
               r.stock_total_return_20d,
               b.benchmark_return_20d,
               CASE WHEN r.censor_reason_20d='VALID' THEN r.stock_total_return_20d-b.benchmark_return_20d END AS excess_return_20d,
               b.benchmark_n_20d
        FROM stock_returns r JOIN benchmarks b USING(decision_date)
        ORDER BY trade_date,exchange,code
      ) TO {q(str(labels))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    rows, ukeys, valid5, valid20, max_valid20, max_valid5 = con.execute(f"""
      SELECT count(*), count(DISTINCT (trade_date,exchange,code)),
             count(*) FILTER (WHERE valid_label_5d),
             count(*) FILTER (WHERE valid_label_20d),
             max(trade_date) FILTER (WHERE valid_label_20d),
             max(trade_date) FILTER (WHERE valid_label_5d)
      FROM read_parquet({q(str(labels))})
    """).fetchone()

    censor5 = dict(con.execute(f"SELECT censor_reason_5d,count(*) FROM read_parquet({q(str(labels))}) GROUP BY 1 ORDER BY 1").fetchall())
    censor20 = dict(con.execute(f"SELECT censor_reason_20d,count(*) FROM read_parquet({q(str(labels))}) GROUP BY 1 ORDER BY 1").fetchall())
    censor_report = {
        "schema_version": 1,
        "rows": rows,
        "valid_5d": valid5,
        "valid_20d": valid20,
        "reasons_5d": censor5,
        "reasons_20d": censor20,
        "no_terminal_value_imputation": True,
        "no_forward_fill": True,
    }
    censor_path = out / "development_label_censoring.json"
    censor_path.write_text(json.dumps(censor_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Freeze six contiguous decision-session blocks without reading any label values.
    dates = [str(r[0]) for r in con.execute("SELECT trade_date FROM calendar WHERE trade_date BETWEEN DATE '2015-01-05' AND DATE '2022-12-02' ORDER BY trade_date").fetchall()]
    n = len(dates)
    base, rem = divmod(n, 6)
    sizes = [base + (1 if i < rem else 0) for i in range(6)]
    blocks = []
    pos = 0
    for i, size in enumerate(sizes):
        part = dates[pos:pos+size]
        blocks.append({"block_id": i, "start": part[0], "end": part[-1], "session_count": len(part), "start_index": pos, "end_index": pos+size-1})
        pos += size
    splits = []
    for k in range(1, 6):
        test = blocks[k]
        test_start_idx = test["start_index"]
        train_end_idx = test_start_idx - 21
        if train_end_idx < 0:
            raise ValueError("causal split has no training history after purge")
        embargo_start_idx = test["end_index"] + 1
        embargo_end_idx = min(n - 1, test["end_index"] + 20)
        splits.append({
            "split_id": k,
            "train_start": dates[0],
            "train_end": dates[train_end_idx],
            "train_blocks_nominal": list(range(k)),
            "purged_pre_test_start": dates[train_end_idx+1],
            "purged_pre_test_end": dates[test_start_idx-1],
            "test_block": k,
            "test_start": test["start"],
            "test_end": test["end"],
            "post_test_embargo_start": dates[embargo_start_idx] if embargo_start_idx < n else None,
            "post_test_embargo_end": dates[embargo_end_idx] if embargo_start_idx < n else None,
            "future_train_to_past_test": False,
        })
    split_seal = {
        "schema_version": 1,
        "method": cb["split_seal"]["method"],
        "label_value_blind": True,
        "calendar_start": dates[0],
        "calendar_end": dates[-1],
        "calendar_sessions": n,
        "block_sizes": sizes,
        "blocks": blocks,
        "splits": splits,
        "purge_sessions_before_test": 20,
        "post_test_embargo_sessions": 20,
        "future_train_to_past_test_forbidden": True,
        "model_fit_allowed": False,
    }
    split_path = out / "development_split_seal.json"
    split_path.write_text(json.dumps(split_seal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    materialization = {
        "gate": "STAGE4_ALPHA_V1_DEVELOPMENT_LABEL_MATERIALIZATION",
        "pass": all([
            rows == decision_rows == ukeys,
            str(source_max) <= "2022-12-30",
            str(max_valid20) <= "2022-12-02",
            str(max_valid5) <= "2022-12-23",
            len(blocks) == 6,
            len(splits) == 5,
            all(s["train_end"] < s["test_start"] and not s["future_train_to_past_test"] for s in splits),
        ]),
        "contract_fingerprint": contract["fingerprint"],
        "effective_preregistration_fingerprint": prereg["fingerprint"],
        "market_source_file_count": len(market_files),
        "market_source_rows": market_rows,
        "market_source_min_date": str(source_min),
        "market_source_max_date": str(source_max),
        "market_calendar_sessions": cal_n,
        "decision_rows": decision_rows,
        "label_rows": rows,
        "unique_label_keys": ukeys,
        "valid_5d_rows": valid5,
        "valid_20d_rows": valid20,
        "latest_valid_5d_decision": str(max_valid5),
        "latest_valid_20d_decision": str(max_valid20),
        "labels_sha256": sha256_file(labels),
        "censoring_sha256": sha256_file(censor_path),
        "split_seal_sha256": sha256_file(split_path),
        "feature_matrix_immutable": True,
        "oos_labels_materialized": False,
        "lockbox_labels_materialized": False,
        "model_fit_allowed": False,
        "live_signal_allowed": False,
    }
    audit_path = out / "materialization_audit.json"
    audit_path.write_text(json.dumps(materialization, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(materialization, ensure_ascii=False, indent=2))
    return 0 if materialization["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
