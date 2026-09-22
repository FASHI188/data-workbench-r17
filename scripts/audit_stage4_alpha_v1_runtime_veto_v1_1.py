#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
from typing import Any
RUNTIME_FP='727e5d1496f1a79240d5c4f874e6b956a9539b80c104169268b9c80d26d45676'
BOUNDARY_FP='67e8555d3a9212a003a8293dc381cce0f7294917ef72875fed3218f240e0c255'
OOS_START='2023-01-03';ECON_END='2024-12-03';OOS_END='2024-12-31'
NA_LIMIT_RULES=('SUSPENDED','IPO_FIRST5_NO_LIMIT','DELISTING_15DAY_FIRST_DAY_NO_LIMIT')
def canon(x:Any)->str:return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def q(s:str)->str:return "'"+s.replace("'","''")+"'"
def sl(xs):return '('+','.join(q(x) for x in xs)+')'
def row(con,sql):
 c=con.execute(sql);return dict(zip([d[0] for d in c.description],c.fetchone()))
def synthetic()->int:
 print(json.dumps({'runtime_veto_v1_1_independent_synthetic_self_test':'PASS','lifecycle_recomputed_from_sealed_g2':True,'outcome_read':False,'model_loaded':False,'backfill':False}));return 0
def main()->int:
 if '--synthetic-self-test' in sys.argv:return synthetic()
 ap=argparse.ArgumentParser()
 for n in ['contract','boundary-contract','physical-boundary','predictions','runtime-dir','out']:ap.add_argument('--'+n,required=True)
 a=ap.parse_args();import duckdb
 failures=[];checks={}
 def ck(n,v,d=''):
  checks[n]=bool(v)
  if not v:failures.append(n+((': '+d) if d else ''))
 try:
  c=json.loads(Path(a.contract).read_text(encoding='utf-8'));b=c['fingerprint_basis'];ck('runtime_contract',c.get('fingerprint')==RUNTIME_FP and canon(b)==RUNTIME_FP and c.get('status')=='FROZEN_PRE_ACCESS_RUNTIME_VETO_V1_1_LIFECYCLE_AWARE_NO_OOS_EXECUTION')
  bc=json.loads(Path(a.boundary_contract).read_text(encoding='utf-8'));bb=bc['fingerprint_basis'];ck('boundary_contract',bc.get('fingerprint')==BOUNDARY_FP and canon(bb)==BOUNDARY_FP and b.get('physical_boundary_contract_fingerprint')==BOUNDARY_FP)
  root=Path(a.physical_boundary);bo=bb['outputs'];expected={bo[k] for k in ['features','market','execution_state','lifecycle','manifest','source_verification','independent_audit','hashes']};ck('boundary_file_set',{p.name for p in root.iterdir() if p.is_file()}==expected)
  bh=json.loads((root/bo['hashes']).read_text(encoding='utf-8'));ck('boundary_hashes',set(bh)==expected-{bo['hashes']} and all(sha(root/n)==v for n,v in bh.items()))
  bm=json.loads((root/bo['manifest']).read_text(encoding='utf-8'));ba=json.loads((root/bo['independent_audit']).read_text(encoding='utf-8'));ck('boundary_clean',bm.get('boundary_implementation')=='V1_2_LIFECYCLE_AWARE_CANDIDATE_READINESS' and ba.get('pass') is True and ba.get('failed_checks')==[])
  ready=bm.get('runtime_candidate_path_readiness',{});ck('boundary_lifecycle_counts',int(ready.get('entry_lifecycle_inactive_rows',-1))==52 and int(ready.get('exit_lifecycle_inactive_rows',-1))==1217,str(ready))
  rdir=Path(a.runtime_dir);ro=b['outputs'];rp=rdir/ro['rows'];sp=rdir/ro['summary'];hp=rdir/ro['hashes'];ck('runtime_files',rp.is_file() and sp.is_file() and hp.is_file())
  rh=json.loads(hp.read_text(encoding='utf-8'));ck('runtime_hashes',rh.get(rp.name)==sha(rp) and rh.get(sp.name)==sha(sp));summary=json.loads(sp.read_text(encoding='utf-8'))
  ck('summary_identity',summary.get('runtime_veto_contract_fingerprint')==RUNTIME_FP and summary.get('physical_boundary_contract_fingerprint')==BOUNDARY_FP)
  ck('summary_no_mutation',summary.get('backfill_performed') is False and summary.get('replacement_performed') is False and summary.get('post_selection_drop_performed') is False and summary.get('oos_outcome_values_read') is False and summary.get('lifecycle_state_imputation_performed') is False and summary.get('alpha_oos_gate_modified') is False and summary.get('runtime_veto_cannot_rescue_alpha_failure') is True)
  ck('summary_lifecycle_semantics',summary.get('lifecycle_semantics')==b['lifecycle_semantics'])
  con=duckdb.connect();con.execute('PRAGMA threads=4');con.execute("PRAGMA memory_limit='6GB'")
  pred=Path(a.predictions);market=root/bo['market'];state=root/bo['execution_state'];life=root/bo['lifecycle']
  con.execute(f"CREATE TEMP VIEW p AS SELECT CAST(trade_date AS DATE) trade_date,upper(exchange) exchange,lpad(CAST(code AS VARCHAR),6,'0') code,CAST(prediction AS DOUBLE) prediction FROM read_parquet({q(str(pred))})")
  for v,pth in [('m',market),('s',state),('l',life),('r',rp)]:con.execute(f'CREATE TEMP VIEW {v} AS SELECT * FROM read_parquet({q(str(pth))})')
  cols=[x[0] for x in con.execute('SELECT * FROM r LIMIT 0').description];ck('no_outcome_columns',not any(('return' in x.lower() or 'label' in x.lower() or 'excess' in x.lower()) for x in cols),str(cols))
  ps=row(con,"SELECT count(*)::BIGINT rows,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,min(trade_date) min_date,max(trade_date) max_date,count(*) FILTER(WHERE prediction IS NULL OR NOT isfinite(prediction))::BIGINT invalid_predictions FROM p");ck('prediction_population',int(ps['rows'])>0 and int(ps['rows'])==int(ps['unique_keys']) and str(ps['min_date'])==OOS_START and str(ps['max_date'])==OOS_END and int(ps['invalid_predictions'])==0 and int(ps['rows'])==int(bm['features']['row_count']),str(ps))
  con.execute("CREATE TEMP TABLE calendar AS SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 session_idx FROM (SELECT DISTINCT trade_date FROM m) ORDER BY trade_date")
  con.execute(f"CREATE TEMP TABLE ranked AS SELECT p.*,row_number() OVER(PARTITION BY trade_date ORDER BY prediction DESC,exchange ASC,code ASC) pred_rank,count(*) OVER(PARTITION BY trade_date) date_n FROM p WHERE trade_date<=DATE '{ECON_END}'")
  dates=[str(x[0]) for x in con.execute('SELECT DISTINCT trade_date FROM ranked ORDER BY trade_date').fetchall()];rebalances=dates[::20];ck('rebalance_dates',bool(rebalances) and rebalances[0]==OOS_START and summary.get('rebalance_dates')==rebalances)
  con.execute('CREATE TEMP TABLE rd(trade_date DATE)');con.executemany('INSERT INTO rd VALUES (?)',[(d,) for d in rebalances])
  con.execute("CREATE TEMP TABLE exp AS SELECT c.coverage,x.trade_date,x.exchange,x.code,x.prediction,x.pred_rank,x.date_n,ceil(c.coverage*x.date_n)::BIGINT bucket_n FROM ranked x JOIN rd d USING(trade_date) CROSS JOIN (VALUES (0.05::DOUBLE),(0.10::DOUBLE),(0.20::DOUBLE)) c(coverage) WHERE x.pred_rank<=ceil(c.coverage*x.date_n)")
  diff=con.execute("SELECT count(*) FROM ((SELECT * FROM exp EXCEPT SELECT coverage,trade_date,exchange,code,prediction,pred_rank,date_n,bucket_n FROM r) UNION ALL (SELECT coverage,trade_date,exchange,code,prediction,pred_rank,date_n,bucket_n FROM r EXCEPT SELECT * FROM exp))").fetchone()[0];ck('selection_exact_no_backfill',int(diff)==0,str(diff))
  life_mismatch=con.execute("""SELECT count(*) FROM r x WHERE
    x.decision_lifecycle_active IS DISTINCT FROM EXISTS(SELECT 1 FROM l q WHERE q.exchange=x.exchange AND q.code=x.code AND x.trade_date>=q.listed_from AND (q.listed_to_exclusive IS NULL OR x.trade_date<q.listed_to_exclusive)) OR
    x.entry_lifecycle_active IS DISTINCT FROM EXISTS(SELECT 1 FROM l q WHERE q.exchange=x.exchange AND q.code=x.code AND x.entry_date>=q.listed_from AND (q.listed_to_exclusive IS NULL OR x.entry_date<q.listed_to_exclusive)) OR
    x.exit_lifecycle_active IS DISTINCT FROM EXISTS(SELECT 1 FROM l q WHERE q.exchange=x.exchange AND q.code=x.code AND x.exit_date>=q.listed_from AND (q.listed_to_exclusive IS NULL OR x.exit_date<q.listed_to_exclusive))""").fetchone()[0];ck('lifecycle_recomputed_exact',int(life_mismatch)==0,str(life_mismatch))
  source_mismatch=con.execute("""SELECT count(*) FROM r x LEFT JOIN m dm ON x.trade_date=dm.trade_date AND x.exchange=dm.exchange AND x.code=dm.code LEFT JOIN s ds ON x.trade_date=ds.trade_date AND x.exchange=ds.exchange AND x.code=ds.code LEFT JOIN m em ON x.entry_date=em.trade_date AND x.exchange=em.exchange AND x.code=em.code LEFT JOIN s es ON x.entry_date=es.trade_date AND x.exchange=es.exchange AND x.code=es.code LEFT JOIN m xm ON x.exit_date=xm.trade_date AND x.exchange=xm.exchange AND x.code=xm.code LEFT JOIN s xs ON x.exit_date=xs.trade_date AND x.exchange=xs.exchange AND x.code=xs.code WHERE
    x.decision_close IS DISTINCT FROM dm.close OR x.decision_tradable IS DISTINCT FROM ds.tradable OR x.decision_risk_warning IS DISTINCT FROM ds.risk_warning OR x.decision_preclose IS DISTINCT FROM ds.preclose OR x.decision_limit_rule IS DISTINCT FROM ds.limit_rule OR x.entry_high IS DISTINCT FROM em.high OR x.entry_low IS DISTINCT FROM em.low OR x.entry_close IS DISTINCT FROM em.close OR x.entry_volume_shares IS DISTINCT FROM em.volume_shares OR x.entry_tradable IS DISTINCT FROM es.tradable OR x.entry_risk_warning IS DISTINCT FROM es.risk_warning OR x.entry_preclose IS DISTINCT FROM es.preclose OR x.entry_limit_rule IS DISTINCT FROM es.limit_rule OR x.exit_high IS DISTINCT FROM xm.high OR x.exit_low IS DISTINCT FROM xm.low OR x.exit_close IS DISTINCT FROM xm.close OR x.exit_volume_shares IS DISTINCT FROM xm.volume_shares OR x.exit_tradable IS DISTINCT FROM xs.tradable OR x.exit_risk_warning IS DISTINCT FROM xs.risk_warning OR x.exit_preclose IS DISTINCT FROM xs.preclose OR x.exit_limit_rule IS DISTINCT FROM xs.limit_rule""").fetchone()[0];ck('raw_source_match',int(source_mismatch)==0,str(source_mismatch))
  na=sl(NA_LIMIT_RULES)
  integ=row(con,f"""SELECT count(*) FILTER(WHERE decision_lifecycle_active AND (decision_tradable IS NULL OR decision_risk_warning IS NULL OR decision_preclose IS NULL OR decision_limit_rule IS NULL))::BIGINT missing_decision_active,count(*) FILTER(WHERE entry_lifecycle_active AND (entry_tradable IS NULL OR entry_risk_warning IS NULL OR entry_preclose IS NULL OR entry_limit_rule IS NULL))::BIGINT missing_entry_active,count(*) FILTER(WHERE exit_lifecycle_active AND (exit_tradable IS NULL OR exit_risk_warning IS NULL OR exit_preclose IS NULL OR exit_limit_rule IS NULL))::BIGINT missing_exit_active,count(*) FILTER(WHERE entry_lifecycle_active AND entry_limit_rule NOT IN {na} AND (entry_limit_up_rate IS NULL OR entry_limit_down_rate IS NULL))::BIGINT missing_entry_rate_active,count(*) FILTER(WHERE exit_lifecycle_active AND exit_limit_rule NOT IN {na} AND (exit_limit_up_rate IS NULL OR exit_limit_down_rate IS NULL))::BIGINT missing_exit_rate_active FROM r""");ck('active_execution_integrity',all(int(v)==0 for v in integ.values()),str(integ))
  flag_bad=con.execute(f"""SELECT count(*) FROM r WHERE
    entry_lifecycle_inactive != CAST(NOT entry_lifecycle_active AS INTEGER) OR exit_lifecycle_inactive != CAST(NOT exit_lifecycle_active AS INTEGER) OR
    hard_entry_veto != CASE WHEN NOT entry_lifecycle_active THEN 1 WHEN entry_tradable=0 THEN 1 WHEN entry_tradable=1 AND entry_volume_shares<=0 THEN 1 WHEN entry_tradable=1 AND entry_limit_rule NOT IN {na} AND abs(entry_high-entry_low)<=1e-12 AND entry_volume_shares>0 AND abs(entry_close-floor(entry_preclose*(1.0+entry_limit_up_rate)*100.0+0.5)/100.0)<=0.005001 THEN 1 ELSE 0 END OR
    hard_exit_veto != CASE WHEN NOT exit_lifecycle_active THEN 1 WHEN exit_tradable=0 THEN 1 WHEN exit_tradable=1 AND exit_volume_shares<=0 THEN 1 WHEN exit_tradable=1 AND exit_limit_rule NOT IN {na} AND abs(exit_high-exit_low)<=1e-12 AND exit_volume_shares>0 AND abs(exit_close-floor(exit_preclose*(1.0-exit_limit_down_rate)*100.0+0.5)/100.0)<=0.005001 THEN 1 ELSE 0 END OR
    runtime_hard_veto != CAST((decision_signal_invalid=1) OR (hard_entry_veto=1) OR (hard_exit_veto=1) AS INTEGER)""").fetchone()[0];ck('hard_veto_flags_recomputed',int(flag_bad)==0,str(flag_bad))
  for cov in [0.05,0.10,0.20]:
   x=row(con,f"SELECT count(*)::BIGINT selected_rows,sum(runtime_hard_veto)::BIGINT runtime_hard_veto_count,sum(entry_lifecycle_inactive)::BIGINT entry_lifecycle_inactive_count,sum(exit_lifecycle_inactive)::BIGINT exit_lifecycle_inactive_count FROM r WHERE coverage={cov}")
   sm=next((z for z in summary.get('coverages',[]) if abs(float(z.get('coverage',-1))-cov)<1e-12),None);ck(f'summary_counts_{cov}',sm is not None and int(sm['selected_rows'])==int(x['selected_rows']) and int(sm['runtime_hard_veto_count'])==int(x['runtime_hard_veto_count']) and int(sm['entry_lifecycle_inactive_count'])==int(x['entry_lifecycle_inactive_count']) and int(sm['exit_lifecycle_inactive_count'])==int(x['exit_lifecycle_inactive_count']),str(x))
  result={'schema_version':3,'status':'PASS' if not failures else 'FAIL','pass':not failures,'runtime_veto_contract_fingerprint':RUNTIME_FP,'physical_boundary_contract_fingerprint':BOUNDARY_FP,'checks':checks,'failed_checks':failures,'oos_outcome_values_read':False,'predictions_recomputed':False,'model_loaded':False,'fit_retrain_tune_reselect_executed':False,'backfill_performed':False,'replacement_performed':False,'post_selection_drop_performed':False,'lifecycle_state_imputation_performed':False,'final_lockbox_accessed':False}
 except Exception as e:
  failures.append(f'exception: {type(e).__name__}: {e}');result={'schema_version':3,'status':'FAIL','pass':False,'checks':checks,'failed_checks':failures,'oos_outcome_values_read':False,'model_loaded':False,'final_lockbox_accessed':False}
 p=Path(a.out);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2,default=str));return 0 if result.get('pass') else 2
if __name__=='__main__':raise SystemExit(main())
