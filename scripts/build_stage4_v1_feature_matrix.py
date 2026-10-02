#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

FIN_CONCEPTS = {
    "TOTAL_ASSETS": "fin_total_assets_cny",
    "TOTAL_LIABILITIES": "fin_total_liabilities_cny",
    "TOTAL_EQUITY": "fin_total_equity_cny",
    "EQUITY_ATTRIBUTABLE_TO_PARENT": "fin_parent_equity_cny",
    "OPERATING_REVENUE": "fin_operating_revenue_cny",
    "OPERATING_COST": "fin_operating_cost_cny",
    "NET_PROFIT_ATTRIBUTABLE_TO_PARENT": "fin_parent_net_profit_cny",
    "NET_PROFIT_EX_NONRECURRING_ATTRIBUTABLE_TO_PARENT": "fin_parent_net_profit_ex_nonrecurring_cny",
    "NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES": "fin_operating_cash_flow_cny",
}

MARKET_FEATURES = [
    "regime_state", "advance_ratio", "net_breadth", "ew_return_5d", "ew_return_20d",
    "net_breadth_5d_mean", "ew_return_vol_20d", "cross_sectional_return_std_1d",
    "amount_ratio_5d_20d"
]

TECH_FEATURES = [
    "close_unadjusted", "total_return_1d", "total_return_5d", "total_return_20d",
    "realized_volatility_20d", "amount_ratio_5d_20d_stock", "volume_ratio_5d_20d_stock",
    "relative_strength_vs_market_20d"
]


def q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def file_list_sql(paths: list[Path]) -> str:
    if not paths:
        raise ValueError("empty input file list")
    return "[" + ",".join(q(str(p)) for p in paths) + "]"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--historical-ohlcv-root", required=True)
    ap.add_argument("--forward-ohlcv-root", required=True)
    ap.add_argument("--historical-g5", required=True)
    ap.add_argument("--forward-g5", required=True)
    ap.add_argument("--historical-financial", required=True)
    ap.add_argument("--forward-financial-root", required=True)
    ap.add_argument("--earnings-surprise", required=True)
    ap.add_argument("--market-regime", required=True)
    ap.add_argument("--feature-set-contract", required=True)
    ap.add_argument("--matrix-contract", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import duckdb

    feature_set = json.loads(Path(args.feature_set_contract).read_text(encoding="utf-8"))
    matrix_contract = json.loads(Path(args.matrix_contract).read_text(encoding="utf-8"))
    if feature_set["feature_set_version"] != "V1.1":
        raise ValueError("matrix materializer requires feature set V1.1")
    if feature_set["feature_set_fingerprint"] != matrix_contract["feature_set_fingerprint"]:
        raise ValueError("matrix contract / feature-set fingerprint mismatch")
    if feature_set["fingerprint_basis"]["permissions"]["alpha_training_allowed"] is not False:
        raise ValueError("feature-set contract unexpectedly authorizes Alpha training")

    hist_ohlcv = sorted(Path(args.historical_ohlcv_root).rglob("*.csv.gz"))
    fwd_ohlcv = sorted(Path(args.forward_ohlcv_root).rglob("*.csv.gz"))
    fwd_fin = sorted(Path(args.forward_financial_root).glob("financial_values_shard*.csv.gz"))
    if len(hist_ohlcv) != matrix_contract["expected_inputs"]["historical_ohlcv_files"]:
        raise ValueError(f"historical OHLCV file count mismatch: {len(hist_ohlcv)}")
    if len(fwd_ohlcv) != matrix_contract["expected_inputs"]["forward_ohlcv_files"]:
        raise ValueError(f"forward OHLCV file count mismatch: {len(fwd_ohlcv)}")
    if len(fwd_fin) != matrix_contract["expected_inputs"]["forward_financial_value_shards"]:
        raise ValueError(f"forward financial shard count mismatch: {len(fwd_fin)}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db = out / "feature_matrix.duckdb"
    con = duckdb.connect(str(db))
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='5GB'")
    con.execute("PRAGMA temp_directory='{}'".format(str(out / "duckdb_tmp").replace("'", "''")))

    con.execute(f"""
      CREATE TABLE ohlcv AS
      SELECT exchange, code, trade_date,
             TRY_CAST(close AS DOUBLE) close_unadjusted,
             TRY_CAST(volume_shares AS DOUBLE) volume_shares,
             TRY_CAST(amount_cny AS DOUBLE) amount_cny
      FROM read_csv({file_list_sql(hist_ohlcv)}, header=true, all_varchar=true, union_by_name=true)
      UNION ALL
      SELECT exchange, code, trade_date,
             TRY_CAST(close AS DOUBLE), TRY_CAST(volume_shares AS DOUBLE), TRY_CAST(amount_cny AS DOUBLE)
      FROM read_csv({file_list_sql(fwd_ohlcv)}, header=true, all_varchar=true, union_by_name=true)
    """)

    con.execute(f"""
      CREATE TABLE adjustment AS
      SELECT exchange, code, ex_date,
             TRY_CAST(cumulative_back_adjust_multiplier AS DOUBLE) cumulative_back_adjust_multiplier
      FROM read_csv({q(args.historical_g5)}, header=true, all_varchar=true)
      UNION ALL
      SELECT exchange, code, ex_date,
             TRY_CAST(cumulative_back_adjust_multiplier AS DOUBLE)
      FROM read_csv({q(args.forward_g5)}, header=true, all_varchar=true)
    """)

    con.execute(f"""
      CREATE TABLE regime AS
      SELECT trade_date, effective_session, regime_state,
             TRY_CAST(advance_ratio AS DOUBLE) advance_ratio,
             TRY_CAST(net_breadth AS DOUBLE) net_breadth,
             TRY_CAST(ew_return_5d AS DOUBLE) ew_return_5d,
             TRY_CAST(ew_return_20d AS DOUBLE) ew_return_20d,
             TRY_CAST(net_breadth_5d_mean AS DOUBLE) net_breadth_5d_mean,
             TRY_CAST(ew_return_vol_20d AS DOUBLE) ew_return_vol_20d,
             TRY_CAST(cross_sectional_return_std_1d AS DOUBLE) cross_sectional_return_std_1d,
             TRY_CAST(amount_ratio_5d_20d AS DOUBLE) amount_ratio_5d_20d
      FROM read_csv({q(args.market_regime)}, header=true, all_varchar=true)
    """)
    con.execute("CREATE TABLE sessions AS SELECT effective_session, row_number() OVER (ORDER BY effective_session) session_idx FROM (SELECT DISTINCT effective_session FROM regime)")

    con.execute("""
      CREATE TABLE price_adjusted AS
      SELECT o.*, COALESCE(a.cumulative_back_adjust_multiplier, 1.0) adjustment_multiplier,
             o.close_unadjusted * COALESCE(a.cumulative_back_adjust_multiplier, 1.0) adjusted_close
      FROM ohlcv o
      ASOF LEFT JOIN adjustment a
        ON o.exchange = a.exchange AND o.code = a.code AND o.trade_date >= a.ex_date
    """)
    con.execute("""
      CREATE TABLE technical_step1 AS
      SELECT p.*,
             lag(adjusted_close,1) OVER w adj_lag_1,
             lag(adjusted_close,5) OVER w adj_lag_5,
             lag(adjusted_close,20) OVER w adj_lag_20,
             avg(amount_cny) OVER (PARTITION BY exchange,code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) amount_avg_5,
             avg(amount_cny) OVER (PARTITION BY exchange,code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) amount_avg_20,
             count(amount_cny) OVER (PARTITION BY exchange,code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) amount_count_20,
             avg(volume_shares) OVER (PARTITION BY exchange,code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) volume_avg_5,
             avg(volume_shares) OVER (PARTITION BY exchange,code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) volume_avg_20,
             count(volume_shares) OVER (PARTITION BY exchange,code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) volume_count_20
      FROM price_adjusted p
      WINDOW w AS (PARTITION BY exchange,code ORDER BY trade_date)
    """)
    con.execute("""
      CREATE TABLE technical_step2 AS
      SELECT *,
             CASE WHEN adj_lag_1>0 THEN adjusted_close/adj_lag_1-1 END total_return_1d,
             CASE WHEN adj_lag_5>0 THEN adjusted_close/adj_lag_5-1 END total_return_5d,
             CASE WHEN adj_lag_20>0 THEN adjusted_close/adj_lag_20-1 END total_return_20d,
             CASE WHEN amount_count_20=20 AND amount_avg_20>0 THEN amount_avg_5/amount_avg_20 END amount_ratio_5d_20d_stock,
             CASE WHEN volume_count_20=20 AND volume_avg_20>0 THEN volume_avg_5/volume_avg_20 END volume_ratio_5d_20d_stock
      FROM technical_step1
    """)
    con.execute("""
      CREATE TABLE technical AS
      SELECT t.*, CASE WHEN count(total_return_1d) OVER (PARTITION BY exchange,code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)=20
                       THEN stddev_pop(total_return_1d) OVER (PARTITION BY exchange,code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) END realized_volatility_20d
      FROM technical_step2 t
    """)

    fin_files = [Path(args.historical_financial)] + fwd_fin
    fin_pivots = ",\n".join(
        f"max(CASE WHEN concept={q(concept)} THEN TRY_CAST(normalized_cny_value AS DOUBLE) END) AS {column}"
        for concept, column in FIN_CONCEPTS.items()
    )
    con.execute(f"""
      CREATE TABLE financial_report AS
      SELECT exchange, effective_code code, economic_date, effective_session, announcement_id,
             max(TRY_CAST(revision_sequence AS BIGINT)) revision_sequence,
             max(report_family) report_family,
             {fin_pivots}
      FROM read_csv({file_list_sql(fin_files)}, header=true, all_varchar=true, union_by_name=true)
      GROUP BY exchange,effective_code,economic_date,effective_session,announcement_id
    """)
    con.execute("""
      CREATE TABLE financial_report_dedup AS
      SELECT * EXCLUDE(rn) FROM (
        SELECT *, row_number() OVER (
          PARTITION BY exchange,code,economic_date,effective_session
          ORDER BY revision_sequence DESC NULLS LAST, announcement_id DESC
        ) rn FROM financial_report
      ) WHERE rn=1
    """)
    con.execute("""
      CREATE TABLE financial_state_candidate AS
      SELECT *, max(economic_date) OVER (
        PARTITION BY exchange,code ORDER BY effective_session,economic_date,revision_sequence,announcement_id
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
      ) latest_economic_date
      FROM financial_report_dedup
    """)
    con.execute("""
      CREATE TABLE financial_state AS
      SELECT * EXCLUDE(latest_economic_date,rn) FROM (
        SELECT *, row_number() OVER (
          PARTITION BY exchange,code,effective_session
          ORDER BY economic_date DESC,revision_sequence DESC NULLS LAST,announcement_id DESC
        ) rn
        FROM financial_state_candidate WHERE economic_date=latest_economic_date
      ) WHERE rn=1
    """)

    con.execute(f"""
      CREATE TABLE surprise AS
      SELECT exchange,effective_code code,economic_date,
             substr(actual_available_at,1,10) surprise_effective_session,
             TRY_CAST(surprise_cny AS DOUBLE) official_guidance_surprise,
             surprise_direction,
             forecast_announcement_id,actual_announcement_id
      FROM read_csv({q(args.earnings_surprise)}, header=true, all_varchar=true)
      WHERE expectation_is_strictly_prior='1' AND analyst_consensus_used='0'
      QUALIFY row_number() OVER (
        PARTITION BY exchange,effective_code,substr(actual_available_at,1,10)
        ORDER BY economic_date DESC,actual_announcement_id DESC
      )=1
    """)

    con.execute("""
      CREATE TABLE candidate_base AS
      SELECT t.exchange,t.code,t.trade_date,r.effective_session,s.session_idx,
             t.close_unadjusted,t.total_return_1d,t.total_return_5d,t.total_return_20d,
             t.realized_volatility_20d,t.amount_ratio_5d_20d_stock,t.volume_ratio_5d_20d_stock,
             CASE WHEN t.total_return_20d IS NOT NULL AND r.ew_return_20d IS NOT NULL THEN t.total_return_20d-r.ew_return_20d END relative_strength_vs_market_20d,
             r.regime_state,r.advance_ratio,r.net_breadth,r.ew_return_5d,r.ew_return_20d,
             r.net_breadth_5d_mean,r.ew_return_vol_20d,r.cross_sectional_return_std_1d,r.amount_ratio_5d_20d,
             t.adjustment_multiplier
      FROM technical t
      JOIN regime r ON t.trade_date=r.trade_date
      JOIN sessions s ON r.effective_session=s.effective_session
      WHERE t.close_unadjusted < 70.0 AND t.close_unadjusted > 0
    """)

    fin_columns = ",".join(f"f.{col}" for col in FIN_CONCEPTS.values())
    con.execute(f"""
      CREATE TABLE candidate_fin AS
      SELECT c.*, f.effective_session financial_source_effective_session,
             f.economic_date financial_economic_date, fs.session_idx financial_source_session_idx,
             {fin_columns}
      FROM candidate_base c
      ASOF LEFT JOIN financial_state f
        ON c.exchange=f.exchange AND c.code=f.code AND c.effective_session>=f.effective_session
      LEFT JOIN sessions fs ON f.effective_session=fs.effective_session
    """)
    con.execute("""
      CREATE TABLE candidate_full AS
      SELECT c.*, su.surprise_effective_session, ss.session_idx surprise_source_session_idx,
             su.economic_date surprise_economic_date, su.official_guidance_surprise,
             su.surprise_direction,
             CASE WHEN su.official_guidance_surprise IS NULL THEN 1 ELSE 0 END official_guidance_surprise_missing,
             CASE WHEN c.financial_source_session_idx IS NULL THEN NULL ELSE c.session_idx-c.financial_source_session_idx END financial_report_age_sessions,
             CASE WHEN ss.session_idx IS NULL THEN NULL ELSE c.session_idx-ss.session_idx END guidance_age_sessions
      FROM candidate_fin c
      ASOF LEFT JOIN surprise su
        ON c.exchange=su.exchange AND c.code=su.code AND c.effective_session>=su.surprise_effective_session
      LEFT JOIN sessions ss ON su.surprise_effective_session=ss.effective_session
    """)

    fin_missing = ",\n".join(
        f"CASE WHEN {column} IS NULL THEN 1 ELSE 0 END AS {column}_missing"
        for column in FIN_CONCEPTS.values()
    )
    matrix = out / "stage4_v1_feature_matrix.parquet"
    con.execute(f"""
      COPY (
        SELECT exchange,code,trade_date,effective_session,
               close_unadjusted,total_return_1d,total_return_5d,total_return_20d,
               realized_volatility_20d,amount_ratio_5d_20d_stock,volume_ratio_5d_20d_stock,
               relative_strength_vs_market_20d,
               regime_state,advance_ratio,net_breadth,ew_return_5d,ew_return_20d,net_breadth_5d_mean,
               ew_return_vol_20d,cross_sectional_return_std_1d,amount_ratio_5d_20d,
               {','.join(FIN_CONCEPTS.values())},
               {fin_missing},
               financial_report_age_sessions,
               official_guidance_surprise,official_guidance_surprise_missing,guidance_age_sessions,
               financial_source_effective_session,financial_economic_date,
               surprise_effective_session,surprise_economic_date,adjustment_multiplier
        FROM candidate_full ORDER BY effective_session,exchange,code
      ) TO {q(str(matrix))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    feature_columns = TECH_FEATURES + MARKET_FEATURES + list(FIN_CONCEPTS.values()) + [
        f"{c}_missing" for c in FIN_CONCEPTS.values()
    ] + ["financial_report_age_sessions","official_guidance_surprise","official_guidance_surprise_missing","guidance_age_sessions"]
    coverage_rows = []
    total_rows = con.execute(f"SELECT count(*) FROM read_parquet({q(str(matrix))})").fetchone()[0]
    for column in feature_columns:
        nonnull, distinct_count = con.execute(
            f"SELECT count({column}), count(DISTINCT {column}) FROM read_parquet({q(str(matrix))})"
        ).fetchone()
        coverage_rows.append({
            "feature": column,
            "rows": total_rows,
            "nonnull_rows": nonnull,
            "missing_rows": total_rows - nonnull,
            "coverage_ratio": nonnull / total_rows if total_rows else 0.0,
            "distinct_nonnull": distinct_count,
        })
    coverage_path = out / "feature_coverage.json"
    coverage_path.write_text(json.dumps(coverage_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    stats = con.execute(f"""
      SELECT count(*) rows,
             count(DISTINCT (effective_session,exchange,code)) unique_keys,
             min(trade_date),max(trade_date),min(effective_session),max(effective_session),
             sum(CASE WHEN close_unadjusted=70.0 THEN 1 ELSE 0 END) exact_70_rows,
             sum(CASE WHEN trade_date>=effective_session THEN 1 ELSE 0 END) bad_next_session_rows,
             sum(CASE WHEN financial_source_effective_session IS NOT NULL AND financial_source_effective_session>effective_session THEN 1 ELSE 0 END) future_financial_rows,
             sum(CASE WHEN surprise_effective_session IS NOT NULL AND surprise_effective_session>effective_session THEN 1 ELSE 0 END) future_surprise_rows,
             sum(CASE WHEN financial_report_age_sessions<0 THEN 1 ELSE 0 END) negative_financial_age_rows,
             sum(CASE WHEN guidance_age_sessions<0 THEN 1 ELSE 0 END) negative_guidance_age_rows
      FROM read_parquet({q(str(matrix))})
    """).fetchone()
    ohlcv_rows = con.execute("SELECT count(*) FROM ohlcv").fetchone()[0]
    ohlcv_dupes = con.execute("SELECT count(*)-count(DISTINCT (exchange,code,trade_date)) FROM ohlcv").fetchone()[0]
    report = {
        "gate": "STAGE4_V1_FEATURE_MATRIX_MATERIALIZATION",
        "pass": True,
        "feature_set_version": feature_set["feature_set_version"],
        "feature_set_fingerprint": feature_set["feature_set_fingerprint"],
        "duckdb_version": duckdb.__version__,
        "ohlcv_rows": ohlcv_rows,
        "expected_ohlcv_rows": matrix_contract["expected_inputs"]["combined_ohlcv_rows"],
        "ohlcv_duplicate_keys": ohlcv_dupes,
        "matrix_rows": stats[0], "unique_matrix_keys": stats[1],
        "trade_date_min": stats[2], "trade_date_max": stats[3],
        "effective_session_min": stats[4], "effective_session_max": stats[5],
        "exact_70_candidate_rows": stats[6], "bad_next_session_rows": stats[7],
        "future_financial_rows": stats[8], "future_surprise_rows": stats[9],
        "negative_financial_age_rows": stats[10], "negative_guidance_age_rows": stats[11],
        "matrix_sha256": sha256_file(matrix),
        "coverage_sha256": sha256_file(coverage_path),
        "industry_identity_in_matrix": False,
        "general_web_news_in_matrix": False,
        "social_media_in_matrix": False,
        "alpha_training_allowed": False,
        "live_signal_allowed": False,
        "authoritative_model_output": False,
    }
    required_true = [
        ohlcv_rows == matrix_contract["expected_inputs"]["combined_ohlcv_rows"],
        ohlcv_dupes == 0,
        stats[0] == stats[1],
        stats[3] == matrix_contract["expected_outputs"]["trade_date_max"],
        stats[5] == matrix_contract["expected_outputs"]["effective_session_max"],
        stats[6] == 0, stats[7] == 0, stats[8] == 0, stats[9] == 0, stats[10] == 0, stats[11] == 0,
    ]
    report["pass"] = all(required_true)
    audit_path = out / "feature_matrix_build_audit.json"
    audit_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "matrix_id": "STAGE4_V1_FEATURE_MATRIX",
        "matrix_version": "V1.1",
        "status": "MATERIALIZED_PRETRAINING",
        "feature_set_fingerprint": feature_set["feature_set_fingerprint"],
        "matrix_sha256": report["matrix_sha256"],
        "coverage_sha256": report["coverage_sha256"],
        "row_count": stats[0],
        "key": ["effective_session","exchange","code"],
        "decision_time_semantics": "SESSION_T_CLOSE_INFORMATION_ONLY_EFFECTIVE_NEXT_TRADING_SESSION",
        "candidate_universe": "SSE_MAIN_A + SZSE_MAIN_A; raw close strictly < CNY 70 at trade_date T",
        "financial_state_semantics": "latest maximum economic_date report known by effective_session; late revisions to older periods do not replace current report state",
        "financial_missing_semantics": "latest-report missing stays missing; no zero fill and no prior-report concept carry-forward",
        "industry_identity": "EXCLUDED_PENDING_NORMALIZATION_PLUGIN",
        "alpha_training_allowed": False,
        "live_signal_allowed": False,
        "authoritative_model_output": False,
        "next_gate": "FAIL_CLOSED_STAGE4_V1_FEATURE_MATRIX_PIT_COVERAGE_MISSINGNESS_NON_LEAKAGE_AUDIT"
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    con.close()
    db.unlink(missing_ok=True)
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
