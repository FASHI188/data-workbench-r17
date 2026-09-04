#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
from typing import Any

NA_LIMIT_RULES=('SUSPENDED','IPO_FIRST5_NO_LIMIT','DELISTING_15DAY_FIRST_DAY_NO_LIMIT')
TRADABLE_NO_LIMIT_RULES=('IPO_FIRST5_NO_LIMIT','DELISTING_15DAY_FIRST_DAY_NO_LIMIT')

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def canonical_hash(obj:Any)->str:
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def q(s:str)->str: return "'"+s.replace("'","''")+"'"
def sl(values:tuple[str,...])->str: return '('+','.join(q(x) for x in values)+')'
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
        ck('applicability_manifest',m.get('execution_state_applicability',{}).get('na_limit_rules')==list(NA_LIMIT_RULES) and m.get('execution_state_applicability',{}).get('null_limit_rates_mean_not_applicable_not_imputed') is True)
        for k in ['features','market','execution_state','lifecycle','manifest']: ck('hash_'+k,h.get(paths[k].name)==sha256_file(paths[k]))
        g=m.get('guards',{})
        for k in ['broad_feature_matrix_available_downstream','broad_g3_available_downstream','broad_g4_available_downstream','raw_g5_available_downstream','raw_g2_available_downstream','oos_prediction_executed','oos_label_constructed','oos_label_value_read','model_loaded','authorization_consumed','fit_retrain_tune_reselect_executed','final_lockbox_accessed','business_metrics_computed']: ck('guard_'+k,g.get(k) is False)
        for k in ['post_oos_feature_rows','post_oos_market_rows','post_oos_execution_state_rows','post_oos_lifecycle_delist_rows']: ck('guard_'+k,int(g.get(k,-1))==0)
        start,end,econ=b['scope']['decision_start'],b['scope']['decision_end'],b['scope']['latest_labelable_decision']; con=duckdb.connect(); con.execute('PRAGMA threads=2')
        for name,k in [('f','features'),('m','market'),('s','execution_state'),('l','lifecycle')]: con.execute(f'CREATE TEMP VIEW {name} AS SELECT * FROM read_parquet({q(str(paths[k]))})')
        cols=[x[0] for x in con.execute('SELECT * FROM f LIMIT 0').description]; ck('feature_schema_exact',cols==['trade_date','exchange','code']+features_expected,str(cols))
        na=sl(NA_LIMIT_RULES); tnl=sl(TRADABLE_NO_LIMIT_RULES)
        fs=row(con,f"SELECT count(*)::BIGINT row_count,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,count(DISTINCT trade_date)::BIGINT decision_days,min(trade_date) date_min,max(trade_date) date_max,count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT outside_rows FROM f")
        ms=row(con,f"SELECT count(*)::BIGINT row_count,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,count(DISTINCT trade_date)::BIGINT market_days,min(trade_date) date_min,max(trade_date) date_max,count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT outside_rows,count(*) FILTER(WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR volume_shares IS NULL OR factor IS NULL)::BIGINT null_required_rows FROM m")
        ss=row(con,f"""SELECT count(*)::BIGINT row_count,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,count(DISTINCT trade_date)::BIGINT state_days,min(trade_date) date_min,max(trade_date) date_max,
          count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT outside_rows,
          count(*) FILTER(WHERE tradable IS NULL OR risk_warning IS NULL OR preclose IS NULL OR limit_rule IS NULL OR trim(limit_rule)='')::BIGINT core_null_rows,
          count(*) FILTER(WHERE (limit_up_rate IS NULL AND limit_down_rate IS NOT NULL) OR (limit_up_rate IS NOT NULL AND limit_down_rate IS NULL))::BIGINT partial_limit_rate_null_rows,
          count(*) FILTER(WHERE limit_rule IN {na} AND limit_up_rate IS NULL AND limit_down_rate IS NULL)::BIGINT na_limit_rate_rows,
          count(*) FILTER(WHERE limit_rule IN {na} AND (limit_up_rate IS NOT NULL OR limit_down_rate IS NOT NULL))::BIGINT na_rule_rate_present_rows,
          count(*) FILTER(WHERE limit_rule NOT IN {na} AND (limit_up_rate IS NULL OR limit_down_rate IS NULL))::BIGINT applicable_rule_missing_rate_rows,
          count(*) FILTER(WHERE limit_rule='SUSPENDED' AND tradable<>0)::BIGINT suspended_tradable_mismatch_rows,
          count(*) FILTER(WHERE limit_rule IN {tnl} AND tradable<>1)::BIGINT no_limit_tradable_mismatch_rows FROM s""")
        ls=row(con,f"SELECT count(*)::BIGINT row_count,max(listed_to_exclusive) listed_to_max,count(*) FILTER(WHERE listed_to_exclusive IS NOT NULL AND listed_to_exclusive>DATE {q(end)})::BIGINT post_oos_delist_rows FROM l")
        st=row(con,"""WITH fd AS(SELECT DISTINCT trade_date FROM f),md AS(SELECT DISTINCT trade_date FROM m),missing_dates AS(SELECT fd.trade_date FROM fd LEFT JOIN md USING(trade_date) WHERE md.trade_date IS NULL),missing_symbols AS(SELECT DISTINCT f.exchange,f.code FROM f LEFT JOIN l ON f.exchange=l.exchange AND f.code=l.code WHERE l.code IS NULL),missing_state AS(SELECT f.trade_date,f.exchange,f.code FROM f LEFT JOIN s USING(trade_date,exchange,code) WHERE s.code IS NULL),market_missing_state AS(SELECT m.trade_date,m.exchange,m.code FROM m LEFT JOIN s USING(trade_date,exchange,code) WHERE s.code IS NULL),state_missing_market AS(SELECT s.* FROM s LEFT JOIN m USING(trade_date,exchange,code) WHERE m.code IS NULL)
          SELECT (SELECT count(*) FROM missing_dates)::BIGINT feature_dates_missing_market_calendar,(SELECT count(*) FROM missing_symbols)::BIGINT feature_symbols_missing_lifecycle,(SELECT count(*) FROM missing_state)::BIGINT feature_decision_keys_missing_execution_state,(SELECT count(*) FROM market_missing_state)::BIGINT market_rows_missing_execution_state,(SELECT count(*) FROM state_missing_market)::BIGINT execution_state_rows_missing_market,(SELECT count(*) FROM state_missing_market WHERE tradable=1)::BIGINT tradable_state_rows_missing_market,(SELECT count(*) FROM state_missing_market WHERE tradable=0 AND limit_rule='SUSPENDED')::BIGINT suspended_state_rows_missing_market,(SELECT count(*) FROM state_missing_market WHERE NOT (tradable=0 AND limit_rule='SUSPENDED'))::BIGINT invalid_state_rows_missing_market""")
        for name,x in [('features',fs),('market',ms),('execution_state',ss)]:
            ck(name+'_positive',int(x['row_count'])>0); ck(name+'_unique',int(x['row_count'])==int(x['unique_keys']),str(x)); ck(name+'_min',str(x['date_min'])==start,str(x)); ck(name+'_max',str(x['date_max'])==end,str(x)); ck(name+'_outside',int(x['outside_rows'])==0,str(x))
        ck('market_complete',int(ms['null_required_rows'])==0,str(ms))
        for k in ['core_null_rows','partial_limit_rate_null_rows','na_rule_rate_present_rows','applicable_rule_missing_rate_rows','suspended_tradable_mismatch_rows','no_limit_tradable_mismatch_rows']: ck('state_'+k,int(ss[k])==0,str(ss))
        ck('lifecycle_no_post_oos',int(ls['post_oos_delist_rows'])==0,str(ls))
        for k in ['feature_dates_missing_market_calendar','feature_symbols_missing_lifecycle','feature_decision_keys_missing_execution_state','market_rows_missing_execution_state','tradable_state_rows_missing_market','invalid_state_rows_missing_market']: ck('structural_'+k,int(st[k])==0,str(st))
        ck('structural_g4_only_exact_suspended',int(st['execution_state_rows_missing_market'])==int(st['suspended_state_rows_missing_market']),str(st))
        con.execute("CREATE TEMP TABLE cal AS SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 session_idx FROM (SELECT DISTINCT trade_date FROM m) ORDER BY trade_date")
        con.execute(f"CREATE TEMP TABLE cs AS SELECT f.trade_date,f.exchange,f.code,c.session_idx,e.trade_date entry_date,x.trade_date exit_date FROM (SELECT trade_date,exchange,code FROM f WHERE trade_date<=DATE {q(econ)}) f JOIN cal c ON f.trade_date=c.trade_date LEFT JOIN cal e ON e.session_idx=c.session_idx+1 LEFT JOIN cal x ON x.session_idx=c.session_idx+20")
        cr=row(con,f"""SELECT count(*)::BIGINT candidate_rows,
          count(*) FILTER(WHERE cs.entry_date IS NULL OR cs.exit_date IS NULL)::BIGINT missing_schedule_rows,
          count(*) FILTER(WHERE ds.tradable IS NULL OR ds.risk_warning IS NULL OR ds.preclose IS NULL OR ds.limit_rule IS NULL)::BIGINT missing_decision_core_state_rows,
          count(*) FILTER(WHERE es.tradable IS NULL OR es.risk_warning IS NULL OR es.preclose IS NULL OR es.limit_rule IS NULL)::BIGINT missing_entry_core_state_rows,
          count(*) FILTER(WHERE xs.tradable IS NULL OR xs.risk_warning IS NULL OR xs.preclose IS NULL OR xs.limit_rule IS NULL)::BIGINT missing_exit_core_state_rows,
          count(*) FILTER(WHERE ds.limit_rule NOT IN {na} AND (ds.limit_up_rate IS NULL OR ds.limit_down_rate IS NULL))::BIGINT decision_applicable_rate_missing_rows,
          count(*) FILTER(WHERE es.limit_rule NOT IN {na} AND (es.limit_up_rate IS NULL OR es.limit_down_rate IS NULL))::BIGINT entry_applicable_rate_missing_rows,
          count(*) FILTER(WHERE xs.limit_rule NOT IN {na} AND (xs.limit_up_rate IS NULL OR xs.limit_down_rate IS NULL))::BIGINT exit_applicable_rate_missing_rows,
          count(*) FILTER(WHERE ds.tradable=1 AND dm.code IS NULL)::BIGINT tradable_decision_market_missing_rows,
          count(*) FILTER(WHERE es.tradable=1 AND em.code IS NULL)::BIGINT tradable_entry_market_missing_rows,
          count(*) FILTER(WHERE xs.tradable=1 AND xm.code IS NULL)::BIGINT tradable_exit_market_missing_rows,
          count(*) FILTER(WHERE dm.code IS NULL AND NOT (ds.tradable=0 AND ds.limit_rule='SUSPENDED'))::BIGINT invalid_decision_market_missing_rows,
          count(*) FILTER(WHERE em.code IS NULL AND NOT (es.tradable=0 AND es.limit_rule='SUSPENDED'))::BIGINT invalid_entry_market_missing_rows,
          count(*) FILTER(WHERE xm.code IS NULL AND NOT (xs.tradable=0 AND xs.limit_rule='SUSPENDED'))::BIGINT invalid_exit_market_missing_rows
          FROM cs LEFT JOIN s ds ON cs.trade_date=ds.trade_date AND cs.exchange=ds.exchange AND cs.code=ds.code LEFT JOIN s es ON cs.entry_date=es.trade_date AND cs.exchange=es.exchange AND cs.code=es.code LEFT JOIN s xs ON cs.exit_date=xs.trade_date AND cs.exchange=xs.exchange AND cs.code=xs.code LEFT JOIN m dm ON cs.trade_date=dm.trade_date AND cs.exchange=dm.exchange AND cs.code=dm.code LEFT JOIN m em ON cs.entry_date=em.trade_date AND cs.exchange=em.exchange AND cs.code=em.code LEFT JOIN m xm ON cs.exit_date=xm.trade_date AND cs.exchange=xm.exchange AND cs.code=xm.code""")
        ck('candidate_positive',int(cr['candidate_rows'])>0,str(cr))
        for k in cr:
            if k!='candidate_rows': ck('candidate_'+k,int(cr[k])==0,str(cr))
        ck('manifest_features',m.get('features')==fs); ck('manifest_market',m.get('market')==ms); ck('manifest_state',m.get('execution_state')==ss); ck('manifest_lifecycle',int(m['lifecycle']['row_count'])==int(ls['row_count'])); ck('manifest_structural',m.get('structural_readiness')==st); ck('manifest_candidate_readiness',m.get('runtime_candidate_path_readiness')==cr)
        result={'schema_version':3,'status':'PASS' if not failures else 'FAIL','pass':not failures,'boundary_contract_fingerprint':c['fingerprint'],'checks':checks,'failed_checks':failures,'features':fs,'market':ms,'execution_state':ss,'lifecycle':ls,'structural_readiness':st,'runtime_candidate_path_readiness':cr,'post_oos_rows_observed':int(fs['outside_rows'])+int(ms['outside_rows'])+int(ss['outside_rows'])+int(ls['post_oos_delist_rows']),'oos_prediction_executed':False,'oos_label_constructed':False,'oos_label_value_read':False,'model_loaded':False,'authorization_consumed':False,'final_lockbox_accessed':False}
    except Exception as e:
        failures.append(f'exception: {type(e).__name__}: {e}'); result={'schema_version':3,'status':'FAIL','pass':False,'checks':checks,'failed_checks':failures}
    p=Path(a.out); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8'); print(json.dumps(result,ensure_ascii=False,indent=2,default=str)); return 0 if result['pass'] else 2

if __name__=='__main__': raise SystemExit(main())
