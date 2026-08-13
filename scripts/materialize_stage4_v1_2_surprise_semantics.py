#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

TRANSFORMED = [
    "official_guidance_surprise",
    "official_guidance_surprise_missing",
    "guidance_age_sessions",
    "surprise_effective_session",
    "surprise_economic_date",
]
FEATURE_COVERAGE = [
    "close_unadjusted","total_return_1d","total_return_5d","total_return_20d","realized_volatility_20d",
    "amount_ratio_5d_20d_stock","volume_ratio_5d_20d_stock","relative_strength_vs_market_20d",
    "regime_state","advance_ratio","net_breadth","ew_return_5d","ew_return_20d","net_breadth_5d_mean",
    "ew_return_vol_20d","cross_sectional_return_std_1d","amount_ratio_5d_20d",
    "fin_total_assets_cny","fin_total_liabilities_cny","fin_total_equity_cny","fin_parent_equity_cny",
    "fin_operating_revenue_cny","fin_operating_cost_cny","fin_parent_net_profit_cny",
    "fin_parent_net_profit_ex_nonrecurring_cny","fin_operating_cash_flow_cny",
    "fin_total_assets_cny_missing","fin_total_liabilities_cny_missing","fin_total_equity_cny_missing",
    "fin_parent_equity_cny_missing","fin_operating_revenue_cny_missing","fin_operating_cost_cny_missing",
    "fin_parent_net_profit_cny_missing","fin_parent_net_profit_ex_nonrecurring_cny_missing",
    "fin_operating_cash_flow_cny_missing","financial_report_age_sessions",
    "official_guidance_surprise","official_guidance_surprise_missing","guidance_age_sessions",
]


def q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--base-matrix",required=True)
    ap.add_argument("--feature-set-contract",required=True)
    ap.add_argument("--matrix-contract",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    import duckdb

    feature=json.loads(Path(args.feature_set_contract).read_text(encoding="utf-8"))
    contract=json.loads(Path(args.matrix_contract).read_text(encoding="utf-8"))
    if feature["feature_set_version"]!="V1.2" or contract["matrix_version"]!="V1.2":
        raise ValueError("V1.2 contracts required")
    if feature["feature_set_fingerprint"]!=contract["feature_set_fingerprint"]:
        raise ValueError("feature/matrix fingerprint mismatch")
    if feature["feature_set_fingerprint"]!="d319ea1c236d580d0d032a055e4cdc07bf45e586ecbef664c6f4b3a8be98f9ff":
        raise ValueError("unexpected V1.2 feature fingerprint")

    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    base=Path(args.base_matrix)
    matrix=out/"stage4_v1_2_feature_matrix.parquet"
    con=duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='5GB'")
    con.execute(f"""
      COPY (
        SELECT * EXCLUDE ({','.join(TRANSFORMED)}),
          CASE WHEN surprise_economic_date=financial_economic_date
               THEN official_guidance_surprise ELSE NULL END AS official_guidance_surprise,
          CASE WHEN surprise_economic_date=financial_economic_date AND official_guidance_surprise IS NOT NULL
               THEN 0 ELSE 1 END AS official_guidance_surprise_missing,
          CASE WHEN surprise_economic_date=financial_economic_date
               THEN guidance_age_sessions ELSE NULL END AS guidance_age_sessions,
          CASE WHEN surprise_economic_date=financial_economic_date
               THEN surprise_effective_session ELSE NULL END AS surprise_effective_session,
          CASE WHEN surprise_economic_date=financial_economic_date
               THEN surprise_economic_date ELSE NULL END AS surprise_economic_date
        FROM read_parquet({q(str(base))})
        ORDER BY effective_session,exchange,code
      ) TO {q(str(matrix))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    base_stats=con.execute(f"""
      SELECT count(*),count(DISTINCT (effective_session,exchange,code)),
        sum(CASE WHEN official_guidance_surprise IS NOT NULL THEN 1 ELSE 0 END),
        sum(CASE WHEN official_guidance_surprise IS NOT NULL AND surprise_economic_date=financial_economic_date THEN 1 ELSE 0 END),
        sum(CASE WHEN official_guidance_surprise IS NOT NULL AND (financial_economic_date IS NULL OR surprise_economic_date IS DISTINCT FROM financial_economic_date) THEN 1 ELSE 0 END)
      FROM read_parquet({q(str(base))})
    """).fetchone()
    new_stats=con.execute(f"""
      SELECT count(*),count(DISTINCT (effective_session,exchange,code)),
        sum(CASE WHEN official_guidance_surprise IS NOT NULL THEN 1 ELSE 0 END),
        sum(CASE WHEN official_guidance_surprise IS NOT NULL AND surprise_economic_date=financial_economic_date THEN 1 ELSE 0 END),
        sum(CASE WHEN official_guidance_surprise IS NOT NULL AND surprise_economic_date IS DISTINCT FROM financial_economic_date THEN 1 ELSE 0 END),
        sum(CASE WHEN official_guidance_surprise IS NULL AND official_guidance_surprise_missing<>1 THEN 1 ELSE 0 END),
        sum(CASE WHEN official_guidance_surprise IS NOT NULL AND official_guidance_surprise_missing<>0 THEN 1 ELSE 0 END),
        sum(CASE WHEN guidance_age_sessions<0 THEN 1 ELSE 0 END),
        max(guidance_age_sessions),
        quantile_cont(guidance_age_sessions,0.50),
        sum(CASE WHEN guidance_age_sessions>252 THEN 1 ELSE 0 END),
        sum(CASE WHEN guidance_age_sessions>504 THEN 1 ELSE 0 END)
      FROM read_parquet({q(str(matrix))})
    """).fetchone()

    coverage=[]
    rows=new_stats[0]
    for col in FEATURE_COVERAGE:
        nonnull,distinct_count=con.execute(
            f"SELECT count({col}),count(DISTINCT {col}) FROM read_parquet({q(str(matrix))})"
        ).fetchone()
        coverage.append({"feature":col,"rows":rows,"nonnull_rows":nonnull,"missing_rows":rows-nonnull,
                         "coverage_ratio":nonnull/rows if rows else 0.0,"distinct_nonnull":distinct_count})
    coverage_path=out/"feature_coverage.json"
    coverage_path.write_text(json.dumps(coverage,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    report={
      "gate":"STAGE4_V1_2_SURPRISE_SEMANTIC_MATERIALIZATION",
      "pass": all([
          base_stats[0]==7924181, base_stats[0]==base_stats[1],
          new_stats[0]==base_stats[0], new_stats[0]==new_stats[1],
          base_stats[2]==5733019, base_stats[3]==1756064, base_stats[4]==3976955,
          new_stats[2]==1756064, new_stats[3]==1756064, new_stats[4]==0,
          new_stats[5]==0, new_stats[6]==0, new_stats[7]==0,
      ]),
      "feature_set_version":"V1.2",
      "feature_set_fingerprint":feature["feature_set_fingerprint"],
      "base_matrix_rows":base_stats[0],
      "base_surprise_nonnull_rows":base_stats[2],
      "base_current_period_surprise_rows":base_stats[3],
      "base_prior_period_stale_surprise_rows":base_stats[4],
      "matrix_rows":new_stats[0],
      "active_current_period_surprise_rows":new_stats[2],
      "active_surprise_period_mismatch_rows":new_stats[4],
      "surprise_missing_indicator_mismatches":new_stats[5]+new_stats[6],
      "negative_guidance_age_rows":new_stats[7],
      "active_guidance_age_max_sessions":new_stats[8],
      "active_guidance_age_p50_sessions":new_stats[9],
      "active_guidance_age_gt_252_rows":new_stats[10],
      "active_guidance_age_gt_504_rows":new_stats[11],
      "matrix_sha256":sha256_file(matrix),
      "coverage_sha256":sha256_file(coverage_path),
      "transformed_columns":TRANSFORMED,
      "transformation":"MASK_PRIOR_FINANCIAL_PERIOD_SURPRISE_TO_MISSING_NO_FIXED_DAY_EXPIRY",
      "industry_identity_in_matrix":False,
      "alpha_training_allowed":False,
      "live_signal_allowed":False,
      "authoritative_model_output":False,
    }
    (out/"materialization_audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    manifest={
      "schema_version":1,
      "matrix_id":"STAGE4_V1_FEATURE_MATRIX",
      "matrix_version":"V1.2",
      "status":"MATERIALIZED_PRETRAINING",
      "feature_set_fingerprint":feature["feature_set_fingerprint"],
      "base_matrix_artifact_id":9168438550,
      "base_matrix_sha256":"1818f9cdaf86c965e45c07cd1d261ece0eb782a6aa0aa6846d18701bd8699feb",
      "matrix_sha256":report["matrix_sha256"],
      "coverage_sha256":report["coverage_sha256"],
      "row_count":rows,
      "surprise_semantics":"ACTIVE_ONLY_WHEN_SURPRISE_ECONOMIC_DATE_EQUALS_CURRENT_FINANCIAL_ECONOMIC_DATE",
      "industry_identity":"EXCLUDED_PENDING_NORMALIZATION_PLUGIN",
      "alpha_training_allowed":False,
      "live_signal_allowed":False,
      "authoritative_model_output":False,
      "next_gate":"INDEPENDENT_V1_2_MATRIX_EQUIVALENCE_PIT_AND_SURPRISE_SEMANTIC_AUDIT"
    }
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["pass"] else 2

if __name__=="__main__":
    raise SystemExit(main())
