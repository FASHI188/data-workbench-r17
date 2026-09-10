#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from typing import Any
BOUNDARY_FP='67e8555d3a9212a003a8293dc381cce0f7294917ef72875fed3218f240e0c255'
SOURCE_AUTH_FP='2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c'
NA_LIMIT_RULES=('SUSPENDED','IPO_FIRST5_NO_LIMIT','DELISTING_15DAY_FIRST_DAY_NO_LIMIT')
def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def canon(x:Any)->str:return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def q(s:str)->str:return "'"+s.replace("'","''")+"'"
def sl(xs):return '('+','.join(q(x) for x in xs)+')'
def row(con,sql):
 c=con.execute(sql);return dict(zip([d[0] for d in c.description],c.fetchone()))
def main()->int:
 ap=argparse.ArgumentParser()
 for n in ['contract','source-cv-authorization','source-verification','package-dir','out']:ap.add_argument('--'+n,required=True)
 a=ap.parse_args();import duckdb
 failures=[];checks={}
 def ck(n,v,d=''):
  checks[n]=bool(v)
  if not v:failures.append(n+((': '+d) if d else ''))
 try:
  bc=json.loads(Path(a.contract).read_text(encoding='utf-8'));b=bc['fingerprint_basis'];ck('boundary_contract',bc.get('fingerprint')==BOUNDARY_FP and canon(b)==BOUNDARY_FP)
  src=json.loads(Path(a.source_cv_authorization).read_text(encoding='utf-8'));ck('source_auth',src.get('fingerprint')==SOURCE_AUTH_FP and canon(src['fingerprint_basis'])==SOURCE_AUTH_FP)
  sv=json.loads(Path(a.source_verification).read_text(encoding='utf-8'));ck('source_verification',sv.get('status')=='VERIFIED' and sv.get('boundary_contract_fingerprint')==BOUNDARY_FP)
  for k,exp in b['inputs'].items():
   got=sv.get('artifacts',{}).get(k,{});ck('source_'+k,int(got.get('artifact_id',-1))==int(exp['artifact_id']) and got.get('archive_sha256')==exp['artifact_zip_sha256'] and got.get('verified') is True)
  root=Path(a.package_dir);o=b['outputs'];paths={k:root/o[k] for k in ['features','market','execution_state','lifecycle','manifest','hashes']}
  for k,p in paths.items():ck('exists_'+k,p.is_file())
  m=json.loads(paths['manifest'].read_text(encoding='utf-8'));hh=json.loads(paths['hashes'].read_text(encoding='utf-8'))
  ck('manifest_status',m.get('status')=='PHYSICALLY_OOS_ONLY_PRE_PREDICTION_NON_LABEL' and m.get('boundary_implementation')=='V1_2_LIFECYCLE_AWARE_CANDIDATE_READINESS')
  ck('manifest_binding',m.get('boundary_contract_fingerprint')==BOUNDARY_FP and m.get('source_cv_authorization_fingerprint')==SOURCE_AUTH_FP)
  expected_hash_names={o['features'],o['market'],o['execution_state'],o['lifecycle'],o['manifest']};ck('hash_names',set(hh)==expected_hash_names,str(set(hh)))
  for k,p in [('features',paths['features']),('market',paths['market']),('execution_state',paths['execution_state']),('lifecycle',paths['lifecycle']),('manifest',paths['manifest'])]:ck('hash_'+k,hh.get(p.name)==sha(p))
  g=m.get('guards',{})
  for k in ['broad_feature_matrix_available_downstream','broad_g3_available_downstream','broad_g4_available_downstream','raw_g5_available_downstream','raw_g2_available_downstream','oos_prediction_executed','oos_label_constructed','oos_label_value_read','model_loaded','authorization_consumed','fit_retrain_tune_reselect_executed','final_lockbox_accessed','business_metrics_computed']:ck('guard_'+k,g.get(k) is False)
  for k in ['post_oos_feature_rows','post_oos_market_rows','post_oos_execution_state_rows','post_oos_lifecycle_delist_rows']:ck('guard_'+k,int(g.get(k,-1))==0)
  sem=m.get('lifecycle_candidate_semantics',{});ck('lifecycle_semantics',sem.get('authority')=='SEALED_G2_LIFECYCLE_INTERVALS' and sem.get('inactive_entry_or_exit_is_explicit_nontradable_not_missing_data') is True and sem.get('state_or_price_imputation_for_lifecycle_inactive_forbidden') is True and sem.get('missing_g4_while_lifecycle_active_fails_closed') is True)
  con=duckdb.connect();con.execute('PRAGMA threads=2')
  for v,k in [('f','features'),('m','market'),('s','execution_state'),('l','lifecycle')]:con.execute(f'CREATE TEMP VIEW {v} AS SELECT * FROM read_parquet({q(str(paths[k]))})')
  start=b['scope']['decision_start'];end=b['scope']['decision_end'];econ=b['scope']['latest_labelable_decision'];na=sl(NA_LIMIT_RULES)
  basic={}
  for v,n in [('f','features'),('m','market'),('s','execution_state')]:
   x=row(con,f"SELECT count(*)::BIGINT row_count,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,min(trade_date) date_min,max(trade_date) date_max,count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT outside_rows FROM {v}");basic[n]=x;ck(n+'_population',int(x['row_count'])>0 and int(x['row_count'])==int(x['unique_keys']) and str(x['date_min'])==start and str(x['date_max'])==end and int(x['outside_rows'])==0,str(x))
  con.execute("CREATE TEMP TABLE cal AS SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 session_idx FROM (SELECT DISTINCT trade_date FROM m) ORDER BY trade_date")
  con.execute(f"CREATE TEMP TABLE cs AS SELECT f.trade_date,f.exchange,f.code,e.trade_date entry_date,x.trade_date exit_date FROM (SELECT trade_date,exchange,code FROM f WHERE trade_date<=DATE {q(econ)}) f JOIN cal c ON f.trade_date=c.trade_date LEFT JOIN cal e ON e.session_idx=c.session_idx+1 LEFT JOIN cal x ON x.session_idx=c.session_idx+20")
  con.execute("""CREATE TEMP TABLE c2 AS SELECT cs.*,
   EXISTS(SELECT 1 FROM l z WHERE z.exchange=cs.exchange AND z.code=cs.code AND cs.trade_date>=z.listed_from AND (z.listed_to_exclusive IS NULL OR cs.trade_date<z.listed_to_exclusive)) decision_active,
   EXISTS(SELECT 1 FROM l z WHERE z.exchange=cs.exchange AND z.code=cs.code AND cs.entry_date>=z.listed_from AND (z.listed_to_exclusive IS NULL OR cs.entry_date<z.listed_to_exclusive)) entry_active,
   EXISTS(SELECT 1 FROM l z WHERE z.exchange=cs.exchange AND z.code=cs.code AND cs.exit_date>=z.listed_from AND (z.listed_to_exclusive IS NULL OR cs.exit_date<z.listed_to_exclusive)) exit_active FROM cs""")
  cr=row(con,f"""SELECT count(*)::BIGINT candidate_rows,count(*) FILTER(WHERE c.entry_date IS NULL OR c.exit_date IS NULL)::BIGINT missing_schedule_rows,
   count(*) FILTER(WHERE NOT c.decision_active)::BIGINT decision_lifecycle_inactive_rows,count(*) FILTER(WHERE NOT c.entry_active)::BIGINT entry_lifecycle_inactive_rows,count(*) FILTER(WHERE NOT c.exit_active)::BIGINT exit_lifecycle_inactive_rows,
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
   FROM c2 c LEFT JOIN s ds ON c.trade_date=ds.trade_date AND c.exchange=ds.exchange AND c.code=ds.code LEFT JOIN s es ON c.entry_date=es.trade_date AND c.exchange=es.exchange AND c.code=es.code LEFT JOIN s xs ON c.exit_date=xs.trade_date AND c.exchange=xs.exchange AND c.code=xs.code LEFT JOIN m dm ON c.trade_date=dm.trade_date AND c.exchange=dm.exchange AND c.code=dm.code LEFT JOIN m em ON c.entry_date=em.trade_date AND c.exchange=em.exchange AND c.code=em.code LEFT JOIN m xm ON c.exit_date=xm.trade_date AND c.exchange=xm.exchange AND c.code=xm.code""")
  ck('lifecycle_counts',int(cr['entry_lifecycle_inactive_rows'])==52 and int(cr['exit_lifecycle_inactive_rows'])==1217,str(cr))
  for k,v in cr.items():
   if k not in {'candidate_rows','entry_lifecycle_inactive_rows','exit_lifecycle_inactive_rows'}:ck('candidate_'+k,int(v)==0,str(cr))
  mr=m.get('runtime_candidate_path_readiness',{});ck('manifest_candidate_readiness',mr==cr,f'manifest={mr} recomputed={cr}')
  result={'schema_version':4,'status':'PASS' if not failures else 'FAIL','pass':not failures,'boundary_contract_fingerprint':BOUNDARY_FP,'boundary_implementation':'V1_2_LIFECYCLE_AWARE_CANDIDATE_READINESS','checks':checks,'failed_checks':failures,'runtime_candidate_path_readiness':cr,'post_oos_rows_observed':sum(int(x['outside_rows']) for x in basic.values()),'oos_prediction_executed':False,'oos_label_constructed':False,'oos_label_value_read':False,'model_loaded':False,'authorization_consumed':False,'final_lockbox_accessed':False}
 except Exception as e:
  failures.append(f'exception: {type(e).__name__}: {e}');result={'schema_version':4,'status':'FAIL','pass':False,'checks':checks,'failed_checks':failures}
 p=Path(a.out);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2,default=str));return 0 if result.get('pass') else 2
if __name__=='__main__':raise SystemExit(main())
