#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def qi(s: str) -> str:
    return '"' + s.replace('"','""') + '"'


def sha256_file(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def canonical_hash(x: object) -> str:
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--matrix',required=True); ap.add_argument('--labels',required=True); ap.add_argument('--split-seal',required=True)
    ap.add_argument('--authorization',required=True); ap.add_argument('--execution-contract',required=True); ap.add_argument('--out',required=True)
    args=ap.parse_args()
    import duckdb

    auth=json.loads(Path(args.authorization).read_text(encoding='utf-8'))
    exe=json.loads(Path(args.execution_contract).read_text(encoding='utf-8'))
    if auth['fingerprint']!='2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c': raise ValueError('authorization fingerprint mismatch')
    if exe['fingerprint']!='9b449b9c12ac98f1516812dfa4d3f40922668e35462087637cea79e81c1645dc': raise ValueError('execution fingerprint mismatch')
    if exe['fingerprint_basis']['authorization_fingerprint']!=auth['fingerprint']: raise ValueError('execution is not bound to authorization')
    split_path=Path(args.split_seal)
    if sha256_file(split_path)!=exe['fingerprint_basis']['input_artifacts']['development_labels']['split_seal_sha256']: raise ValueError('split-seal hash mismatch')
    split=json.loads(split_path.read_text(encoding='utf-8'))
    if len(split['splits'])!=5 or len(split['blocks'])!=6: raise ValueError('split shape mismatch')
    if not all(s['future_train_to_past_test'] is False for s in split['splits']): raise ValueError('noncausal split')

    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect(); con.execute("PRAGMA threads=4"); con.execute("PRAGMA memory_limit='7GB'"); con.execute("PRAGMA temp_directory='build/duckdb-train-prep-tmp'")
    features=auth['fingerprint_basis']['feature_columns']
    feat_sql=',\n'.join(f'm.{qi(c)} AS {qi(c)}' for c in features)
    prepared=out/'joined_development.parquet'
    con.execute(f"""
      COPY (
        SELECT CAST(m.trade_date AS DATE) AS trade_date,
               upper(CAST(m.exchange AS VARCHAR)) AS exchange,
               lpad(CAST(m.code AS VARCHAR),6,'0') AS code,
               {feat_sql},
               CAST(l.valid_label_5d AS BOOLEAN) AS valid_label_5d,
               CAST(l.valid_label_20d AS BOOLEAN) AS valid_label_20d,
               CAST(l.excess_return_5d AS DOUBLE) AS excess_return_5d,
               CAST(l.excess_return_20d AS DOUBLE) AS excess_return_20d,
               CAST(l.stock_total_return_20d AS DOUBLE) AS stock_total_return_20d,
               CAST(l.benchmark_return_20d AS DOUBLE) AS benchmark_return_20d
        FROM read_parquet({q(args.matrix)}) m
        JOIN read_parquet({q(args.labels)}) l
          ON CAST(m.trade_date AS DATE)=CAST(l.trade_date AS DATE)
         AND upper(CAST(m.exchange AS VARCHAR))=upper(CAST(l.exchange AS VARCHAR))
         AND lpad(CAST(m.code AS VARCHAR),6,'0')=lpad(CAST(l.code AS VARCHAR),6,'0')
        WHERE CAST(m.trade_date AS DATE) BETWEEN DATE '2015-01-05' AND DATE '2022-12-30'
        ORDER BY trade_date,exchange,code
      ) TO {q(str(prepared))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    rows,ukeys,dmin,dmax,valid20=con.execute(f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date),count(*) FILTER(WHERE valid_label_20d) FROM read_parquet({q(str(prepared))})").fetchone()
    if not (rows==ukeys==5197648 and str(dmin)=='2015-01-05' and str(dmax)=='2022-12-30' and valid20==5103016):
        raise ValueError(f'prepared population mismatch rows={rows} unique={ukeys} dates={dmin}..{dmax} valid20={valid20}')

    binary=auth['fingerprint_basis']['feature_roles']['binary_missing_indicators']
    bad_expr=' + '.join(f"sum(CASE WHEN {qi(c)} IS NULL OR CAST({qi(c)} AS DOUBLE) NOT IN (0.0,1.0) THEN 1 ELSE 0 END)" for c in binary)
    bad_binary=con.execute(f"SELECT {bad_expr} FROM read_parquet({q(str(prepared))})").fetchone()[0]
    if bad_binary!=0: raise ValueError(f'binary indicator violations={bad_binary}')

    financial=set(auth['fingerprint_basis']['feature_roles']['financial_signed_log1p'])
    continuous=auth['fingerprint_basis']['feature_roles']['continuous_clip_train_only']
    def xexpr(c: str) -> str:
        z=qi(c)
        return f"CASE WHEN {z} IS NULL THEN NULL ELSE sign(CAST({z} AS DOUBLE))*ln(1+abs(CAST({z} AS DOUBLE))) END" if c in financial else f"CAST({z} AS DOUBLE)"

    split_stats=[]
    for s in split['splits']:
        sid=int(s['split_id']); ts=s['train_start']; te=s['train_end']; vs=s['test_start']; ve=s['test_end']
        filt=f"valid_label_20d AND trade_date BETWEEN DATE {q(ts)} AND DATE {q(te)}"
        train_rows=con.execute(f"SELECT count(*) FROM read_parquet({q(str(prepared))}) WHERE {filt}").fetchone()[0]
        test_rows,test_days=con.execute(f"SELECT count(*),count(DISTINCT trade_date) FROM read_parquet({q(str(prepared))}) WHERE valid_label_20d AND trade_date BETWEEN DATE {q(vs)} AND DATE {q(ve)}").fetchone()
        if train_rows<=0 or test_rows<=0: raise ValueError(f'empty split {sid}')
        levels=[r[0] for r in con.execute(f"SELECT DISTINCT CAST(regime_state AS VARCHAR) FROM read_parquet({q(str(prepared))}) WHERE {filt} AND regime_state IS NOT NULL ORDER BY 1").fetchall()]
        agg=[]
        for c in continuous:
            e=xexpr(c); prefix=c.replace('"','')
            agg += [f"quantile_cont({e},0.001) AS {qi(prefix+'__q001')}", f"quantile_cont({e},0.999) AS {qi(prefix+'__q999')}", f"median({e}) AS {qi(prefix+'__median')}"]
        vals=con.execute(f"SELECT {','.join(agg)} FROM read_parquet({q(str(prepared))}) WHERE {filt}").fetchone()
        stats={}
        j=0
        for c in continuous:
            lo,hi,med=vals[j],vals[j+1],vals[j+2]; j+=3
            stats[c]={'q001':None if lo is None else float(lo),'q999':None if hi is None else float(hi),'median':None if med is None else float(med)}
            if med is None: raise ValueError(f'all-missing continuous feature {c} in split {sid}')
        entry={'split_id':sid,'train_start':ts,'train_end':te,'test_start':vs,'test_end':ve,'train_rows_valid20':train_rows,'test_rows_valid20':test_rows,'test_days':test_days,'regime_levels_train':levels,'continuous_train_stats':stats}
        entry['stats_sha256']=canonical_hash(entry)
        split_stats.append(entry)

    preprocess={'schema_version':1,'authorization_fingerprint':auth['fingerprint'],'execution_fingerprint':exe['fingerprint'],'prepared_rows':rows,'valid20_rows':valid20,'feature_columns':features,'binary_indicator_violations':bad_binary,'split_seal_sha256':sha256_file(split_path),'splits':split_stats}
    prep_path=out/'split_preprocess.json'; prep_path.write_text(json.dumps(preprocess,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    audit={'gate':'STAGE4_ALPHA_V1_DEVELOPMENT_CV_PREPARE_DATA','pass':True,'prepared_rows':rows,'unique_keys':ukeys,'date_min':str(dmin),'date_max':str(dmax),'valid20_rows':valid20,'feature_count':len(features),'binary_indicator_violations':bad_binary,'split_count':len(split_stats),'prepared_sha256':sha256_file(prepared),'split_preprocess_sha256':sha256_file(prep_path),'model_fit_executed':False,'oos_accessed':False,'lockbox_accessed':False}
    (out/'prepare_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(audit,ensure_ascii=False,indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
