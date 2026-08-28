#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def q(s:str)->str: return "'"+s.replace("'","''")+"'"

def row(con,sql):
    cur=con.execute(sql); return dict(zip([x[0] for x in cur.description],cur.fetchone()))


def main()->int:
    ap=argparse.ArgumentParser()
    for n in ['contract','source-cv-authorization','source-verification','package-dir','out']: ap.add_argument('--'+n,required=True)
    a=ap.parse_args(); import duckdb
    checks={}; failures=[]
    def ck(n,c,d=''):
        checks[n]=bool(c)
        if not c: failures.append(n+(f': {d}' if d else ''))
    try:
        c=json.loads(Path(a.contract).read_text(encoding='utf-8')); b=c['fingerprint_basis']; ck('contract_fp',canonical_hash(b)==c['fingerprint']); ck('contract_status',c.get('status')=='PRE_PREDICTION_PHYSICAL_OOS_BOUNDARY_COMPILER_NON_LABEL_NON_CONSUMING')
        src=json.loads(Path(a.source_cv_authorization).read_text(encoding='utf-8')); sfp=b['source_cv_authorization_fingerprint']; ck('source_cv_fp',src.get('fingerprint')==sfp and canonical_hash(src['fingerprint_basis'])==sfp); features_expected=list(src['fingerprint_basis']['feature_columns'])
        v=json.loads(Path(a.source_verification).read_text(encoding='utf-8')); ck('source_verification',v.get('status')=='VERIFIED' and v.get('boundary_contract_fingerprint')==c['fingerprint'])
        for key,exp in b['inputs'].items():
            got=v.get('artifacts',{}).get(key,{}); ck('source_'+key,int(got.get('artifact_id',-1))==int(exp['artifact_id']) and got.get('archive_sha256')==exp['artifact_zip_sha256'] and got.get('verified') is True)
        root=Path(a.package_dir); o=b['outputs']; paths={k:root/o[k] for k in ['features','market','execution_state','lifecycle','manifest','hashes']}
        for k,p in paths.items(): ck('exists_'+k,p.is_file())
        m=json.loads(paths['manifest'].read_text(encoding='utf-8')); h=json.loads(paths['hashes'].read_text(encoding='utf-8'))
        ck('manifest_status',m.get('status')=='PHYSICALLY_OOS_ONLY_PRE_PREDICTION_NON_LABEL'); ck('manifest_binding',m.get('boundary_contract_fingerprint')==c['fingerprint'] and m.get('source_cv_authorization_fingerprint')==sfp); ck('feature_columns',m.get('feature_columns')==features_expected)
        for k in ['features','market','execution_state','lifecycle','manifest']: ck('hash_'+k,h.get(paths[k].name)==sha256_file(paths[k]))
        g=m.get('guards',{})
        for k in ['broad_feature_matrix_available_downstream','broad_g3_available_downstream','broad_g4_available_downstream','raw_g5_available_downstream','raw_g2_available_downstream','oos_prediction_executed','oos_label_constructed','oos_label_value_read','model_loaded','authorization_consumed','fit_retrain_tune_reselect_executed','final_lockbox_accessed','business_metrics_computed']: ck('guard_'+k,g.get(k) is False)
        for k in ['post_oos_feature_rows','post_oos_market_rows','post_oos_execution_state_rows','post_oos_lifecycle_delist_rows']: ck('guard_'+k,int(g.get(k,-1))==0)
        start,end=b['scope']['decision_start'],b['scope']['decision_end']; con=duckdb.connect(); con.execute('PRAGMA threads=2')
        for name,k in [('f','features'),('m','market'),('s','execution_state'),('l','lifecycle')]: con.execute(f'CREATE TEMP VIEW {name} AS SELECT * FROM read_parquet({q(str(paths[k]))})')
        cols=[x[0] for x in con.execute('SELECT * FROM f LIMIT 0').description]; ck('feature_schema_exact',cols==['trade_date','exchange','code']+features_expected,str(cols))
        fs=row(con,f"SELECT count(*)::BIGINT row_count,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,count(DISTINCT trade_date)::BIGINT decision_days,min(trade_date) date_min,max(trade_date) date_max,count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT outside_rows FROM f")
        ms=row(con,f"SELECT count(*)::BIGINT row_count,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,count(DISTINCT trade_date)::BIGINT market_days,min(trade_date) date_min,max(trade_date) date_max,count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT outside_rows,count(*) FILTER(WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR volume_shares IS NULL OR factor IS NULL)::BIGINT null_required_rows FROM m")
        ss=row(con,f"SELECT count(*)::BIGINT row_count,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,count(DISTINCT trade_date)::BIGINT state_days,min(trade_date) date_min,max(trade_date) date_max,count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT outside_rows,count(*) FILTER(WHERE tradable IS NULL OR risk_warning IS NULL OR preclose IS NULL OR limit_up_rate IS NULL OR limit_down_rate IS NULL)::BIGINT null_required_rows FROM s")
        ls=row(con,f"SELECT count(*)::BIGINT row_count,max(listed_to_exclusive) listed_to_max,count(*) FILTER(WHERE listed_to_exclusive IS NOT NULL AND listed_to_exclusive>DATE {q(end)})::BIGINT post_oos_delist_rows FROM l")
        st=row(con,"""WITH fd AS(SELECT DISTINCT trade_date FROM f),md AS(SELECT DISTINCT trade_date FROM m),missing_dates AS(SELECT fd.trade_date FROM fd LEFT JOIN md USING(trade_date) WHERE md.trade_date IS NULL),missing_symbols AS(SELECT DISTINCT f.exchange,f.code FROM f LEFT JOIN l ON f.exchange=l.exchange AND f.code=l.code WHERE l.code IS NULL),missing_state AS(SELECT f.trade_date,f.exchange,f.code FROM f LEFT JOIN s USING(trade_date,exchange,code) WHERE s.code IS NULL) SELECT (SELECT count(*) FROM missing_dates)::BIGINT feature_dates_missing_market_calendar,(SELECT count(*) FROM missing_symbols)::BIGINT feature_symbols_missing_lifecycle,(SELECT count(*) FROM missing_state)::BIGINT feature_decision_keys_missing_execution_state""")
        for name,x in [('features',fs),('market',ms),('execution_state',ss)]:
            ck(name+'_positive',int(x['row_count'])>0); ck(name+'_unique',int(x['row_count'])==int(x['unique_keys']),str(x)); ck(name+'_min',str(x['date_min'])==start,str(x)); ck(name+'_max',str(x['date_max'])==end,str(x)); ck(name+'_outside',int(x['outside_rows'])==0,str(x))
        ck('market_complete',int(ms['null_required_rows'])==0,str(ms)); ck('state_complete',int(ss['null_required_rows'])==0,str(ss)); ck('lifecycle_no_post_oos',int(ls['post_oos_delist_rows'])==0,str(ls))
        for k,vv in st.items(): ck('structural_'+k,int(vv)==0,str(st))
        ck('manifest_features',int(m['features']['row_count'])==int(fs['row_count'])); ck('manifest_market',int(m['market']['row_count'])==int(ms['row_count'])); ck('manifest_state',int(m['execution_state']['row_count'])==int(ss['row_count'])); ck('manifest_lifecycle',int(m['lifecycle']['row_count'])==int(ls['row_count'])); ck('manifest_structural',m['structural_readiness']==st)
        result={'schema_version':2,'status':'PASS' if not failures else 'FAIL','pass':not failures,'boundary_contract_fingerprint':c['fingerprint'],'checks':checks,'failed_checks':failures,'features':fs,'market':ms,'execution_state':ss,'lifecycle':ls,'structural_readiness':st,'post_oos_rows_observed':int(fs['outside_rows'])+int(ms['outside_rows'])+int(ss['outside_rows'])+int(ls['post_oos_delist_rows']),'oos_prediction_executed':False,'oos_label_constructed':False,'oos_label_value_read':False,'model_loaded':False,'authorization_consumed':False,'final_lockbox_accessed':False}
    except Exception as e:
        failures.append(f'exception: {type(e).__name__}: {e}'); result={'schema_version':2,'status':'FAIL','pass':False,'checks':checks,'failed_checks':failures}
    p=Path(a.out); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8'); print(json.dumps(result,ensure_ascii=False,indent=2,default=str)); return 0 if result['pass'] else 2

if __name__=='__main__': raise SystemExit(main())
