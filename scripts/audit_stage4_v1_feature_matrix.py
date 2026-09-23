#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

FIN = [
    "fin_total_assets_cny","fin_total_liabilities_cny","fin_total_equity_cny","fin_parent_equity_cny",
    "fin_operating_revenue_cny","fin_operating_cost_cny","fin_parent_net_profit_cny",
    "fin_parent_net_profit_ex_nonrecurring_cny","fin_operating_cash_flow_cny"
]
MARKET_NUMERIC = [
    "advance_ratio","net_breadth","ew_return_5d","ew_return_20d","net_breadth_5d_mean",
    "ew_return_vol_20d","cross_sectional_return_std_1d","amount_ratio_5d_20d"
]
EXPECTED_COLUMNS = {
    "exchange","code","trade_date","effective_session","close_unadjusted","total_return_1d","total_return_5d",
    "total_return_20d","realized_volatility_20d","amount_ratio_5d_20d_stock","volume_ratio_5d_20d_stock",
    "relative_strength_vs_market_20d","regime_state","advance_ratio","net_breadth","ew_return_5d","ew_return_20d",
    "net_breadth_5d_mean","ew_return_vol_20d","cross_sectional_return_std_1d","amount_ratio_5d_20d",
    "financial_report_age_sessions","official_guidance_surprise","official_guidance_surprise_missing","guidance_age_sessions",
    "financial_source_effective_session","financial_economic_date","surprise_effective_session","surprise_economic_date",
    "adjustment_multiplier",
} | set(FIN) | {f"{c}_missing" for c in FIN}


def q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def file_list(paths: list[Path]) -> str:
    return "[" + ",".join(q(str(p)) for p in paths) + "]"


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--matrix",required=True)
    ap.add_argument("--coverage",required=True)
    ap.add_argument("--build-audit",required=True)
    ap.add_argument("--manifest",required=True)
    ap.add_argument("--contract",required=True)
    ap.add_argument("--feature-set-contract",required=True)
    ap.add_argument("--historical-ohlcv-root",required=True)
    ap.add_argument("--forward-ohlcv-root",required=True)
    ap.add_argument("--market-regime",required=True)
    ap.add_argument("--trading-universe-audit",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    import duckdb
    matrix=Path(args.matrix)
    coverage=json.loads(Path(args.coverage).read_text(encoding="utf-8"))
    build=json.loads(Path(args.build_audit).read_text(encoding="utf-8"))
    manifest=json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    contract=json.loads(Path(args.contract).read_text(encoding="utf-8"))
    feature_set=json.loads(Path(args.feature_set_contract).read_text(encoding="utf-8"))
    universe=json.loads(Path(args.trading_universe_audit).read_text(encoding="utf-8"))
    hist=sorted(Path(args.historical_ohlcv_root).rglob("*.csv.gz"))
    fwd=sorted(Path(args.forward_ohlcv_root).rglob("*.csv.gz"))
    con=duckdb.connect()
    con.execute("PRAGMA threads=4")

    cols={r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(str(matrix))})").fetchall()}
    rows,unique_keys,min_trade,max_trade,min_eff,max_eff = con.execute(f"""
      SELECT count(*),count(DISTINCT (effective_session,exchange,code)),min(trade_date),max(trade_date),min(effective_session),max(effective_session)
      FROM read_parquet({q(str(matrix))})
    """).fetchone()
    source_candidate_rows, source_duplicate_keys = con.execute(f"""
      WITH o AS (
        SELECT exchange,code,trade_date,TRY_CAST(close AS DOUBLE) close_unadjusted
        FROM read_csv({file_list(hist)},header=true,all_varchar=true,union_by_name=true)
        UNION ALL
        SELECT exchange,code,trade_date,TRY_CAST(close AS DOUBLE)
        FROM read_csv({file_list(fwd)},header=true,all_varchar=true,union_by_name=true)
      ), r AS (
        SELECT trade_date,effective_session FROM read_csv({q(args.market_regime)},header=true,all_varchar=true)
      ), c AS (
        SELECT o.exchange,o.code,o.trade_date,r.effective_session FROM o JOIN r USING(trade_date)
        WHERE o.close_unadjusted>0 AND o.close_unadjusted<70
      )
      SELECT count(*),count(*)-count(DISTINCT (effective_session,exchange,code)) FROM c
    """).fetchone()

    temporal = con.execute(f"""
      SELECT
        sum(CASE WHEN NOT (trade_date<effective_session) THEN 1 ELSE 0 END),
        sum(CASE WHEN financial_source_effective_session IS NOT NULL AND financial_source_effective_session>effective_session THEN 1 ELSE 0 END),
        sum(CASE WHEN surprise_effective_session IS NOT NULL AND surprise_effective_session>effective_session THEN 1 ELSE 0 END),
        sum(CASE WHEN financial_report_age_sessions<0 THEN 1 ELSE 0 END),
        sum(CASE WHEN guidance_age_sessions<0 THEN 1 ELSE 0 END),
        sum(CASE WHEN close_unadjusted<=0 OR close_unadjusted>=70 THEN 1 ELSE 0 END)
      FROM read_parquet({q(str(matrix))})
    """).fetchone()

    con.execute(f"CREATE VIEW m AS SELECT * FROM read_parquet({q(str(matrix))})")
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_csv({q(args.market_regime)},header=true,all_varchar=true)")
    regime_mismatch_parts=["m.regime_state IS DISTINCT FROM r.regime_state"]
    for c in MARKET_NUMERIC:
        regime_mismatch_parts.append(f"m.{c} IS DISTINCT FROM TRY_CAST(r.{c} AS DOUBLE)")
    regime_mismatches=con.execute(f"""
      SELECT count(*) FROM m JOIN r ON m.trade_date=r.trade_date AND m.effective_session=r.effective_session
      WHERE {' OR '.join(regime_mismatch_parts)}
    """).fetchone()[0]
    regime_join_missing=con.execute("SELECT count(*) FROM m LEFT JOIN r ON m.trade_date=r.trade_date AND m.effective_session=r.effective_session WHERE r.trade_date IS NULL").fetchone()[0]

    missing_inconsistency=0
    for c in FIN:
        missing_inconsistency += con.execute(
            f"SELECT count(*) FROM m WHERE ({c} IS NULL AND {c}_missing<>1) OR ({c} IS NOT NULL AND {c}_missing<>0)"
        ).fetchone()[0]
    surprise_missing_inconsistency=con.execute(
        "SELECT count(*) FROM m WHERE (official_guidance_surprise IS NULL AND official_guidance_surprise_missing<>1) OR (official_guidance_surprise IS NOT NULL AND official_guidance_surprise_missing<>0)"
    ).fetchone()[0]

    actual_coverage={r["feature"]:(r["rows"],r["nonnull_rows"],r["missing_rows"]) for r in coverage}
    coverage_mismatches=[]
    for feature,(reported_rows,reported_nonnull,reported_missing) in actual_coverage.items():
        if feature not in cols:
            coverage_mismatches.append(feature+":missing-column"); continue
        actual_nonnull=con.execute(f"SELECT count({feature}) FROM m").fetchone()[0]
        if reported_rows!=rows or reported_nonnull!=actual_nonnull or reported_missing!=rows-actual_nonnull:
            coverage_mismatches.append(feature)

    prohibited_tokens=("industry","news","social","future_return","forward_return","target_return","label")
    prohibited_columns=sorted(c for c in cols if any(t in c.lower() for t in prohibited_tokens))

    checks={
        "schema_exact": cols==EXPECTED_COLUMNS,
        "matrix_rows_positive": rows>0,
        "matrix_key_unique": rows==unique_keys,
        "source_candidate_population_exact": rows==source_candidate_rows and source_duplicate_keys==0,
        "combined_source_rows_exact": build["ohlcv_rows"]==contract["expected_inputs"]["combined_ohlcv_rows"],
        "trade_date_max_exact": max_trade==contract["expected_outputs"]["trade_date_max"],
        "effective_session_max_exact": max_eff==contract["expected_outputs"]["effective_session_max"],
        "next_session_semantics": temporal[0]==0,
        "financial_no_future": temporal[1]==0 and temporal[3]==0,
        "surprise_no_future": temporal[2]==0 and temporal[4]==0,
        "strict_price_universe": temporal[5]==0,
        "regime_exact_join": regime_mismatches==0 and regime_join_missing==0,
        "financial_missing_indicators_exact": missing_inconsistency==0,
        "surprise_missing_indicator_exact": surprise_missing_inconsistency==0,
        "coverage_report_exact": not coverage_mismatches,
        "prohibited_columns_absent": not prohibited_columns,
        "universe_policy_exact": universe.get("pass") is True and universe.get("boards")==["SSE_MAIN_A","SZSE_MAIN_A"] and universe.get("strict_price_rule")=="<70 CNY" and universe.get("exact_70_excluded") is True,
        "feature_set_v1_1_exact": feature_set["feature_set_version"]=="V1.1" and feature_set["feature_set_fingerprint"]==contract["feature_set_fingerprint"],
        "industry_excluded": feature_set["source_facts"]["industry_artifact"]["normalized_primary_code_rows"]==19048 and feature_set["invariants"]["industry_identity_model_input_disabled_until_separate_normalization_plugin_is_tested_and_accepted"] is True,
        "no_training_or_live_authorization": manifest["alpha_training_allowed"] is False and manifest["live_signal_allowed"] is False and manifest["authoritative_model_output"] is False,
    }
    failed=[k for k,v in checks.items() if not v]
    report={
        "gate":"STAGE4_V1_FEATURE_MATRIX_PIT_COVERAGE_MISSINGNESS_NON_LEAKAGE_AUDIT",
        "pass":not failed,
        "matrix_rows":rows,"unique_matrix_keys":unique_keys,"source_candidate_rows":source_candidate_rows,
        "trade_date_min":min_trade,"trade_date_max":max_trade,"effective_session_min":min_eff,"effective_session_max":max_eff,
        "temporal_violation_counts":{
            "bad_next_session":temporal[0],"future_financial":temporal[1],"future_surprise":temporal[2],
            "negative_financial_age":temporal[3],"negative_guidance_age":temporal[4],"price_rule_violations":temporal[5]
        },
        "regime_mismatches":regime_mismatches,"regime_join_missing":regime_join_missing,
        "financial_missing_indicator_mismatches":missing_inconsistency,
        "surprise_missing_indicator_mismatches":surprise_missing_inconsistency,
        "coverage_mismatches":coverage_mismatches,"prohibited_columns":prohibited_columns,
        "checks":checks,"failed_checks":failed,
        "alpha_training_allowed":False,"live_signal_allowed":False,"authoritative_model_output":False,
        "next_gate":"SEPARATE_STAGE4_ALPHA_V1_TRAINING_PREREGISTRATION_AND_OOS_DESIGN"
    }
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["pass"] else 2


if __name__=="__main__":
    raise SystemExit(main())
