#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

TRANSFORMED={
    "official_guidance_surprise","official_guidance_surprise_missing","guidance_age_sessions",
    "surprise_effective_session","surprise_economic_date"
}
KEYS=["effective_session","exchange","code"]


def q(v:str)->str:
    return "'"+v.replace("'","''")+"'"


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--base-matrix',required=True)
    ap.add_argument('--matrix',required=True)
    ap.add_argument('--base-independent-audit',required=True)
    ap.add_argument('--base-execution-manifest',required=True)
    ap.add_argument('--materialization-audit',required=True)
    ap.add_argument('--manifest',required=True)
    ap.add_argument('--feature-set-contract',required=True)
    ap.add_argument('--matrix-contract',required=True)
    ap.add_argument('--out',required=True)
    args=ap.parse_args()
    import duckdb

    base_audit=json.loads(Path(args.base_independent_audit).read_text(encoding='utf-8'))
    base_exec=json.loads(Path(args.base_execution_manifest).read_text(encoding='utf-8'))
    mat=json.loads(Path(args.materialization_audit).read_text(encoding='utf-8'))
    manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
    feature=json.loads(Path(args.feature_set_contract).read_text(encoding='utf-8'))
    contract=json.loads(Path(args.matrix_contract).read_text(encoding='utf-8'))
    con=duckdb.connect(); con.execute('PRAGMA threads=4')
    b=q(args.base_matrix); n=q(args.matrix)
    base_cols=[r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({b})").fetchall()]
    new_cols=[r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({n})").fetchall()]
    unaffected=[c for c in base_cols if c not in TRANSFORMED]
    mismatch_pred=' OR '.join(f'b.{c} IS DISTINCT FROM n.{c}' for c in unaffected)
    unaffected_mismatches=con.execute(f"""
      SELECT count(*) FROM read_parquet({b}) b
      JOIN read_parquet({n}) n USING(effective_session,exchange,code)
      WHERE {mismatch_pred}
    """).fetchone()[0]
    counts=con.execute(f"""
      SELECT
       (SELECT count(*) FROM read_parquet({b})),
       (SELECT count(*) FROM read_parquet({n})),
       (SELECT count(DISTINCT (effective_session,exchange,code)) FROM read_parquet({n})),
       (SELECT count(*) FROM read_parquet({n}) WHERE official_guidance_surprise IS NOT NULL),
       (SELECT count(*) FROM read_parquet({n}) WHERE official_guidance_surprise IS NOT NULL AND surprise_economic_date IS DISTINCT FROM financial_economic_date),
       (SELECT count(*) FROM read_parquet({n}) WHERE official_guidance_surprise IS NULL AND official_guidance_surprise_missing<>1),
       (SELECT count(*) FROM read_parquet({n}) WHERE official_guidance_surprise IS NOT NULL AND official_guidance_surprise_missing<>0),
       (SELECT count(*) FROM read_parquet({n}) WHERE guidance_age_sessions<0),
       (SELECT count(*) FROM read_parquet({n}) WHERE surprise_effective_session IS NOT NULL AND surprise_effective_session>effective_session),
       (SELECT min(trade_date) FROM read_parquet({n})),
       (SELECT max(trade_date) FROM read_parquet({n})),
       (SELECT min(effective_session) FROM read_parquet({n})),
       (SELECT max(effective_session) FROM read_parquet({n}))
    """).fetchone()
    base_active=con.execute(f"""
      SELECT count(*) FROM read_parquet({b})
      WHERE official_guidance_surprise IS NOT NULL AND surprise_economic_date=financial_economic_date
    """).fetchone()[0]
    base_stale=con.execute(f"""
      SELECT count(*) FROM read_parquet({b})
      WHERE official_guidance_surprise IS NOT NULL
        AND (financial_economic_date IS NULL OR surprise_economic_date IS DISTINCT FROM financial_economic_date)
    """).fetchone()[0]
    transformed_exact=con.execute(f"""
      SELECT count(*) FROM read_parquet({b}) b
      JOIN read_parquet({n}) n USING(effective_session,exchange,code)
      WHERE
        n.official_guidance_surprise IS DISTINCT FROM CASE WHEN b.surprise_economic_date=b.financial_economic_date THEN b.official_guidance_surprise ELSE NULL END
        OR n.official_guidance_surprise_missing IS DISTINCT FROM CASE WHEN b.surprise_economic_date=b.financial_economic_date AND b.official_guidance_surprise IS NOT NULL THEN 0 ELSE 1 END
        OR n.guidance_age_sessions IS DISTINCT FROM CASE WHEN b.surprise_economic_date=b.financial_economic_date THEN b.guidance_age_sessions ELSE NULL END
        OR n.surprise_effective_session IS DISTINCT FROM CASE WHEN b.surprise_economic_date=b.financial_economic_date THEN b.surprise_effective_session ELSE NULL END
        OR n.surprise_economic_date IS DISTINCT FROM CASE WHEN b.surprise_economic_date=b.financial_economic_date THEN b.surprise_economic_date ELSE NULL END
    """).fetchone()[0]
    prohibited=[c for c in new_cols if any(t in c.lower() for t in ('industry','news','social','future_return','forward_return','target_return','label'))]
    checks={
      'base_r3_independent_audit_pass':base_audit.get('pass') is True and base_exec.get('independent_audit_pass') is True,
      'base_r3_exact_identity':base_exec.get('matrix_rows')==7924181 and base_exec.get('matrix_sha256')=='1818f9cdaf86c965e45c07cd1d261ece0eb782a6aa0aa6846d18701bd8699feb',
      'feature_set_v1_2_exact':feature.get('feature_set_version')=='V1.2' and feature.get('feature_set_fingerprint')=='d319ea1c236d580d0d032a055e4cdc07bf45e586ecbef664c6f4b3a8be98f9ff' and contract.get('feature_set_fingerprint')==feature.get('feature_set_fingerprint'),
      'schema_set_unchanged':set(base_cols)==set(new_cols),
      'row_population_unchanged':counts[0]==counts[1]==counts[2]==7924181,
      'all_unaffected_columns_exact':unaffected_mismatches==0,
      'transformed_columns_exact':transformed_exact==0,
      'active_surprise_current_period_only':counts[3]==base_active==1756064 and counts[4]==0,
      'all_prior_period_surprise_removed':base_stale==3976955,
      'surprise_missing_indicator_exact':counts[5]==0 and counts[6]==0,
      'surprise_temporal_valid':counts[7]==0 and counts[8]==0,
      'date_boundaries_unchanged':counts[10]=='2026-08-12' and counts[12]=='2026-08-13',
      'prohibited_columns_absent':not prohibited,
      'materialization_self_audit_pass':mat.get('pass') is True,
      'manifest_pretraining_only':manifest.get('matrix_version')=='V1.2' and manifest.get('alpha_training_allowed') is False and manifest.get('live_signal_allowed') is False and manifest.get('authoritative_model_output') is False,
    }
    failed=[k for k,v in checks.items() if not v]
    report={
      'gate':'STAGE4_V1_2_MATRIX_EQUIVALENCE_PIT_AND_SURPRISE_SEMANTIC_AUDIT',
      'pass':not failed,
      'base_matrix_rows':counts[0],'matrix_rows':counts[1],'unique_matrix_keys':counts[2],
      'unaffected_column_mismatches':unaffected_mismatches,
      'transformed_column_mismatches':transformed_exact,
      'active_current_period_surprise_rows':counts[3],
      'active_surprise_period_mismatch_rows':counts[4],
      'prior_period_surprise_rows_removed':base_stale,
      'surprise_missing_indicator_mismatches':counts[5]+counts[6],
      'negative_guidance_age_rows':counts[7],
      'future_surprise_source_rows':counts[8],
      'trade_date_min':counts[9],'trade_date_max':counts[10],
      'effective_session_min':counts[11],'effective_session_max':counts[12],
      'prohibited_columns':prohibited,
      'checks':checks,'failed_checks':failed,
      'alpha_training_allowed':False,'live_signal_allowed':False,'authoritative_model_output':False,
      'next_gate':'SEPARATE_STAGE4_ALPHA_V1_TRAINING_PREREGISTRATION_AND_OOS_DESIGN'
    }
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['pass'] else 2

if __name__=='__main__':
    raise SystemExit(main())
