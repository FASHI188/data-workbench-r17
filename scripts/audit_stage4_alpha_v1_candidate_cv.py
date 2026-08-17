#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math
from pathlib import Path


def q(s: str) -> str: return "'" + s.replace("'", "''") + "'"

def close(a, b, tol=1e-10):
    if a is None or b is None: return a is None and b is None
    return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a)-float(b)) <= tol


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--candidate-dir',required=True); ap.add_argument('--authorization',required=True); ap.add_argument('--execution-contract',required=True); ap.add_argument('--split-seal',required=True); ap.add_argument('--out',required=True)
    args=ap.parse_args()
    import duckdb

    d=Path(args.candidate_dir); auth=json.loads(Path(args.authorization).read_text(encoding='utf-8')); exe=json.loads(Path(args.execution_contract).read_text(encoding='utf-8')); split=json.loads(Path(args.split_seal).read_text(encoding='utf-8'))
    summary=json.loads((d/'candidate_summary.json').read_text(encoding='utf-8')); trials=json.loads((d/'trial_log.json').read_text(encoding='utf-8')); metrics=json.loads((d/'split_metrics.json').read_text(encoding='utf-8')); prep=json.loads((d/'preprocess_manifest.json').read_text(encoding='utf-8')); runtime=json.loads((d/'runtime_manifest.json').read_text(encoding='utf-8'))
    cid=summary['candidate_id']; catalog={x['candidate_id']:x for x in auth['fingerprint_basis']['candidate_catalog']}; spec=catalog[cid]
    checks:dict[str,bool]={}
    checks['authorization_and_execution_exact']=(auth['fingerprint']=='2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c' and exe['fingerprint']=='9b449b9c12ac98f1516812dfa4d3f40922668e35462087637cea79e81c1645dc' and exe['fingerprint_basis']['authorization_fingerprint']==auth['fingerprint'])
    checks['candidate_identity_exact']=(summary['ordinal']==spec['ordinal'] and summary['family']==spec['family'] and summary['params']==spec['params'])
    checks['five_trial_records_exact']=len(trials)==5 and [int(t['split_id']) for t in trials]==[1,2,3,4,5]
    checks['preprocess_five_splits_exact']=len(prep['splits'])==5 and [int(x['split_id']) for x in prep['splits']]==[1,2,3,4,5]
    checks['runtime_exact']=(runtime['python']=='3.12.13' and runtime['numpy']=='2.5.1' and runtime['scipy']=='1.17.0' and runtime['scikit_learn']=='1.9.0' and runtime['pyarrow']=='25.0.0' and runtime['duckdb']=='1.3.2' and all(runtime['threads'].get(k)=='1' for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']))
    checks['no_final_refit_or_sealed_access']=summary['model_final_refit_executed'] is False and summary['oos_accessed'] is False and summary['lockbox_accessed'] is False

    success=[t for t in trials if t['status']=='SUCCESS']; failed=[t for t in trials if t['status']!='SUCCESS']; structural_invalid_ok=(not summary['candidate_valid'] and (len(failed)>0 or any(not m.get('split_valid',False) for m in metrics)))
    if not summary['candidate_valid']:
        checks['invalid_candidate_has_explicit_reason']=structural_invalid_ok
        checks['summary_success_count_exact']=summary['successful_trials']==len(success)
        checks['no_oof_required_for_failed_candidate']=True
        failed_checks=[k for k,v in checks.items() if not v]
        report={'gate':'STAGE4_ALPHA_V1_CANDIDATE_CV_INDEPENDENT_AUDIT','pass':not failed_checks,'candidate_id':cid,'candidate_valid':False,'checks':checks,'failed_checks':failed_checks,'fit_failed_splits':[t['split_id'] for t in failed],'model_final_refit_executed':False,'oos_accessed':False,'lockbox_accessed':False}
        Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if report['pass'] else 2

    oof=d/'oof_predictions.parquet'; daily=d/'daily_metrics.parquet'
    checks['valid_candidate_all_splits_success']=len(success)==5 and len(metrics)==5 and all(m['split_valid'] for m in metrics)
    checks['oof_files_present']=oof.is_file() and daily.is_file()
    con=duckdb.connect(); con.execute("PRAGMA threads=4"); con.execute("PRAGMA memory_limit='5GB'"); con.execute("PRAGMA temp_directory='build/duckdb-candidate-audit-tmp'")
    cols={r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(str(oof))})").fetchall()}
    expected={'trade_date','exchange','code','split_id','prediction','excess_return_20d','excess_return_5d','stock_total_return_20d','benchmark_return_20d'}
    checks['oof_schema_exact']=cols==expected
    rows,ukeys,bad_pred,bad_sid=con.execute(f"SELECT count(*),count(DISTINCT (trade_date,exchange,code,split_id)),sum(CASE WHEN NOT isfinite(prediction) THEN 1 ELSE 0 END),sum(CASE WHEN split_id<1 OR split_id>5 THEN 1 ELSE 0 END) FROM read_parquet({q(str(oof))})").fetchone()
    checks['oof_unique_and_finite']=rows==ukeys==summary['oof_rows'] and bad_pred==0 and bad_sid==0

    split_by_id={int(s['split_id']):s for s in split['splits']}; drift=0
    for sid in range(1,6):
        s=split_by_id[sid]
        n,bad=con.execute(f"SELECT count(*),sum(CASE WHEN trade_date<DATE {q(s['test_start'])} OR trade_date>DATE {q(s['test_end'])} THEN 1 ELSE 0 END) FROM read_parquet({q(str(oof))}) WHERE split_id={sid}").fetchone()
        trial=next(t for t in trials if int(t['split_id'])==sid)
        if n!=trial['test_rows'] or (bad or 0)!=0: drift+=1
    checks['oof_rows_match_authorized_test_blocks']=drift==0

    # 20d ranks use all valid-20d OOF rows. 5d Spearman is recomputed independently on the pairwise non-null 5d subset.
    recomputed=con.execute(f"""
      WITH x20 AS (
        SELECT *,
          rank() OVER(PARTITION BY split_id,trade_date ORDER BY prediction) + (count(*) OVER(PARTITION BY split_id,trade_date,prediction)-1)/2.0 AS rp20,
          rank() OVER(PARTITION BY split_id,trade_date ORDER BY excess_return_20d) + (count(*) OVER(PARTITION BY split_id,trade_date,excess_return_20d)-1)/2.0 AS ry20,
          row_number() OVER(PARTITION BY split_id,trade_date ORDER BY prediction DESC,exchange,code) AS score_rn,
          count(*) OVER(PARTITION BY split_id,trade_date) AS n
        FROM read_parquet({q(str(oof))})
      ), d20 AS (
        SELECT split_id,trade_date,count(*) n20,
          CASE WHEN count(*)>=20 AND count(DISTINCT prediction)>1 AND count(DISTINCT excess_return_20d)>1 THEN corr(rp20,ry20) END AS daily_ic_20d,
          max(CAST(ceil(0.10*n) AS BIGINT)) AS top10_n,
          avg(excess_return_20d) FILTER(WHERE score_rn<=CAST(ceil(0.10*n) AS BIGINT)) AS top10_gross_excess_20d,
          avg(stock_total_return_20d) FILTER(WHERE score_rn<=CAST(ceil(0.10*n) AS BIGINT)) AS top10_stock_total_return_20d,
          avg(benchmark_return_20d) FILTER(WHERE score_rn<=CAST(ceil(0.10*n) AS BIGINT)) AS benchmark_return_20d
        FROM x20 GROUP BY split_id,trade_date
      ), x5 AS (
        SELECT *,
          rank() OVER(PARTITION BY split_id,trade_date ORDER BY prediction) + (count(*) OVER(PARTITION BY split_id,trade_date,prediction)-1)/2.0 AS rp5,
          rank() OVER(PARTITION BY split_id,trade_date ORDER BY excess_return_5d) + (count(*) OVER(PARTITION BY split_id,trade_date,excess_return_5d)-1)/2.0 AS ry5
        FROM read_parquet({q(str(oof))}) WHERE excess_return_5d IS NOT NULL AND isfinite(excess_return_5d)
      ), d5 AS (
        SELECT split_id,trade_date,count(*) n5,
          CASE WHEN count(*)>=20 AND count(DISTINCT prediction)>1 AND count(DISTINCT excess_return_5d)>1 THEN corr(rp5,ry5) END AS daily_ic_5d
        FROM x5 GROUP BY split_id,trade_date
      ), d AS (
        SELECT d20.*,coalesce(d5.n5,0) n5,d5.daily_ic_5d FROM d20 LEFT JOIN d5 USING(split_id,trade_date)
      ), orig AS (SELECT * FROM read_parquet({q(str(daily))}))
      SELECT count(*),
        max(abs(d.daily_ic_20d-orig.daily_ic_20d)) FILTER(WHERE d.daily_ic_20d IS NOT NULL AND orig.daily_ic_20d IS NOT NULL),
        max(abs(d.daily_ic_5d-orig.daily_ic_5d)) FILTER(WHERE d.daily_ic_5d IS NOT NULL AND orig.daily_ic_5d IS NOT NULL),
        max(abs(d.top10_gross_excess_20d-orig.top10_gross_excess_20d)),
        max(abs(d.top10_stock_total_return_20d-orig.top10_stock_total_return_20d)),
        max(abs(d.benchmark_return_20d-orig.benchmark_return_20d)),
        sum(CASE WHEN d.top10_n<>orig.top10_n OR d.n20<>orig.n20 OR d.n5<>orig.n5 THEN 1 ELSE 0 END),
        sum(CASE WHEN (d.daily_ic_20d IS NULL)<>(orig.daily_ic_20d IS NULL) THEN 1 ELSE 0 END),
        sum(CASE WHEN (d.daily_ic_5d IS NULL)<>(orig.daily_ic_5d IS NULL) THEN 1 ELSE 0 END)
      FROM d JOIN orig USING(split_id,trade_date)
    """).fetchone()
    day_rows,err20,err5,errtop,errstock,errbench,badcounts,null20,null5=recomputed
    checks['daily_metric_rows_exact']=day_rows==con.execute(f"SELECT count(*) FROM read_parquet({q(str(daily))})").fetchone()[0]
    checks['daily_spearman_recomputed']=float(err20 or 0)<1e-10 and float(err5 or 0)<1e-10 and (null20 or 0)==0 and (null5 or 0)==0
    checks['daily_counts_and_top_bucket_recomputed']=float(errtop or 0)<1e-10 and float(errstock or 0)<1e-10 and float(errbench or 0)<1e-10 and (badcounts or 0)==0

    recomputed_metrics=[]
    for sid in range(1,6):
        vals=con.execute(f"SELECT count(*),count(daily_ic_20d),avg(daily_ic_20d),avg(daily_ic_5d) FROM read_parquet({q(str(daily))}) WHERE split_id={sid}").fetchone(); test_days,nonnull,mean20,mean5=vals; recomputed_metrics.append((sid,test_days,nonnull,mean20,mean5))
    split_ok=True
    for sid,test_days,nonnull,mean20,mean5 in recomputed_metrics:
        m=next(x for x in metrics if int(x['split_id'])==sid); split_ok &= m['test_days']==test_days and m['nonnull_ic20_days']==nonnull and close(m['mean_daily_ic_20d'],mean20) and close(m['mean_daily_ic_5d'],mean5)
    checks['split_metrics_recomputed']=bool(split_ok)
    means=[x[3] for x in recomputed_metrics]
    checks['candidate_selection_statistics_recomputed']=close(summary['primary_median_split_mean_daily_ic_20d'],sorted(means)[2]) and close(summary['worst_split_mean_daily_ic_20d'],min(means))

    failed_checks=[k for k,v in checks.items() if not v]
    report={'gate':'STAGE4_ALPHA_V1_CANDIDATE_CV_INDEPENDENT_AUDIT','pass':not failed_checks,'candidate_id':cid,'candidate_valid':True,'checks':checks,'failed_checks':failed_checks,'oof_rows':rows,'daily_ic20_max_abs_error':float(err20 or 0),'daily_ic5_max_abs_error':float(err5 or 0),'top10_excess_max_abs_error':float(errtop or 0),'model_final_refit_executed':False,'oos_accessed':False,'lockbox_accessed':False}
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if report['pass'] else 2

if __name__=='__main__': raise SystemExit(main())
