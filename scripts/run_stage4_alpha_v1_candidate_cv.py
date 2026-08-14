#!/usr/bin/env python3
from __future__ import annotations

import argparse, gc, hashlib, json, math, os, time, warnings
from pathlib import Path


def q(s: str) -> str: return "'" + s.replace("'", "''") + "'"
def qi(s: str) -> str: return '"' + s.replace('"','""') + '"'
def canon_hash(x: object) -> str: return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def sha256_file(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--candidate-id',required=True); ap.add_argument('--prepared',required=True); ap.add_argument('--preprocess',required=True); ap.add_argument('--authorization',required=True); ap.add_argument('--execution-contract',required=True); ap.add_argument('--out',required=True)
    args=ap.parse_args()
    import duckdb, numpy as np, pyarrow as pa, pyarrow.parquet as pq, scipy, sklearn
    from scipy.stats import spearmanr
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.preprocessing import StandardScaler

    auth=json.loads(Path(args.authorization).read_text(encoding='utf-8')); exe=json.loads(Path(args.execution_contract).read_text(encoding='utf-8')); prep=json.loads(Path(args.preprocess).read_text(encoding='utf-8'))
    if auth['fingerprint']!='2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c': raise ValueError('authorization mismatch')
    if exe['fingerprint']!='9b449b9c12ac98f1516812dfa4d3f40922668e35462087637cea79e81c1645dc': raise ValueError('execution mismatch')
    if prep['authorization_fingerprint']!=auth['fingerprint'] or prep['execution_fingerprint']!=exe['fingerprint']: raise ValueError('prepared data not bound to execution')
    candidates={c['candidate_id']:c for c in auth['fingerprint_basis']['candidate_catalog']}; cid=args.candidate_id
    if cid not in candidates: raise ValueError(f'unknown candidate {cid}')
    spec=candidates[cid]; family=spec['family']; params=spec['params']
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True); prepared=Path(args.prepared)

    runtime={'python':os.sys.version.split()[0],'numpy':np.__version__,'scipy':scipy.__version__,'scikit_learn':sklearn.__version__,'pyarrow':pa.__version__,'duckdb':duckdb.__version__,'threads':{k:os.getenv(k) for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']}}
    expected=auth['fingerprint_basis']['runtime']
    if not (runtime['python']==expected['python'] and runtime['numpy']==expected['numpy'] and runtime['scipy']==expected['scipy'] and runtime['scikit_learn']==expected['scikit_learn'] and runtime['pyarrow']==expected['pyarrow'] and runtime['duckdb']==expected['duckdb']): raise ValueError(f'runtime mismatch {runtime}')
    (out/'runtime_manifest.json').write_text(json.dumps(runtime,indent=2)+'\n',encoding='utf-8')

    features=auth['fingerprint_basis']['feature_columns']; roles=auth['fingerprint_basis']['feature_roles']; continuous=set(roles['continuous_clip_train_only']); binary=set(roles['binary_missing_indicators']); financial=set(roles['financial_signed_log1p']); split_map={int(s['split_id']):s for s in prep['splits']}
    con=duckdb.connect(); con.execute("PRAGMA threads=4"); con.execute("PRAGMA memory_limit='7GB'"); con.execute("PRAGMA temp_directory='build/duckdb-candidate-tmp'")

    def xbase(c: str) -> str:
        z=qi(c); return f"CASE WHEN {z} IS NULL THEN NULL ELSE sign(CAST({z} AS DOUBLE))*ln(1+abs(CAST({z} AS DOUBLE))) END" if c in financial else f"CAST({z} AS DOUBLE)"
    def feature_sql(s: dict, ridge: bool) -> tuple[list[str],list[str]]:
        stats=s['continuous_train_stats']; levels=s['regime_levels_train']; exprs=[]; names=[]
        for c in features:
            if c=='regime_state':
                for i,lev in enumerate(levels): exprs.append(f"CASE WHEN CAST(regime_state AS VARCHAR)={q(str(lev))} THEN 1.0 ELSE 0.0 END"); names.append(f'regime__{i}')
                known=','.join(q(str(x)) for x in levels); exprs.append("CASE WHEN regime_state IS NULL THEN 1.0 ELSE 0.0 END" if not levels else f"CASE WHEN regime_state IS NULL OR CAST(regime_state AS VARCHAR) NOT IN ({known}) THEN 1.0 ELSE 0.0 END"); names.append('regime__unknown')
            elif c in binary: exprs.append(f"CAST({qi(c)} AS DOUBLE)"); names.append(c)
            elif c in continuous:
                st=stats[c]; lo=st['q001']; hi=st['q999']; med=st['median']; e=xbase(c); clipped=f"CASE WHEN {e} IS NULL THEN NULL WHEN {e}<{repr(lo)} THEN {repr(lo)} WHEN {e}>{repr(hi)} THEN {repr(hi)} ELSE {e} END"; exprs.append(f"coalesce({clipped},{repr(med)})" if ridge else clipped); names.append(c)
            else: raise ValueError(f'unclassified feature {c}')
        return exprs,names
    def table_to_xy(table: pa.Table, feature_names: list[str], include_keys: bool):
        n=table.num_rows; X=np.empty((n,len(feature_names)),dtype=np.float32)
        for j,nm in enumerate(feature_names): X[:,j]=np.asarray(table.column(nm).combine_chunks().to_numpy(zero_copy_only=False),dtype=np.float32)
        y20=np.asarray(table.column('excess_return_20d').combine_chunks().to_numpy(zero_copy_only=False),dtype=np.float32)
        if not np.isfinite(y20).all(): raise ValueError('nonfinite primary target')
        if not include_keys: return X,y20
        dates=np.asarray(table.column('trade_date').combine_chunks().to_numpy(zero_copy_only=False)); exchanges=np.asarray(table.column('exchange').combine_chunks().to_pylist(),dtype=object); codes=np.asarray(table.column('code').combine_chunks().to_pylist(),dtype=object); y5=np.asarray(table.column('excess_return_5d').combine_chunks().to_numpy(zero_copy_only=False),dtype=np.float32); stock20=np.asarray(table.column('stock_total_return_20d').combine_chunks().to_numpy(zero_copy_only=False),dtype=np.float32); bench20=np.asarray(table.column('benchmark_return_20d').combine_chunks().to_numpy(zero_copy_only=False),dtype=np.float32)
        return X,y20,dates,exchanges,codes,y5,stock20,bench20

    trial_log=[]; split_metrics=[]; daily_rows=[]; preprocess_manifest={'candidate_id':cid,'family':family,'splits':[]}; oof_path=out/'oof_predictions.parquet'; writer=None
    try:
        for sid in range(1,6):
            s=split_map[sid]; ridge=family=='RIDGE_V1'; exprs,names=feature_sql(s,ridge); select_features=', '.join(f"{e} AS {qi(n)}" for e,n in zip(exprs,names))
            train_sql=f"SELECT {select_features}, CAST(excess_return_20d AS DOUBLE) AS excess_return_20d FROM read_parquet({q(str(prepared))}) WHERE valid_label_20d AND trade_date BETWEEN DATE {q(s['train_start'])} AND DATE {q(s['train_end'])} ORDER BY trade_date,exchange,code"; test_sql=f"SELECT trade_date,exchange,code,{select_features},CAST(excess_return_20d AS DOUBLE) AS excess_return_20d,CAST(excess_return_5d AS DOUBLE) AS excess_return_5d,CAST(stock_total_return_20d AS DOUBLE) AS stock_total_return_20d,CAST(benchmark_return_20d AS DOUBLE) AS benchmark_return_20d FROM read_parquet({q(str(prepared))}) WHERE valid_label_20d AND trade_date BETWEEN DATE {q(s['test_start'])} AND DATE {q(s['test_end'])} ORDER BY trade_date,exchange,code"
            train_t=con.execute(train_sql).fetch_arrow_table(); test_t=con.execute(test_sql).fetch_arrow_table()
            if train_t.num_rows!=s['train_rows_valid20'] or test_t.num_rows!=s['test_rows_valid20']: raise ValueError(f'row drift split {sid}')
            Xtr,ytr=table_to_xy(train_t,names,False); Xte,yte,dates,exchanges,codes,y5,stock20,bench20=table_to_xy(test_t,names,True); del train_t,test_t; gc.collect(); scaler_info=None
            if ridge:
                if not np.isfinite(Xtr).all() or not np.isfinite(Xte).all(): raise ValueError(f'Ridge nonfinite feature after imputation split {sid}')
                scaler=StandardScaler(copy=False); Xtr=scaler.fit_transform(Xtr); Xte=scaler.transform(Xte); scaler_info={'mean':[float(x) for x in scaler.mean_],'scale':[float(x) for x in scaler.scale_],'mean_scale_sha256':canon_hash({'mean':[float(x) for x in scaler.mean_],'scale':[float(x) for x in scaler.scale_]})}
            start=time.monotonic(); fit_error=None; warn=[]; model=None
            try:
                with warnings.catch_warnings(record=True) as ws:
                    warnings.simplefilter('always'); model=Ridge(alpha=params['alpha'],solver=params['solver'],tol=params['tol']) if ridge else HistGradientBoostingRegressor(**params); model.fit(Xtr,ytr); pred=np.asarray(model.predict(Xte),dtype=np.float64); warn=[f"{w.category.__name__}:{w.message}" for w in ws]
                if pred.shape[0]!=Xte.shape[0] or not np.isfinite(pred).all(): raise ValueError('invalid predictions')
            except Exception as e: fit_error=f'{type(e).__name__}:{e}'; pred=None
            elapsed=time.monotonic()-start; trial={'candidate_id':cid,'split_id':sid,'status':'SUCCESS' if fit_error is None else 'FIT_FAILED','fit_error':fit_error,'fit_seconds':elapsed,'train_rows':int(Xtr.shape[0]),'test_rows':int(Xte.shape[0]),'model_input_features':int(Xtr.shape[1]),'warnings':warn,'preprocess_stats_sha256':s['stats_sha256']}; trial_log.append(trial); preprocess_manifest['splits'].append({'split_id':sid,'regime_levels_train':s['regime_levels_train'],'continuous_stats_sha256':s['stats_sha256'],'ridge_scaler':scaler_info,'model_input_feature_names':names,'model_input_feature_count':len(names)})
            if fit_error is not None: del Xtr,Xte,ytr,yte,dates,exchanges,codes,y5,stock20,bench20,model; gc.collect(); continue
            uniq,idx,cnts=np.unique(dates,return_index=True,return_counts=True); valid_ic20=0; ics20=[]; ics5=[]
            for sess_i,(d,i0,n) in enumerate(zip(uniq,idx,cnts)):
                sl=slice(int(i0),int(i0+n)); p=pred[sl]; a=yte[sl].astype(float); b=y5[sl].astype(float); m20=np.isfinite(p)&np.isfinite(a); ic20=None
                if int(m20.sum())>=20 and np.unique(p[m20]).size>1 and np.unique(a[m20]).size>1: ic20=float(spearmanr(p[m20],a[m20]).statistic); valid_ic20+=1; ics20.append(ic20)
                m5=np.isfinite(p)&np.isfinite(b); ic5=None
                if int(m5.sum())>=20 and np.unique(p[m5]).size>1 and np.unique(b[m5]).size>1: ic5=float(spearmanr(p[m5],b[m5]).statistic); ics5.append(ic5)
                order=np.argsort(-p,kind='stable'); k=max(1,int(math.ceil(0.10*len(order)))); top=order[:k]
                daily_rows.append({'candidate_id':cid,'split_id':sid,'trade_date':str(d)[:10],'test_session_index_within_split':sess_i,'n20':int(m20.sum()),'daily_ic_20d':ic20,'n5':int(m5.sum()),'daily_ic_5d':ic5,'top10_n':k,'top10_gross_excess_20d':float(np.mean(a[top])),'top10_stock_total_return_20d':float(np.mean(stock20[sl][top].astype(float))),'benchmark_return_20d':float(np.mean(bench20[sl][top].astype(float)))})
            valid_fraction=valid_ic20/len(uniq); split_valid=valid_fraction>=0.90 and len(ics20)>0; split_metrics.append({'candidate_id':cid,'split_id':sid,'split_valid':split_valid,'test_days':len(uniq),'nonnull_ic20_days':valid_ic20,'nonnull_ic20_fraction':valid_fraction,'mean_daily_ic_20d':float(np.mean(ics20)) if ics20 else None,'mean_daily_ic_5d':float(np.mean(ics5)) if ics5 else None})
            tbl=pa.table({'trade_date':pa.array(dates),'exchange':pa.array(exchanges.tolist()),'code':pa.array(codes.tolist()),'split_id':pa.array(np.full(len(pred),sid,dtype=np.int8)),'prediction':pa.array(pred.astype(np.float32)),'excess_return_20d':pa.array(yte),'excess_return_5d':pa.array(y5),'stock_total_return_20d':pa.array(stock20),'benchmark_return_20d':pa.array(bench20)}); writer=pq.ParquetWriter(oof_path,tbl.schema,compression='zstd') if writer is None else writer; writer.write_table(tbl); del Xtr,Xte,ytr,yte,pred,dates,exchanges,codes,y5,stock20,bench20,model,tbl; gc.collect()
    finally:
        if writer is not None: writer.close()
    candidate_valid=len(trial_log)==5 and all(t['status']=='SUCCESS' for t in trial_log) and len(split_metrics)==5 and all(s['split_valid'] for s in split_metrics); means=[s['mean_daily_ic_20d'] for s in split_metrics if s['mean_daily_ic_20d'] is not None]; primary=float(np.median(means)) if candidate_valid else None; worst=float(np.min(means)) if candidate_valid else None; complexity=0 if family=='RIDGE_V1' else (10 if params['max_leaf_nodes']==15 else 20)
    summary={'candidate_id':cid,'ordinal':spec['ordinal'],'family':family,'params':params,'candidate_valid':candidate_valid,'primary_median_split_mean_daily_ic_20d':primary,'worst_split_mean_daily_ic_20d':worst,'complexity_rank':complexity,'successful_trials':sum(t['status']=='SUCCESS' for t in trial_log),'required_trials':5,'oof_rows':sum(t['test_rows'] for t in trial_log if t['status']=='SUCCESS'),'model_final_refit_executed':False,'oos_accessed':False,'lockbox_accessed':False}; (out/'trial_log.json').write_text(json.dumps(trial_log,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); (out/'split_metrics.json').write_text(json.dumps(split_metrics,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); (out/'preprocess_manifest.json').write_text(json.dumps(preprocess_manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); (out/'candidate_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); pq.write_table(pa.Table.from_pylist(daily_rows),out/'daily_metrics.parquet',compression='zstd'); hashes={p.name:sha256_file(p) for p in out.iterdir() if p.is_file()}; (out/'artifact_hashes.json').write_text(json.dumps(hashes,sort_keys=True,indent=2)+'\n',encoding='utf-8'); print(json.dumps(summary,ensure_ascii=False,indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
