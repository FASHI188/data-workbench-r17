#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys
from pathlib import Path
from typing import Any

BOUNDARY_FP='67e8555d3a9212a003a8293dc381cce0f7294917ef72875fed3218f240e0c255'
SOURCE_AUTH_FP='2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c'
NA_LIMIT_RULES=('SUSPENDED','IPO_FIRST5_NO_LIMIT','DELISTING_15DAY_FIRST_DAY_NO_LIMIT')
TRADABLE_NO_LIMIT_RULES=('IPO_FIRST5_NO_LIMIT','DELISTING_15DAY_FIRST_DAY_NO_LIMIT')
LEGACY_FAILURE_TOKEN='pre-prediction Runtime Veto candidate-path readiness failed'

def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def canon(x:Any)->str:
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def q(s:str)->str: return "'"+s.replace("'","''")+"'"
def sl(xs): return '('+','.join(q(x) for x in xs)+')'
def one(con,sql):
    c=con.execute(sql); return dict(zip([d[0] for d in c.description],c.fetchone()))

def main()->int:
    ap=argparse.ArgumentParser()
    for n in ['contract','source-cv-authorization','source-verification','matrix-root','g3-root','g4-root','g5-root','g2-root','work-dir','out']:
        ap.add_argument('--'+n,required=True)
    a=ap.parse_args()
    import duckdb
    contract=json.loads(Path(a.contract).read_text(encoding='utf-8')); b=contract['fingerprint_basis']
    if contract.get('fingerprint')!=BOUNDARY_FP or canon(b)!=BOUNDARY_FP: raise ValueError('physical boundary contract mismatch')
    src=json.loads(Path(a.source_cv_authorization).read_text(encoding='utf-8'))
    if src.get('fingerprint')!=SOURCE_AUTH_FP or canon(src['fingerprint_basis'])!=SOURCE_AUTH_FP: raise ValueError('source authorization mismatch')
    sv=json.loads(Path(a.source_verification).read_text(encoding='utf-8'))
    if sv.get('status')!='VERIFIED' or sv.get('boundary_contract_fingerprint')!=BOUNDARY_FP: raise ValueError('source verification mismatch')
    for k,exp in b['inputs'].items():
        got=sv.get('artifacts',{}).get(k,{})
        if int(got.get('artifact_id',-1))!=int(exp['artifact_id']) or got.get('archive_sha256')!=exp['artifact_zip_sha256'] or got.get('verified') is not True:
            raise ValueError('source verification artifact mismatch: '+k)
    legacy=Path(__file__).with_name('build_stage4_alpha_v1_oos_physical_boundary.py')
    cmd=[sys.executable,str(legacy)]
    for n in ['contract','source-cv-authorization','source-verification','matrix-root','g3-root','g4-root','g5-root','g2-root','work-dir','out']:
        cmd += ['--'+n,getattr(a,n.replace('-','_'))]
    p=subprocess.run(cmd,text=True,capture_output=True)
    text=(p.stdout or '')+'\n'+(p.stderr or '')
    if p.returncode==0:
        raise ValueError('legacy boundary compiler unexpectedly passed; lifecycle recovery path not proven necessary')
    if LEGACY_FAILURE_TOKEN not in text:
        raise ValueError('legacy boundary compiler failed outside the frozen lifecycle-readiness failure: '+text[-3000:])
    out=Path(a.out); o=b['outputs']
    fp=out/o['features']; mp=out/o['market']; sp=out/o['execution_state']; lp=out/o['lifecycle']
    for x in [fp,mp,sp,lp,Path(a.source_verification)]:
        if not x.is_file(): raise ValueError('expected physical output missing: '+str(x))
    for forbidden in ['authorization_consumption.json','oos_predictions.parquet','oos_labels.parquet']:
        if (out/forbidden).exists(): raise ValueError('forbidden pre-prediction materialization: '+forbidden)
    con=duckdb.connect(); con.execute('PRAGMA threads=4'); con.execute("PRAGMA memory_limit='6GB'")
    for v,pth in [('f',fp),('m',mp),('s',sp),('l',lp)]: con.execute(f'CREATE TEMP VIEW {v} AS SELECT * FROM read_parquet({q(str(pth))})')
    start=b['scope']['decision_start']; end=b['scope']['decision_end']; econ=b['scope']['latest_labelable_decision']; na=sl(NA_LIMIT_RULES); tnl=sl(TRADABLE_NO_LIMIT_RULES)
    features=one(con,f"SELECT count(*)::BIGINT row_count,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,count(DISTINCT trade_date)::BIGINT decision_days,min(trade_date) date_min,max(trade_date) date_max,count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT outside_rows FROM f")
    market=one(con,f"SELECT count(*)::BIGINT row_count,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,count(DISTINCT trade_date)::BIGINT market_days,min(trade_date) date_min,max(trade_date) date_max,count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT outside_rows,count(*) FILTER(WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR volume_shares IS NULL OR factor IS NULL)::BIGINT null_required_rows FROM m")
    state=one(con,f"""SELECT count(*)::BIGINT row_count,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,count(DISTINCT trade_date)::BIGINT state_days,min(trade_date) date_min,max(trade_date) date_max,
      count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT outside_rows,
      count(*) FILTER(WHERE tradable IS NULL OR risk_warning IS NULL OR preclose IS NULL OR limit_rule IS NULL OR trim(limit_rule)='')::BIGINT core_null_rows,
      count(*) FILTER(WHERE (limit_up_rate IS NULL AND limit_down_rate IS NOT NULL) OR (limit_up_rate IS NOT NULL AND limit_down_rate IS NULL))::BIGINT partial_limit_rate_null_rows,
      count(*) FILTER(WHERE limit_rule IN {na} AND limit_up_rate IS NULL AND limit_down_rate IS NULL)::BIGINT na_limit_rate_rows,
      count(*) FILTER(WHERE limit_rule IN {na} AND (limit_up_rate IS NOT NULL OR limit_down_rate IS NOT NULL))::BIGINT na_rule_rate_present_rows,
      count(*) FILTER(WHERE limit_rule NOT IN {na} AND (limit_up_rate IS NULL OR limit_down_rate IS NULL))::BIGINT applicable_rule_missing_rate_rows,
      count(*) FILTER(WHERE limit_rule='SUSPENDED' AND tradable<>0)::BIGINT suspended_tradable_mismatch_rows,
      count(*) FILTER(WHERE limit_rule IN {tnl} AND tradable<>1)::BIGINT no_limit_tradable_mismatch_rows FROM s""")
    lifecycle=one(con,f"SELECT count(*)::BIGINT row_count,min(listed_from) listed_from_min,max(listed_from) listed_from_max,max(listed_to_exclusive) listed_to_max,count(*) FILTER(WHERE listed_to_exclusive IS NOT NULL AND listed_to_exclusive>DATE {q(end)})::BIGINT post_oos_delist_rows FROM l")
    structural=one(con,"""WITH fd AS(SELECT DISTINCT trade_date FROM f),md AS(SELECT DISTINCT trade_date FROM m),
      missing_dates AS(SELECT fd.trade_date FROM fd LEFT JOIN md USING(trade_date) WHERE md.trade_date IS NULL),
      missing_symbols AS(SELECT DISTINCT f.exchange,f.code FROM f LEFT JOIN l ON f.exchange=l.exchange AND f.code=l.code WHERE l.code IS NULL),
      missing_state AS(SELECT f.trade_date,f.exchange,f.code FROM f LEFT JOIN s USING(trade_date,exchange,code) WHERE s.code IS NULL),
      market_missing_state AS(SELECT m.trade_date,m.exchange,m.code FROM m LEFT JOIN s USING(trade_date,exchange,code) WHERE s.code IS NULL),
      state_missing_market AS(SELECT s.* FROM s LEFT JOIN m USING(trade_date,exchange,code) WHERE m.code IS NULL)
      SELECT (SELECT count(*) FROM missing_dates)::BIGINT feature_dates_missing_market_calendar,
             (SELECT count(*) FROM missing_symbols)::BIGINT feature_symbols_missing_lifecycle,
             (SELECT count(*) FROM missing_state)::BIGINT feature_decision_keys_missing_execution_state,
             (SELECT count(*) FROM market_missing_state)::BIGINT market_rows_missing_execution_state,
             (SELECT count(*) FROM state_missing_market)::BIGINT execution_state_rows_missing_market,
             (SELECT count(*) FROM state_missing_market WHERE tradable=1)::BIGINT tradable_state_rows_missing_market,
             (SELECT count(*) FROM state_missing_market WHERE tradable=0 AND limit_rule='SUSPENDED')::BIGINT suspended_state_rows_missing_market,
             (SELECT count(*) FROM state_missing_market WHERE NOT (tradable=0 AND limit_rule='SUSPENDED'))::BIGINT invalid_state_rows_missing_market""")
    for name,x in [('features',features),('market',market),('execution_state',state)]:
        if int(x['row_count'])<=0 or int(x['row_count'])!=int(x['unique_keys']) or str(x['date_min'])!=start or str(x['date_max'])!=end or int(x['outside_rows'])!=0: raise ValueError(name+' physical population invalid')
    if int(market['null_required_rows'])!=0: raise ValueError('market required values missing')
    for k in ['core_null_rows','partial_limit_rate_null_rows','na_rule_rate_present_rows','applicable_rule_missing_rate_rows','suspended_tradable_mismatch_rows','no_limit_tradable_mismatch_rows']:
        if int(state[k])!=0: raise ValueError('execution-state integrity failed: '+k)
    if int(lifecycle['post_oos_delist_rows'])!=0: raise ValueError('lifecycle leaks post-OOS information')
    for k in ['feature_dates_missing_market_calendar','feature_symbols_missing_lifecycle','feature_decision_keys_missing_execution_state','market_rows_missing_execution_state','tradable_state_rows_missing_market','invalid_state_rows_missing_market']:
        if int(structural[k])!=0: raise ValueError('structural readiness failed: '+k)
    if int(structural['execution_state_rows_missing_market'])!=int(structural['suspended_state_rows_missing_market']): raise ValueError('G4-only rows not exclusively suspended')
    con.execute("CREATE TEMP TABLE cal AS SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 session_idx FROM (SELECT DISTINCT trade_date FROM m) ORDER BY trade_date")
    con.execute(f"""CREATE TEMP TABLE cs AS SELECT f.trade_date,f.exchange,f.code,c.session_idx,e.trade_date entry_date,x.trade_date exit_date
      FROM (SELECT trade_date,exchange,code FROM f WHERE trade_date<=DATE {q(econ)}) f JOIN cal c ON f.trade_date=c.trade_date
      LEFT JOIN cal e ON e.session_idx=c.session_idx+1 LEFT JOIN cal x ON x.session_idx=c.session_idx+20""")
    con.execute("""CREATE TEMP TABLE cr0 AS SELECT cs.*,
      EXISTS(SELECT 1 FROM l z WHERE z.exchange=cs.exchange AND z.code=cs.code AND cs.trade_date>=z.listed_from AND (z.listed_to_exclusive IS NULL OR cs.trade_date<z.listed_to_exclusive)) decision_active,
      EXISTS(SELECT 1 FROM l z WHERE z.exchange=cs.exchange AND z.code=cs.code AND cs.entry_date>=z.listed_from AND (z.listed_to_exclusive IS NULL OR cs.entry_date<z.listed_to_exclusive)) entry_active,
      EXISTS(SELECT 1 FROM l z WHERE z.exchange=cs.exchange AND z.code=cs.code AND cs.exit_date>=z.listed_from AND (z.listed_to_exclusive IS NULL OR cs.exit_date<z.listed_to_exclusive)) exit_active
      FROM cs""")
    cr=one(con,f"""SELECT count(*)::BIGINT candidate_rows,
      count(*) FILTER(WHERE c.entry_date IS NULL OR c.exit_date IS NULL)::BIGINT missing_schedule_rows,
      count(*) FILTER(WHERE NOT c.decision_active)::BIGINT decision_lifecycle_inactive_rows,
      count(*) FILTER(WHERE NOT c.entry_active)::BIGINT entry_lifecycle_inactive_rows,
      count(*) FILTER(WHERE NOT c.exit_active)::BIGINT exit_lifecycle_inactive_rows,
      count(*) FILTER(WHERE c.decision_active AND (ds.tradable IS NULL OR ds.risk_warning IS NULL OR ds.preclose IS NULL OR ds.limit_rule IS NULL))::BIGINT missing_decision_core_state_active_rows,
      count(*) FILTER(WHERE c.entry_active AND (es.tradable IS NULL OR es.risk_warning IS NULL OR es.preclose IS NULL OR es.limit_rule IS NULL))::BIGINT missing_entry_core_state_active_rows,
      count(*) FILTER(WHERE c.exit_active AND (xs.tradable IS NULL OR xs.risk_warning IS NULL OR xs.preclose IS NULL OR xs.limit_rule IS NULL))::BIGINT missing_exit_core_state_active_rows,
      count(*) FILTER(WHERE c.decision_active AND ds.limit_rule NOT IN {na} AND (ds.limit_up_rate IS NULL OR ds.limit_down_rate IS NULL))::BIGINT decision_applicable_rate_missing_active_rows,
      count(*) FILTER(WHERE c.entry_active AND es.limit_rule NOT IN {na} AND (es.limit_up_rate IS NULL OR es.limit_down_rate IS NULL))::BIGINT entry_applicable_rate_missing_active_rows,
      count(*) FILTER(WHERE c.exit_active AND xs.limit_rule NOT IN {na} AND (xs.limit_up_rate IS NULL OR xs.limit_down_rate IS NULL))::BIGINT exit_applicable_rate_missing_active_rows,
      count(*) FILTER(WHERE c.decision_active AND ds.tradable=1 AND dm.code IS NULL)::BIGINT tradable_decision_market_missing_active_rows,
      count(*) FILTER(WHERE c.entry_active AND es.tradable=1 AND em.code IS NULL)::BIGINT tradable_entry_market_missing_active_rows,
      count(*) FILTER(WHERE c.exit_active AND xs.tradable=1 AND xm.code IS NULL)::BIGINT tradable_exit_market_missing_active_rows,
      count(*) FILTER(WHERE c.decision_active AND dm.code IS NULL AND NOT (ds.tradable=0 AND ds.limit_rule='SUSPENDED'))::BIGINT invalid_decision_market_missing_active_rows,
      count(*) FILTER(WHERE c.entry_active AND em.code IS NULL AND NOT (es.tradable=0 AND es.limit_rule='SUSPENDED'))::BIGINT invalid_entry_market_missing_active_rows,
      count(*) FILTER(WHERE c.exit_active AND xm.code IS NULL AND NOT (xs.tradable=0 AND xs.limit_rule='SUSPENDED'))::BIGINT invalid_exit_market_missing_active_rows,
      count(*) FILTER(WHERE NOT c.entry_active AND em.code IS NOT NULL)::BIGINT lifecycle_inactive_entry_market_present_rows,
      count(*) FILTER(WHERE NOT c.exit_active AND xm.code IS NOT NULL)::BIGINT lifecycle_inactive_exit_market_present_rows
      FROM cr0 c LEFT JOIN s ds ON c.trade_date=ds.trade_date AND c.exchange=ds.exchange AND c.code=ds.code
      LEFT JOIN s es ON c.entry_date=es.trade_date AND c.exchange=es.exchange AND c.code=es.code
      LEFT JOIN s xs ON c.exit_date=xs.trade_date AND c.exchange=xs.exchange AND c.code=xs.code
      LEFT JOIN m dm ON c.trade_date=dm.trade_date AND c.exchange=dm.exchange AND c.code=dm.code
      LEFT JOIN m em ON c.entry_date=em.trade_date AND c.exchange=em.exchange AND c.code=em.code
      LEFT JOIN m xm ON c.exit_date=xm.trade_date AND c.exchange=xm.exchange AND c.code=xm.code""")
    required_zero=[k for k in cr if k not in {'candidate_rows','entry_lifecycle_inactive_rows','exit_lifecycle_inactive_rows'}]
    if int(cr['candidate_rows'])<=0 or any(int(cr[k])!=0 for k in required_zero): raise ValueError('lifecycle-aware candidate readiness failed: '+json.dumps(cr,default=str))
    if int(cr['entry_lifecycle_inactive_rows'])!=52 or int(cr['exit_lifecycle_inactive_rows'])!=1217:
        raise ValueError('frozen lifecycle-gap counts drift from independent diagnostic')
    dh={o['features']:sha(fp),o['market']:sha(mp),o['execution_state']:sha(sp),o['lifecycle']:sha(lp)}
    manifest={
      'schema_version':4,'status':'PHYSICALLY_OOS_ONLY_PRE_PREDICTION_NON_LABEL','boundary_contract_fingerprint':BOUNDARY_FP,
      'boundary_implementation':'V1_2_LIFECYCLE_AWARE_CANDIDATE_READINESS','source_cv_authorization_fingerprint':SOURCE_AUTH_FP,
      'decision_start':start,'decision_end':end,'final_lockbox_start':b['scope']['final_lockbox_start'],'source_artifacts':b['inputs'],
      'feature_columns':list(src['fingerprint_basis']['feature_columns']),'features':features,'market':market,'execution_state':state,
      'execution_state_applicability':{'na_limit_rules':list(NA_LIMIT_RULES),'null_limit_rates_mean_not_applicable_not_imputed':True},
      'lifecycle':lifecycle,'lifecycle_candidate_semantics':{'authority':'SEALED_G2_LIFECYCLE_INTERVALS','inactive_entry_or_exit_is_explicit_nontradable_not_missing_data':True,'state_or_price_imputation_for_lifecycle_inactive_forbidden':True,'missing_g4_while_lifecycle_active_fails_closed':True},
      'structural_readiness':structural,'runtime_candidate_path_readiness':cr,'data_sha256':dh,
      'guards':{'broad_feature_matrix_available_downstream':False,'broad_g3_available_downstream':False,'broad_g4_available_downstream':False,'raw_g5_available_downstream':False,'raw_g2_available_downstream':False,'post_oos_feature_rows':0,'post_oos_market_rows':0,'post_oos_execution_state_rows':0,'post_oos_lifecycle_delist_rows':0,'oos_prediction_executed':False,'oos_label_constructed':False,'oos_label_value_read':False,'model_loaded':False,'authorization_consumed':False,'fit_retrain_tune_reselect_executed':False,'final_lockbox_accessed':False,'business_metrics_computed':False}
    }
    mpath=out/o['manifest']; mpath.write_text(json.dumps(manifest,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    hh={**dh,o['manifest']:sha(mpath)}; (out/o['hashes']).write_text(json.dumps(hh,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':manifest['status'],'implementation':manifest['boundary_implementation'],'runtime_candidate_path_readiness':cr,'authorization_consumed':False,'oos_prediction_executed':False},indent=2,default=str))
    return 0
if __name__=='__main__': raise SystemExit(main())
