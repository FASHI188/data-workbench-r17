#!/usr/bin/env python3
from __future__ import annotations

import argparse,gc,hashlib,json,math,os,pickle,re,sys
from datetime import datetime,timezone
from pathlib import Path

AUTH_FP='d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d'
EXEC_FP='224d9144d1989f021c29bb17ce13a6d2644b2d8992d604738b4e596a6907d177'
BOUNDARY_FP='67e8555d3a9212a003a8293dc381cce0f7294917ef72875fed3218f240e0c255'
SOURCE_CV_AUTH_FP='2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c'
MODEL_SHA='e85aabf694799a16f8c5a1dea017e3489a9025ecf3d484d7a4f3fd931b0d702c'
PREPROCESS_SHA='4b7833e4c4bdba9b956dba190f7337003ae944a624b59ddad7654b1457608330'
SOURCE_MATRIX_SHA='c5fca80bc0f35c008590fe8f6cd7b8a16ab22e13b4978314a812f1ecb60b391c'
OOS_START='2023-01-03'; OOS_END='2024-12-31'; LATEST_VALID20='2024-12-03'; LOCKBOX_START='2025-01-02'

def canonical_hash(obj): return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def sha256_file(p:Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def q(s): return "'"+s.replace("'","''")+"'"
def qi(s): return '"'+s.replace('"','""')+'"'
def handling_rate(d): return 0.0000341 if d>='2023-08-28' else 0.0000487
def stamp_rate(d): return 0.0005 if d>='2023-08-28' else 0.001
def cohort_roundtrip_cost(e,x): return 0.003+handling_rate(e)+handling_rate(x)+stamp_rate(x)

def moving_block_bootstrap_mean_ci(values,block=20,resamples=10000,seed=20260817):
    import numpy as np
    x=np.asarray(values,dtype=np.float64)
    if x.ndim!=1 or len(x)<block or not np.isfinite(x).all(): raise ValueError('invalid bootstrap series')
    rng=np.random.Generator(np.random.PCG64(seed)); need=math.ceil(len(x)/block); mx=len(x)-block+1; means=np.empty(resamples,dtype=np.float64)
    for i in range(resamples):
        starts=rng.integers(0,mx,size=need); sample=np.concatenate([x[s:s+block] for s in starts])[:len(x)]; means[i]=sample.mean()
    return float(np.percentile(means,2.5)),float(np.percentile(means,97.5))

def synthetic_self_test():
    import numpy as np
    x=np.linspace(.001,.05,80); a=moving_block_bootstrap_mean_ci(x,resamples=250); b=moving_block_bootstrap_mean_ci(x,resamples=250); assert a==b and a[0]>0
    assert abs(cohort_roundtrip_cost('2023-08-01','2023-08-25')-(.003+2*.0000487+.001))<1e-15
    rows=[{'prediction':.5,'exchange':'SZSE','code':'000002','valid':False},{'prediction':.5,'exchange':'SSE','code':'600001','valid':True},{'prediction':.4,'exchange':'SSE','code':'600002','valid':True}]
    ordered=sorted(rows,key=lambda r:(-r['prediction'],r['exchange'],r['code'])); assert ordered[0]['code']=='600001' and any(not r['valid'] for r in ordered[:2])
    print(json.dumps({'synthetic_self_test':'PASS','bootstrap_ci':a,'economic_label_lookahead':False,'fit_calls':0})); return 0

def validate_authority(a):
    auth=json.loads(Path(a.authorization).read_text(encoding='utf-8')); exe=json.loads(Path(a.execution_contract).read_text(encoding='utf-8')); src=json.loads(Path(a.source_cv_authorization).read_text(encoding='utf-8')); state=json.loads(Path(a.accepted_state).read_text(encoding='utf-8'))
    if auth.get('fingerprint')!=AUTH_FP or canonical_hash(auth['fingerprint_basis'])!=AUTH_FP: raise ValueError('OOS authorization fingerprint mismatch')
    if exe.get('fingerprint')!=EXEC_FP or canonical_hash(exe['fingerprint_basis'])!=EXEC_FP or exe['fingerprint_basis'].get('version')!='V1.1': raise ValueError('OOS execution contract mismatch')
    if src.get('fingerprint')!=SOURCE_CV_AUTH_FP or canonical_hash(src['fingerprint_basis'])!=SOURCE_CV_AUTH_FP: raise ValueError('source CV authorization mismatch')
    p=state['permissions']; req=['model_fit_allowed','oos_label_access_allowed','lockbox_label_access_allowed','live_signal_allowed','main_merge_allowed','authoritative_model_output_allowed']
    if any(p.get(k) is not False for k in req) or p.get('oos_execution_pr_creation_allowed') is not True or int(p.get('oos_label_bearing_execution_runs_remaining',-1))!=1: raise ValueError('accepted state permission mismatch')
    b=exe['fingerprint_basis']
    if b['authority']['oos_authorization_fingerprint']!=AUTH_FP or b['authority']['integration_base_sha']!='c484b6f8e0b404f790995274b768fdde3000bd8d': raise ValueError('execution authority mismatch')
    if b['execution_semantics']['economic_selection_population']!='ALL_PREDICTED_ROWS_ON_REBALANCE_DATE_BEFORE_ANY_LABEL_VALIDITY_FILTER' or b['metric_semantics']['bucket_size']!='CEIL_COVERAGE_TIMES_ALL_PREDICTION_ROWS_ON_REBALANCE_DATE': raise ValueError('economic selection semantics drift')
    if b['hard_boundaries']['fit'] or b['hard_boundaries']['lockbox_access'] or b['hard_boundaries']['main_merge']: raise ValueError('execution hard boundary drift')
    return exe,src

def validate_physical_boundary(a,src):
    root=Path(a.physical_boundary); c=json.loads(Path(a.boundary_contract).read_text(encoding='utf-8'))
    if c.get('fingerprint')!=BOUNDARY_FP or canonical_hash(c['fingerprint_basis'])!=BOUNDARY_FP or c.get('status')!='PRE_PREDICTION_PHYSICAL_OOS_BOUNDARY_COMPILER_NON_LABEL_NON_CONSUMING': raise ValueError('OOS physical boundary mismatch')
    b=c['fingerprint_basis']; s=b['scope']
    if b.get('oos_authorization_fingerprint')!=AUTH_FP or b.get('source_cv_authorization_fingerprint')!=SOURCE_CV_AUTH_FP or s['decision_start']!=OOS_START or s['decision_end']!=OOS_END or s['final_lockbox_start']!=LOCKBOX_START: raise ValueError('physical boundary authority/date mismatch')
    for k in ['oos_prediction_forbidden','oos_label_construction_forbidden','oos_label_value_read_forbidden','model_load_forbidden','authorization_consumption_forbidden','fit_retrain_tune_reselect_forbidden','final_lockbox_access_forbidden','business_metrics_forbidden']:
        if s.get(k) is not True: raise ValueError('physical boundary permission not closed: '+k)
    o=b['outputs']; expected={o[k] for k in ['features','market','execution_state','lifecycle','manifest','source_verification','independent_audit','hashes']}; have={p.name for p in root.iterdir() if p.is_file()}
    if have!=expected: raise ValueError(f'physical boundary file set mismatch expected={sorted(expected)} actual={sorted(have)}')
    hh=json.loads((root/o['hashes']).read_text(encoding='utf-8'))
    if set(hh)!=expected-{o['hashes']} or any(sha256_file(root/n)!=v for n,v in hh.items()): raise ValueError('physical boundary final hashes invalid')
    m=json.loads((root/o['manifest']).read_text(encoding='utf-8')); au=json.loads((root/o['independent_audit']).read_text(encoding='utf-8')); v=json.loads((root/o['source_verification']).read_text(encoding='utf-8'))
    if m.get('status')!='PHYSICALLY_OOS_ONLY_PRE_PREDICTION_NON_LABEL' or m.get('boundary_contract_fingerprint')!=BOUNDARY_FP or m.get('source_cv_authorization_fingerprint')!=SOURCE_CV_AUTH_FP or m.get('feature_columns')!=list(src['fingerprint_basis']['feature_columns']): raise ValueError('physical boundary manifest invalid')
    if au.get('pass') is not True or au.get('failed_checks')!=[] or au.get('boundary_contract_fingerprint')!=BOUNDARY_FP or int(au.get('post_oos_rows_observed',-1))!=0: raise ValueError('physical boundary independent audit invalid')
    for k in ['oos_prediction_executed','oos_label_constructed','oos_label_value_read','model_loaded','authorization_consumed','final_lockbox_accessed']:
        if au.get(k) is not False: raise ValueError('physical audit permission evidence not closed: '+k)
    if v.get('status')!='VERIFIED' or v.get('boundary_contract_fingerprint')!=BOUNDARY_FP: raise ValueError('physical source verification invalid')
    for k,exp in b['inputs'].items():
        got=v.get('artifacts',{}).get(k,{})
        if int(got.get('artifact_id',-1))!=int(exp['artifact_id']) or got.get('archive_sha256')!=exp['artifact_zip_sha256'] or got.get('verified') is not True: raise ValueError('physical source mismatch: '+k)
    if b['inputs']['feature_matrix']['file_sha256']!=SOURCE_MATRIX_SHA: raise ValueError('source matrix authority drift')
    g=m.get('guards',{})
    for k in ['broad_feature_matrix_available_downstream','broad_g3_available_downstream','broad_g4_available_downstream','raw_g5_available_downstream','raw_g2_available_downstream','oos_prediction_executed','oos_label_constructed','oos_label_value_read','model_loaded','authorization_consumed','fit_retrain_tune_reselect_executed','final_lockbox_accessed','business_metrics_computed']:
        if g.get(k) is not False: raise ValueError('physical manifest guard not closed: '+k)
    for k in ['post_oos_feature_rows','post_oos_market_rows','post_oos_execution_state_rows','post_oos_lifecycle_delist_rows']:
        if int(g.get(k,-1))!=0: raise ValueError('physical manifest guard nonzero: '+k)
    return {'root':root,'manifest':m,'features':root/o['features'],'market':root/o['market'],'execution_state':root/o['execution_state'],'lifecycle':root/o['lifecycle'],'manifest_path':root/o['manifest'],'audit_path':root/o['independent_audit']}

def runtime_check(exe):
    import duckdb,numpy as np,pandas as pd,pyarrow as pa,scipy,sklearn
    got={'python':sys.version.split()[0],'numpy':np.__version__,'scipy':scipy.__version__,'scikit_learn':sklearn.__version__,'pyarrow':pa.__version__,'duckdb':duckdb.__version__,'pandas':pd.__version__,'thread_env':{k:os.getenv(k) for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']}}
    if got!=exe['fingerprint_basis']['runtime']: raise ValueError(f'runtime mismatch: {got}')
    return got

def transform_frame(df,pre,src):
    import numpy as np
    features=list(pre['feature_columns']); expected=list(pre['model_input_feature_names']); stats=pre['continuous_stats']; levels=list(pre['regime_levels']); roles=src['fingerprint_basis']['feature_roles']; continuous=set(roles['continuous_clip_train_only']); binary=set(roles['binary_missing_indicators']); financial=set(roles['financial_signed_log1p']); cols=[]; names=[]
    for c in features:
        if c=='regime_state':
            s=df[c]
            for i,lev in enumerate(levels): cols.append((s.astype('string')==str(lev)).to_numpy(dtype=np.float32)); names.append(f'regime__{i}')
            u=s.isna()|~s.astype('string').isin([str(x) for x in levels]); cols.append(u.to_numpy(dtype=np.float32)); names.append('regime__unknown')
        elif c in binary:
            x=df[c].to_numpy(dtype=np.float64,na_value=np.nan)
            if np.isnan(x).any() or not np.isin(x,[0.,1.]).all(): raise ValueError('OOS binary violation: '+c)
            cols.append(x.astype(np.float32)); names.append(c)
        elif c in continuous:
            x=df[c].to_numpy(dtype=np.float64,na_value=np.nan)
            if c in financial: x=np.sign(x)*np.log1p(np.abs(x))
            st=stats[c]; x=np.where(np.isnan(x),np.nan,np.clip(x,float(st['q001']),float(st['q999']))); cols.append(x.astype(np.float32)); names.append(c)
        else: raise ValueError('unclassified feature '+c)
    if names!=expected: raise ValueError('transformed feature names drift')
    X=np.column_stack(cols).astype(np.float32,copy=False)
    if np.isinf(X).any(): raise ValueError('infinite transformed OOS feature')
    return X

def materialize_predictions(matrix,src,pre,model,bm,work,out,head):
    import duckdb,numpy as np,pyarrow as pa,pyarrow.parquet as pq
    con=duckdb.connect(); con.execute('PRAGMA threads=4'); con.execute("PRAGMA memory_limit='6GB'"); (work/'duckdb-pred-tmp').mkdir(parents=True,exist_ok=True); con.execute(f"PRAGMA temp_directory={q(str(work/'duckdb-pred-tmp'))}")
    raw=work/'oos_features_raw.parquet'; feat_sql=','.join(qi(c) for c in pre['feature_columns']); con.execute(f"COPY (SELECT CAST(trade_date AS DATE) trade_date,upper(CAST(exchange AS VARCHAR)) exchange,lpad(CAST(code AS VARCHAR),6,'0') code,{feat_sql} FROM read_parquet({q(str(matrix))}) ORDER BY trade_date,exchange,code) TO {q(str(raw))} (FORMAT PARQUET,COMPRESSION ZSTD)")
    rows,uniq,dmin,dmax=con.execute(f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date) FROM read_parquet({q(str(raw))})").fetchone()
    if rows<=0 or rows!=uniq or str(dmin)!=OOS_START or str(dmax)!=OOS_END or int(rows)!=int(bm['features']['row_count']): raise ValueError('OOS prediction population mismatch')
    writer=None; consumed=False; n=0; pp=out/'oos_predictions.parquet'
    try:
        for batch in pq.ParquetFile(raw).iter_batches(batch_size=100000):
            df=pa.Table.from_batches([batch]).to_pandas(); X=transform_frame(df,pre,src)
            if not consumed:
                payload={'schema_version':1,'status':'CONSUMED','authorization_fingerprint':AUTH_FP,'execution_contract_fingerprint':EXEC_FP,'physical_boundary_contract_fingerprint':BOUNDARY_FP,'execution_head':head,'consumption_event':'FIRST_OOS_PREDICTION_COMPUTATION','consumed_at_utc':datetime.now(timezone.utc).isoformat(),'oos_label_read_before_consumption':False,'lockbox_accessed':False,'fit_executed':False}; (out/'authorization_consumption.json').write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8'); consumed=True
            pred=np.asarray(model.predict(X),dtype=np.float64)
            if len(pred)!=len(df) or not np.isfinite(pred).all(): raise ValueError('invalid OOS predictions')
            t=pa.table({'trade_date':pa.array(df['trade_date']),'exchange':pa.array(df['exchange'].astype(str)),'code':pa.array(df['code'].astype(str)),'prediction':pa.array(pred)})
            if writer is None: writer=pq.ParquetWriter(pp,t.schema,compression='zstd')
            writer.write_table(t); n+=len(df); del df,X,pred,t; gc.collect()
    finally:
        if writer is not None: writer.close()
    if not consumed or n!=rows: raise ValueError('prediction/consumption mismatch')
    return {'prediction_rows':int(rows),'prediction_date_min':str(dmin),'prediction_date_max':str(dmax)}

def materialize_labels(matrix,market,lifecycle,bm,work):
    import duckdb
    con=duckdb.connect(); con.execute('PRAGMA threads=4'); con.execute("PRAGMA memory_limit='7GB'"); (work/'duckdb-label-tmp').mkdir(parents=True,exist_ok=True); con.execute(f"PRAGMA temp_directory={q(str(work/'duckdb-label-tmp'))}")
    con.execute(f"CREATE TEMP TABLE market AS SELECT upper(CAST(exchange AS VARCHAR)) exchange,lpad(CAST(code AS VARCHAR),6,'0') code,CAST(trade_date AS DATE) trade_date,CAST(open AS DOUBLE) open,CAST(close AS DOUBLE) close,CAST(factor AS DOUBLE) factor FROM read_parquet({q(str(market))})")
    mr,mn,mx=con.execute('SELECT count(*),min(trade_date),max(trade_date) FROM market').fetchone()
    if mr<=0 or str(mn)!=OOS_START or str(mx)!=OOS_END or str(mx)>=LOCKBOX_START or int(mr)!=int(bm['market']['row_count']): raise ValueError('market boundary mismatch')
    con.execute(f"CREATE TEMP TABLE lifecycle AS SELECT upper(CAST(exchange AS VARCHAR)) exchange,lpad(CAST(code AS VARCHAR),6,'0') code,CAST(listed_from AS DATE) listed_from,CAST(listed_to_exclusive AS DATE) listed_to_exclusive FROM read_parquet({q(str(lifecycle))})")
    if con.execute(f"SELECT count(*) FROM lifecycle WHERE listed_to_exclusive IS NOT NULL AND listed_to_exclusive>DATE '{OOS_END}'").fetchone()[0]: raise ValueError('lifecycle contains post-OOS information')
    con.execute(f"CREATE TEMP TABLE decisions AS SELECT CAST(trade_date AS DATE) decision_date,upper(CAST(exchange AS VARCHAR)) exchange,lpad(CAST(code AS VARCHAR),6,'0') code FROM read_parquet({q(str(matrix))})")
    dr,du,dn,dx=con.execute('SELECT count(*),count(DISTINCT (decision_date,exchange,code)),min(decision_date),max(decision_date) FROM decisions').fetchone()
    if dr!=du or str(dn)!=OOS_START or str(dx)!=OOS_END or int(dr)!=int(bm['features']['row_count']): raise ValueError('decision population mismatch')
    con.execute('CREATE TEMP TABLE calendar AS SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 session_idx FROM (SELECT DISTINCT trade_date FROM market) ORDER BY trade_date')
    con.execute('CREATE TEMP TABLE schedule AS SELECT d.*,c.session_idx,e.trade_date entry_date,x5.trade_date exit_date_5d,x20.trade_date exit_date_20d FROM decisions d JOIN calendar c ON c.trade_date=d.decision_date LEFT JOIN calendar e ON e.session_idx=c.session_idx+1 LEFT JOIN calendar x5 ON x5.session_idx=c.session_idx+5 LEFT JOIN calendar x20 ON x20.session_idx=c.session_idx+20')
    con.execute(f"""CREATE TEMP TABLE raw_labels AS SELECT s.decision_date,s.exchange,s.code,s.entry_date,s.exit_date_5d,s.exit_date_20d,ep.open entry_open_raw,ep.factor entry_factor,p5.close exit_close_5d_raw,p5.factor exit_factor_5d,p20.close exit_close_20d_raw,p20.factor exit_factor_20d,lc.listed_to_exclusive,
      CASE WHEN s.exit_date_5d IS NULL THEN 'PARTITION_BOUNDARY_INCOMPLETE_HORIZON' WHEN lc.listed_to_exclusive IS NOT NULL AND lc.listed_to_exclusive>s.decision_date AND lc.listed_to_exclusive<=s.exit_date_5d THEN 'DELISTING_HORIZON_CENSOR_NO_TERMINAL_IMPUTATION' WHEN ep.open IS NULL OR ep.open<=0 THEN 'MISSING_ENTRY_OPEN' WHEN p5.close IS NULL OR p5.close<=0 THEN 'MISSING_EXIT_CLOSE' ELSE 'VALID' END censor_reason_5d,
      CASE WHEN s.exit_date_20d IS NULL OR s.decision_date>DATE '{LATEST_VALID20}' THEN 'PARTITION_BOUNDARY_INCOMPLETE_HORIZON' WHEN lc.listed_to_exclusive IS NOT NULL AND lc.listed_to_exclusive>s.decision_date AND lc.listed_to_exclusive<=s.exit_date_20d THEN 'DELISTING_HORIZON_CENSOR_NO_TERMINAL_IMPUTATION' WHEN ep.open IS NULL OR ep.open<=0 THEN 'MISSING_ENTRY_OPEN' WHEN p20.close IS NULL OR p20.close<=0 THEN 'MISSING_EXIT_CLOSE' ELSE 'VALID' END censor_reason_20d
      FROM schedule s LEFT JOIN market ep ON ep.exchange=s.exchange AND ep.code=s.code AND ep.trade_date=s.entry_date LEFT JOIN market p5 ON p5.exchange=s.exchange AND p5.code=s.code AND p5.trade_date=s.exit_date_5d LEFT JOIN market p20 ON p20.exchange=s.exchange AND p20.code=s.code AND p20.trade_date=s.exit_date_20d LEFT JOIN lifecycle lc ON lc.exchange=s.exchange AND lc.code=s.code AND s.decision_date>=lc.listed_from AND (lc.listed_to_exclusive IS NULL OR s.decision_date<lc.listed_to_exclusive)""")
    con.execute("CREATE TEMP TABLE stock_returns AS SELECT *,CASE WHEN censor_reason_5d='VALID' THEN (exit_close_5d_raw*exit_factor_5d)/(entry_open_raw*entry_factor)-1 END stock_total_return_5d,CASE WHEN censor_reason_20d='VALID' THEN (exit_close_20d_raw*exit_factor_20d)/(entry_open_raw*entry_factor)-1 END stock_total_return_20d FROM raw_labels")
    con.execute("CREATE TEMP TABLE benchmarks AS SELECT decision_date,avg(stock_total_return_5d) FILTER(WHERE censor_reason_5d='VALID') benchmark_return_5d,avg(stock_total_return_20d) FILTER(WHERE censor_reason_20d='VALID') benchmark_return_20d FROM stock_returns GROUP BY decision_date")
    lp=work/'oos_labels.parquet'; con.execute(f"COPY (SELECT r.decision_date trade_date,r.exchange,r.code,r.entry_date,r.exit_date_5d,r.exit_date_20d,r.censor_reason_5d='VALID' valid_label_5d,r.censor_reason_20d='VALID' valid_label_20d,r.censor_reason_5d,r.censor_reason_20d,r.stock_total_return_5d,b.benchmark_return_5d,CASE WHEN r.censor_reason_5d='VALID' THEN r.stock_total_return_5d-b.benchmark_return_5d END excess_return_5d,r.stock_total_return_20d,b.benchmark_return_20d,CASE WHEN r.censor_reason_20d='VALID' THEN r.stock_total_return_20d-b.benchmark_return_20d END excess_return_20d FROM stock_returns r JOIN benchmarks b USING(decision_date) ORDER BY trade_date,exchange,code) TO {q(str(lp))} (FORMAT PARQUET,COMPRESSION ZSTD)")
    rows,uniq,v20,mv,me=con.execute(f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),count(*) FILTER(WHERE valid_label_20d),max(trade_date) FILTER(WHERE valid_label_20d),max(exit_date_20d) FILTER(WHERE valid_label_20d) FROM read_parquet({q(str(lp))})").fetchone()
    if rows!=dr or uniq!=dr or str(mv)>LATEST_VALID20 or str(me)>OOS_END: raise ValueError('OOS label boundary mismatch')
    return {'label_rows':int(rows),'valid_20d_rows':int(v20),'latest_valid_20d_decision':str(mv),'latest_valid_20d_exit':str(me),'market_source_kind':'SEALED_PHYSICAL_OOS_BOUNDARY','market_source_rows':int(mr),'market_source_min_date':str(mn),'market_source_max_date':str(mx)}

def evaluate(a,work,out,exe):
    import duckdb,numpy as np,pandas as pd,pyarrow as pa,pyarrow.parquet as pq
    from scipy.stats import spearmanr
    con=duckdb.connect(); con.execute('PRAGMA threads=4'); con.execute("PRAGMA memory_limit='7GB'"); (work/'duckdb-eval-tmp').mkdir(parents=True,exist_ok=True); con.execute(f"PRAGMA temp_directory={q(str(work/'duckdb-eval-tmp'))}")
    pred=out/'oos_predictions.parquet'; labels=work/'oos_labels.parquet'; allp=work/'oos_all_economic_rows.parquet'; icp=work/'oos_evaluation_rows.parquet'
    con.execute(f"COPY (SELECT p.trade_date,p.exchange,p.code,p.prediction,l.valid_label_20d,l.censor_reason_20d,l.entry_date,l.exit_date_20d,l.excess_return_20d,l.stock_total_return_20d,l.benchmark_return_20d FROM read_parquet({q(str(pred))}) p JOIN read_parquet({q(str(labels))}) l USING(trade_date,exchange,code) WHERE p.trade_date<=DATE '{LATEST_VALID20}' ORDER BY p.trade_date,p.exchange,p.code) TO {q(str(allp))} (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.execute(f"COPY (SELECT trade_date,exchange,code,prediction,entry_date,exit_date_20d,excess_return_20d,stock_total_return_20d,benchmark_return_20d FROM read_parquet({q(str(allp))}) WHERE valid_label_20d ORDER BY trade_date,exchange,code) TO {q(str(icp))} (FORMAT PARQUET,COMPRESSION ZSTD)")
    er,emin,emax=con.execute(f"SELECT count(*),min(trade_date),max(trade_date) FROM read_parquet({q(str(icp))})").fetchone();
    if er<=0 or str(emax)>LATEST_VALID20: raise ValueError('invalid IC population')
    df=pq.read_table(icp).to_pandas(); df['trade_date']=pd.to_datetime(df['trade_date']).dt.date; daily=[]
    for d,g in df.groupby('trade_date',sort=True):
        p=g['prediction'].to_numpy(dtype=float); y=g['excess_return_20d'].to_numpy(dtype=float); ok=np.isfinite(p)&np.isfinite(y); ic=None
        if int(ok.sum())>=20 and np.unique(p[ok]).size>1 and np.unique(y[ok]).size>1: ic=float(spearmanr(p[ok],y[ok]).statistic)
        daily.append({'trade_date':str(d),'n20':int(ok.sum()),'daily_ic_20d':ic})
    vd=[r for r in daily if r['daily_ic_20d'] is not None and math.isfinite(r['daily_ic_20d'])]; ics=np.asarray([r['daily_ic_20d'] for r in vd],dtype=np.float64)
    if not len(ics): raise ValueError('no valid daily IC')
    mean=float(ics.mean()); lo,hi=moving_block_bootstrap_mean_ci(ics); ddf=pd.DataFrame(vd); ddf['period']=pd.PeriodIndex(pd.to_datetime(ddf['trade_date']),freq='Q').astype(str); qmeans=ddf.groupby('period',sort=True)['daily_ic_20d'].mean().to_dict(); expected=exe['fingerprint_basis']['metric_semantics']['expected_quarters']; qr=[]
    for qq in expected:
        v=qmeans.get(qq); qr.append({'quarter':qq,'mean_daily_ic_20d':None if v is None else float(v),'positive':bool(v is not None and v>0)})
    pq.write_table(pa.Table.from_pylist(daily),out/'oos_daily_metrics.parquet',compression='zstd'); pos=sum(r['positive'] for r in qr); (out/'oos_quarter_metrics.json').write_text(json.dumps({'schema_version':1,'expected_quarters':expected,'positive_quarter_count':pos,'quarters':qr},indent=2)+'\n',encoding='utf-8')
    alldf=pq.read_table(allp).to_pandas(); alldf['trade_date']=pd.to_datetime(alldf['trade_date']).dt.date; alldf['trade_date_str']=alldf['trade_date'].astype(str); dates=sorted(alldf['trade_date_str'].unique().tolist());
    if not dates or dates[0]!=OOS_START: raise ValueError('rebalance anchor missing')
    rebalances=dates[::20]; econ={'selection_population':'ALL_PREDICTED_ROWS_BEFORE_LABEL_VALIDITY_FILTER','selected_invalid_label_action':'FAIL_CLOSED_NO_BACKFILL_NO_POST_SELECTION_DROP','rebalance_anchor':OOS_START,'rebalance_every_sessions':20,'rebalance_dates':rebalances,'coverages':{}}
    for cov in [.05,.10,.20]:
        cohorts=[]; valid=True
        for d in rebalances:
            g=alldf[alldf['trade_date_str']==d].copy(); g.sort_values(['prediction','exchange','code'],ascending=[False,True,True],kind='mergesort',inplace=True); k=max(1,int(math.ceil(cov*len(g)))); top=g.iloc[:k].copy(); mask=top['valid_label_20d'].fillna(False).astype(bool)&np.isfinite(top['excess_return_20d'].to_numpy(dtype=float,na_value=np.nan)); invalid=int((~mask).sum()); r={'decision_date':d,'eligible_prediction_rows':int(len(g)),'selected_rows':k,'selected_invalid_20d_rows':invalid,'cohort_valid':invalid==0}
            if invalid: valid=False; r.update({'entry_date':None,'exit_date':None,'gross_excess_return_20d':None,'roundtrip_cost':None,'net_excess_return_20d':None})
            else:
                entry=sorted({str(x) for x in top['entry_date']}); exitd=sorted({str(x) for x in top['exit_date_20d']});
                if len(entry)!=1 or len(exitd)!=1: raise ValueError('cohort dates not common')
                gross=float(top['excess_return_20d'].mean()); cost=cohort_roundtrip_cost(entry[0],exitd[0]); r.update({'entry_date':entry[0],'exit_date':exitd[0],'gross_excess_return_20d':gross,'roundtrip_cost':cost,'net_excess_return_20d':gross-cost})
            cohorts.append(r)
        agg=None if not valid else float(np.mean([x['net_excess_return_20d'] for x in cohorts])); econ['coverages'][f'{int(cov*100):02d}pct']={'coverage_valid':valid,'aggregate_net_excess_return_20d':agg,'cohort_count':len(cohorts),'cohorts':cohorts}
    c05=econ['coverages']['05pct']; c10=econ['coverages']['10pct']; c20=econ['coverages']['20pct']; checks={'mean_daily_spearman_ic_20d_gt_0':mean>0,'block_bootstrap_95pct_ci_lower_bound_mean_daily_ic_20d_gt_0':lo>0,'positive_mean_ic_in_at_least_6_of_8_calendar_quarters':pos>=6 and len(qr)==8 and all(r['mean_daily_ic_20d'] is not None for r in qr),'top_10pct_net_excess_return_20d_at_15bps_per_side_gt_0':c10['coverage_valid'] and c10['aggregate_net_excess_return_20d']>0,'no_sign_inversion_5pct_or_20pct_coverage':c05['coverage_valid'] and c20['coverage_valid'] and c05['aggregate_net_excess_return_20d']>=0 and c20['aggregate_net_excess_return_20d']>=0,'pbo_le_0_20_carried_from_development':.11904761904761904<=.2,'dsr_ge_0_95_carried_from_development':.9999989891602007>=.95}; gp=all(checks.values()); econ['cost_semantics']=exe['fingerprint_basis']['metric_semantics']; (out/'oos_economic_metrics.json').write_text(json.dumps(econ,indent=2)+'\n',encoding='utf-8'); (out/'oos_gate_result.json').write_text(json.dumps({'schema_version':1,'status':'PASS' if gp else 'FAIL','mean_daily_ic_20d':mean,'bootstrap_95pct_ci':{'lower':lo,'upper':hi},'positive_quarters':pos,'checks':checks,'gate_logic':'ALL_REQUIRED_MUST_PASS','oos_failure_action':'NO_PROMOTION_NO_RETUNING_ON_OOS','final_lockbox_open_allowed':False},indent=2)+'\n',encoding='utf-8')
    return {'evaluation_rows':int(er),'evaluation_date_min':str(emin),'evaluation_date_max':str(emax),'valid_daily_ic_days':len(vd),'mean_daily_ic_20d':mean,'bootstrap_ci_lower':lo,'bootstrap_ci_upper':hi,'positive_quarters':pos,'economic_05pct_coverage_valid':c05['coverage_valid'],'economic_10pct_coverage_valid':c10['coverage_valid'],'economic_20pct_coverage_valid':c20['coverage_valid'],'gate_pass':gp}

def main():
    if '--synthetic-self-test' in sys.argv: return synthetic_self_test()
    ap=argparse.ArgumentParser()
    for n in ['physical-boundary','boundary-contract','model','preprocess','authorization','execution-contract','source-cv-authorization','accepted-state','work-dir','out','execution-head']: ap.add_argument('--'+n,required=True)
    a=ap.parse_args(); exe,src=validate_authority(a); runtime=runtime_check(exe)
    if not re.fullmatch(r'[0-9a-f]{40}',a.execution_head) or os.environ.get('EXECUTION_HEAD')!=a.execution_head: raise ValueError('exact execution head mismatch')
    physical=validate_physical_boundary(a,src)
    if sha256_file(Path(a.model))!=MODEL_SHA or sha256_file(Path(a.preprocess))!=PREPROCESS_SHA: raise ValueError('frozen model/preprocess hash mismatch')
    pre=json.loads(Path(a.preprocess).read_text(encoding='utf-8'))
    if pre.get('oos_rows_used') is not False or pre.get('lockbox_rows_used') is not False or pre.get('fit_rows')!=5103016 or pre.get('model_input_feature_count')!=45 or list(pre.get('feature_columns',[]))!=list(physical['manifest']['feature_columns']): raise ValueError('frozen preprocess identity drift')
    with Path(a.model).open('rb') as f: model=pickle.load(f)
    if int(getattr(model,'n_features_in_',-1))!=45: raise ValueError('frozen model feature count mismatch')
    work=Path(a.work_dir); out=Path(a.out); work.mkdir(parents=True,exist_ok=True); out.mkdir(parents=True,exist_ok=True)
    pred=materialize_predictions(physical['features'],src,pre,model,physical['manifest'],work,out,a.execution_head); labels=materialize_labels(physical['features'],physical['market'],physical['lifecycle'],physical['manifest'],work); ev=evaluate(a,work,out,exe); cons=json.loads((out/'authorization_consumption.json').read_text(encoding='utf-8'))
    manifest={'schema_version':2,'gate':'STAGE4_ALPHA_V1_OOS_VALIDATION_SINGLE_USE_EXECUTION','execution_head':a.execution_head,'authorization_fingerprint':AUTH_FP,'execution_contract_fingerprint':EXEC_FP,'physical_boundary_contract_fingerprint':BOUNDARY_FP,'authorization_consumed':True,'consumption_event':cons['consumption_event'],'runtime':runtime,'model_sha256':sha256_file(Path(a.model)),'preprocess_manifest_sha256':sha256_file(Path(a.preprocess)),'source_feature_matrix_sha256':SOURCE_MATRIX_SHA,'physical_oos_features_sha256':sha256_file(physical['features']),'physical_oos_market_sha256':sha256_file(physical['market']),'physical_oos_execution_state_sha256':sha256_file(physical['execution_state']),'physical_oos_lifecycle_sha256':sha256_file(physical['lifecycle']),'physical_boundary_manifest_sha256':sha256_file(physical['manifest_path']),'physical_boundary_independent_audit_sha256':sha256_file(physical['audit_path']),'broad_source_inputs_available_in_execution_runner':False,**pred,**labels,**ev,'fit_executed':False,'retraining_executed':False,'hyperparameter_search_executed':False,'candidate_reselection_executed':False,'oos_fitted_preprocessor':False,'economic_label_validity_lookahead':False,'oos_accessed':True,'lockbox_accessed':False,'live_signal_allowed':False,'authoritative_model_output':False,'main_merge_allowed':False,'next_gate_if_pass':'SEPARATE_OOS_EVIDENCE_ACCEPTANCE_THEN_SEPARATE_LOCKBOX_AUTHORIZATION','next_gate_if_fail':'REGISTER_OOS_FAILURE_NO_PROMOTION_NO_RETUNING'}
    (out/'oos_execution_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8'); req=['oos_execution_manifest.json','oos_predictions.parquet','oos_daily_metrics.parquet','oos_quarter_metrics.json','oos_economic_metrics.json','oos_gate_result.json','authorization_consumption.json']; (out/'artifact_hashes.json').write_text(json.dumps({n:sha256_file(out/n) for n in req},sort_keys=True,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'execution_head':a.execution_head,'physical_boundary_contract':BOUNDARY_FP,'broad_source_inputs_available_in_execution_runner':False,'authorization_consumed':True,'prediction_rows':pred['prediction_rows'],'valid_20d_rows':labels['valid_20d_rows'],'mean_daily_ic_20d':ev['mean_daily_ic_20d'],'positive_quarters':ev['positive_quarters'],'economic_coverage_valid':{'05pct':ev['economic_05pct_coverage_valid'],'10pct':ev['economic_10pct_coverage_valid'],'20pct':ev['economic_20pct_coverage_valid']},'gate_pass':ev['gate_pass'],'lockbox_accessed':False,'fit_executed':False},indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
