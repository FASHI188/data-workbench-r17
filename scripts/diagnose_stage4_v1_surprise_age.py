#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--matrix',required=True)
    ap.add_argument('--out',required=True)
    args=ap.parse_args()
    import duckdb
    con=duckdb.connect()
    matrix=args.matrix.replace("'","''")
    row=con.execute(f"""
      SELECT
        count(*) total_rows,
        count(official_guidance_surprise) surprise_rows,
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
      FROM read_parquet('{matrix}')
      WHERE official_guidance_surprise IS NOT NULL
    """).fetchone()
    total=row[0]; surprise=row[1]
    report={
      'gate':'STAGE4_V1_SURPRISE_AGE_SEMANTIC_DIAGNOSTIC',
      'matrix_artifact_id':9168438550,
      'matrix_artifact_digest':'sha256:813ae234c149fb30f725895cd67bcfbe404b1050cba9f915c9c4c0f5a1392a42',
      'matrix_sha256':'1818f9cdaf86c965e45c07cd1d261ece0eb782a6aa0aa6846d18701bd8699feb',
      'total_rows':total,
      'surprise_nonnull_rows':surprise,
      'surprise_coverage_ratio':surprise/total if total else 0,
      'guidance_age_sessions':{
        'min':row[2],'p50':row[3],'p75':row[4],'p90':row[5],'p95':row[6],'p99':row[7],'max':row[8]
      },
      'fresh_windows':{
        'le_5':row[9],'le_20':row[10],'le_60':row[11],'le_120':row[12],
        'gt_252':row[13],'gt_504':row[14]
      },
      'diagnostic_only':True,
      'alpha_training_allowed':False,
      'live_signal_allowed':False
    }
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
