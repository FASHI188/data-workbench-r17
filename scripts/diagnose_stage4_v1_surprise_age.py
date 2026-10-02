#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def stats(con, matrix: str, where: str) -> dict:
    row=con.execute(f"""
      SELECT
        count(*),
        min(guidance_age_sessions),
        quantile_cont(guidance_age_sessions,0.50),
        quantile_cont(guidance_age_sessions,0.75),
        quantile_cont(guidance_age_sessions,0.90),
        quantile_cont(guidance_age_sessions,0.95),
        quantile_cont(guidance_age_sessions,0.99),
        max(guidance_age_sessions),
        sum(CASE WHEN guidance_age_sessions<=5 THEN 1 ELSE 0 END),
        sum(CASE WHEN guidance_age_sessions<=20 THEN 1 ELSE 0 END),
        sum(CASE WHEN guidance_age_sessions<=60 THEN 1 ELSE 0 END),
        sum(CASE WHEN guidance_age_sessions<=120 THEN 1 ELSE 0 END),
        sum(CASE WHEN guidance_age_sessions>252 THEN 1 ELSE 0 END),
        sum(CASE WHEN guidance_age_sessions>504 THEN 1 ELSE 0 END)
      FROM read_parquet('{matrix}') WHERE {where}
    """).fetchone()
    return {
      'rows':row[0],
      'age':{'min':row[1],'p50':row[2],'p75':row[3],'p90':row[4],'p95':row[5],'p99':row[6],'max':row[7]},
      'windows':{'le_5':row[8],'le_20':row[9],'le_60':row[10],'le_120':row[11],'gt_252':row[12],'gt_504':row[13]}
    }


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--matrix',required=True)
    ap.add_argument('--out',required=True)
    args=ap.parse_args()
    import duckdb
    con=duckdb.connect()
    matrix=args.matrix.replace("'","''")
    total=con.execute(f"SELECT count(*) FROM read_parquet('{matrix}')").fetchone()[0]
    all_surprise=stats(con,matrix,"official_guidance_surprise IS NOT NULL")
    current_report=stats(con,matrix,"official_guidance_surprise IS NOT NULL AND surprise_economic_date=financial_economic_date")
    mismatch=con.execute(f"""
      SELECT count(*) FROM read_parquet('{matrix}')
      WHERE official_guidance_surprise IS NOT NULL
        AND (financial_economic_date IS NULL OR surprise_economic_date IS DISTINCT FROM financial_economic_date)
    """).fetchone()[0]
    report={
      'gate':'STAGE4_V1_SURPRISE_AGE_SEMANTIC_DIAGNOSTIC_R2',
      'matrix_artifact_id':9168438550,
      'matrix_artifact_digest':'sha256:813ae234c149fb30f725895cd67bcfbe404b1050cba9f915c9c4c0f5a1392a42',
      'matrix_sha256':'1818f9cdaf86c965e45c07cd1d261ece0eb782a6aa0aa6846d18701bd8699feb',
      'matrix_total_rows':total,
      'all_asof_surprise':all_surprise,
      'current_report_period_match':current_report,
      'surprise_rows_not_matching_current_financial_period':mismatch,
      'current_report_match_ratio_of_surprise':current_report['rows']/all_surprise['rows'] if all_surprise['rows'] else 0,
      'interpretation_tested':'SURPRISE_EVENT_ACTIVE_ONLY_WHILE_ITS_ECONOMIC_DATE_EQUALS_CURRENT_LATEST_FINANCIAL_ECONOMIC_DATE',
      'diagnostic_only':True,
      'alpha_training_allowed':False,
      'live_signal_allowed':False
    }
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
