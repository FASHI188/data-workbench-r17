#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,math,sys
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
def one(con,sql):
 c=con.execute(sql);return dict(zip([d[0] for d in c.description],c.fetchone()))
def synthetic()->int:
 assert (0 if True else None)==0
 for r in ('IPO_FIRST5_NO_LIMIT','DELISTING_15DAY_FIRST_DAY_NO_LIMIT'):assert r in NA_LIMIT_RULES
 print(json.dumps({'runtime_veto_v1_1_synthetic_self_test':'PASS','lifecycle_inactive_entry_hard_veto':True,'lifecycle_inactive_exit_hard_veto':True,'state_imputation':False,'backfill':False,'replacement':False,'oos_outcome_read':False}));return 0
def main()->int:
 if '--synthetic-self-test' in sys.argv:return synthetic()
 ap=argparse.ArgumentParser()
 for n in ['contract','boundary-contract','physical-boundary','predictions','out']:ap.add_argument('--'+n,required=True)
 a=ap.parse_args();import duckdb
 c=json.loads(Path(a.contract).read_text(encoding='utf-8'));b=c['fingerprint_basis']
 if c.get('fingerprint')!=RUNTIME_FP or canon(b)!=RUNTIME_FP or c.get('status')!='FROZEN_PRE_ACCESS_RUNTIME_VETO_V1_1_LIFECYCLE_AWARE_NO_OOS_EXECUTION':raise ValueError('runtime veto V1.1 contract mismatch')
 if b.get('physical_boundary_contract_fingerprint')!=BOUNDARY_FP:raise ValueError('boundary binding mismatch')
 for k in ['prediction_ranking_frozen','selected_bucket_membership_frozen','backfill_forbidden','replacement_forbidden','post_selection_drop_forbidden','score_filtering_forbidden','oos_fit_retrain_tune_reselect_forbidden','oos_outcome_values_forbidden','final_lockbox_access_forbidden','runtime_veto_cannot_rescue_alpha_failure']:
  if b['scope'].get(k) is not True:raise ValueError('scope drift: '+k)
 lcsem=b['lifecycle_semantics']
 if lcsem.get('lifecycle_inactive_is_not_missing_data') is not True or lcsem.get('missing_g4_state_while_lifecycle_active')!='FAIL_CLOSED_INTEGRITY_ERROR':raise ValueError('lifecycle semantics drift')
 bc=json.loads(Path(a.boundary_contract).read_text(encoding='utf-8'));bb=bc['fingerprint_basis']
 if bc.get('fingerprint')!=BOUNDARY_FP or canon(bb)!=BOUNDARY_FP:raise ValueError('physical boundary contract mismatch')
 root=Path(a.physical_boundary);bo=bb['outputs'];expected={bo[k] for k in ['features','market','execution_state','lifecycle','manifest','source_verification','independent_audit','hashes']}
 if {p.name for p in root.iterdir() if p.is_file()}!=expected:raise ValueError('physical package file set mismatch')
 hh=json.loads((root/bo['hashes']).read_text(encoding='utf-8'))
 if set(hh)!=expected-{bo['hashes']} or any(sha(root/n)!=v for n,v in hh.items()):raise ValueError('physical package hash mismatch')
 bm=json.loads((root/bo['manifest']).read_text(encoding='utf-8'));ba=json.loads((root/bo['independent_audit']).read_text(encoding='utf-8'))
 if bm.get('status')!='PHYSICALLY_OOS_ONLY_PRE_PREDICTION_NON_LABEL' or bm.get('boundary_implementation')!='V1_2_LIFECYCLE_AWARE_CANDIDATE_READINESS':raise ValueError('lifecycle-aware physical manifest missing')
 if ba.get('pass') is not True or ba.get('failed_checks')!=[]:raise ValueError('physical independent audit failed')
 ready=bm.get('runtime_candidate_path_readiness',{})
 if int(ready.get('candidate_rows',0))<=0 or int(ready.get('entry_lifecycle_inactive_rows',-1))!=52 or int(ready.get('exit_lifecycle_inactive_rows',-1))!=1217:raise ValueError('candidate lifecycle evidence mismatch')
 for k,v in ready.items():
  if k not in {'candidate_rows','entry_lifecycle_inactive_rows','exit_lifecycle_inactive_rows'} and int(v)!=0:raise ValueError('active candidate readiness not clean: '+k)
 out=Path(a.out);out.mkdir(parents=True,exist_ok=True);pred=Path(a.predictions);market=root/bo['market'];state=root/bo['execution_state'];lifecycle=root/bo['lifecycle']
 con=duckdb.connect();con.execute('PRAGMA threads=4');con.execute("PRAGMA memory_limit='6GB'")
 con.execute(f"CREATE TEMP VIEW p AS SELECT CAST(trade_date AS DATE) trade_date,upper(exchange) exchange,lpad(CAST(code AS VARCHAR),6,'0') code,CAST(prediction AS DOUBLE) prediction FROM read_parquet({q(str(pred))})")
 for v,pth in [('m',market),('s',state),('l',lifecycle)]:con.execute(f'CREATE TEMP VIEW {v} AS SELECT * FROM read_parquet({q(str(pth))})')
 ps=one(con,"SELECT count(*)::BIGINT rows,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,min(trade_date) min_date,max(trade_date) max_date,count(*) FILTER(WHERE prediction IS NULL OR NOT isfinite(prediction))::BIGINT invalid_predictions FROM p")
 if int(ps['rows'])<=0 or int(ps['rows'])!=int(ps['unique_keys']) or str(ps['min_date'])!=OOS_START or str(ps['max_date'])!=OOS_END or int(ps['invalid_predictions'])!=0 or int(ps['rows'])!=int(bm['features']['row_count']):raise ValueError('prediction population invalid')
 con.execute("CREATE TEMP TABLE calendar AS SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 session_idx FROM (SELECT DISTINCT trade_date FROM m) ORDER BY trade_date")
 con.execute(f"CREATE TEMP TABLE ranked AS SELECT p.*,row_number() OVER(PARTITION BY trade_date ORDER BY prediction DESC,exchange ASC,code ASC) pred_rank,count(*) OVER(PARTITION BY trade_date) date_n FROM p WHERE trade_date<=DATE '{ECON_END}'")
 dates=[str(x[0]) for x in con.execute('SELECT DISTINCT trade_date FROM ranked ORDER BY trade_date').fetchall()]
 if not dates or dates[0]!=OOS_START:raise ValueError('rebalance anchor missing')
 rebalances=dates[::int(b['selection']['rebalance_sessions'])];con.execute('CREATE TEMP TABLE rebalance_dates(trade_date DATE)');con.executemany('INSERT INTO rebalance_dates VALUES (?)',[(x,) for x in rebalances])
 con.execute("CREATE TEMP TABLE selected AS SELECT c.coverage,r.*,ceil(c.coverage*r.date_n)::BIGINT bucket_n FROM ranked r JOIN rebalance_dates d USING(trade_date) CROSS JOIN (VALUES (0.05::DOUBLE),(0.10::DOUBLE),(0.20::DOUBLE)) c(coverage) WHERE r.pred_rank<=ceil(c.coverage*r.date_n)")
 con.execute("CREATE TEMP TABLE schedule AS SELECT x.*,cal.session_idx,e.trade_date entry_date,z.trade_date exit_date FROM selected x JOIN calendar cal ON x.trade_date=cal.trade_date LEFT JOIN calendar e ON e.session_idx=cal.session_idx+1 LEFT JOIN calendar z ON z.session_idx=cal.session_idx+20")
 con.execute("""CREATE TEMP TABLE life AS SELECT x.*,
  EXISTS(SELECT 1 FROM l q WHERE q.exchange=x.exchange AND q.code=x.code AND x.trade_date>=q.listed_from AND (q.listed_to_exclusive IS NULL OR x.trade_date<q.listed_to_exclusive)) decision_lifecycle_active,
  EXISTS(SELECT 1 FROM l q WHERE q.exchange=x.exchange AND q.code=x.code AND x.entry_date>=q.listed_from AND (q.listed_to_exclusive IS NULL OR x.entry_date<q.listed_to_exclusive)) entry_lifecycle_active,
  EXISTS(SELECT 1 FROM l q WHERE q.exchange=x.exchange AND q.code=x.code AND x.exit_date>=q.listed_from AND (q.listed_to_exclusive IS NULL OR x.exit_date<q.listed_to_exclusive)) exit_lifecycle_active
  FROM schedule x""")
 con.execute("""CREATE TEMP TABLE joined AS SELECT x.*,
  dm.close decision_close,ds.tradable decision_tradable,ds.risk_warning decision_risk_warning,ds.preclose decision_preclose,ds.limit_rule decision_limit_rule,ds.limit_up_rate decision_limit_up_rate,ds.limit_down_rate decision_limit_down_rate,
  em.high entry_high,em.low entry_low,em.close entry_close,em.volume_shares entry_volume_shares,es.tradable entry_tradable,es.risk_warning entry_risk_warning,es.preclose entry_preclose,es.limit_rule entry_limit_rule,es.limit_up_rate entry_limit_up_rate,es.limit_down_rate entry_limit_down_rate,
  xm.high exit_high,xm.low exit_low,xm.close exit_close,xm.volume_shares exit_volume_shares,xs.tradable exit_tradable,xs.risk_warning exit_risk_warning,xs.preclose exit_preclose,xs.limit_rule exit_limit_rule,xs.limit_up_rate exit_limit_up_rate,xs.limit_down_rate exit_limit_down_rate
  FROM life x LEFT JOIN m dm ON x.trade_date=dm.trade_date AND x.exchange=dm.exchange AND x.code=dm.code LEFT JOIN s ds ON x.trade_date=ds.trade_date AND x.exchange=ds.exchange AND x.code=ds.code
  LEFT JOIN m em ON x.entry_date=em.trade_date AND x.exchange=em.exchange AND x.code=em.code LEFT JOIN s es ON x.entry_date=es.trade_date AND x.exchange=es.exchange AND x.code=es.code
  LEFT JOIN m xm ON x.exit_date=xm.trade_date AND x.exchange=xm.exchange AND x.code=xm.code LEFT JOIN s xs ON x.exit_date=xs.trade_date AND x.exchange=xs.exchange AND x.code=xs.code""")
 na=sl(NA_LIMIT_RULES)
 missing=one(con,f"""SELECT count(*) FILTER(WHERE entry_date IS NULL OR exit_date IS NULL)::BIGINT missing_schedule,
  count(*) FILTER(WHERE decision_lifecycle_active AND (decision_tradable IS NULL OR decision_risk_warning IS NULL OR decision_preclose IS NULL OR decision_limit_rule IS NULL))::BIGINT missing_decision_core_state_active,
  count(*) FILTER(WHERE entry_lifecycle_active AND (entry_tradable IS NULL OR entry_risk_warning IS NULL OR entry_preclose IS NULL OR entry_limit_rule IS NULL))::BIGINT missing_entry_core_state_active,
  count(*) FILTER(WHERE exit_lifecycle_active AND (exit_tradable IS NULL OR exit_risk_warning IS NULL OR exit_preclose IS NULL OR exit_limit_rule IS NULL))::BIGINT missing_exit_core_state_active,
  count(*) FILTER(WHERE entry_lifecycle_active AND entry_limit_rule NOT IN {na} AND (entry_limit_up_rate IS NULL OR entry_limit_down_rate IS NULL))::BIGINT missing_entry_applicable_rate_active,
  count(*) FILTER(WHERE exit_lifecycle_active AND exit_limit_rule NOT IN {na} AND (exit_limit_up_rate IS NULL OR exit_limit_down_rate IS NULL))::BIGINT missing_exit_applicable_rate_active,
  count(*) FILTER(WHERE entry_lifecycle_active AND entry_tradable=1 AND (entry_high IS NULL OR entry_low IS NULL OR entry_close IS NULL OR entry_volume_shares IS NULL))::BIGINT missing_tradable_entry_market_active,
  count(*) FILTER(WHERE exit_lifecycle_active AND exit_tradable=1 AND (exit_high IS NULL OR exit_low IS NULL OR exit_close IS NULL OR exit_volume_shares IS NULL))::BIGINT missing_tradable_exit_market_active,
  count(*) FILTER(WHERE NOT entry_lifecycle_active)::BIGINT lifecycle_inactive_entry_selected,
  count(*) FILTER(WHERE NOT exit_lifecycle_active)::BIGINT lifecycle_inactive_exit_selected FROM joined""")
 for k,v in missing.items():
  if k not in {'lifecycle_inactive_entry_selected','lifecycle_inactive_exit_selected'} and int(v)!=0:raise ValueError('missing active execution state: '+json.dumps(missing))
 con.execute(f"""CREATE TEMP TABLE f0 AS SELECT *,
  CAST(NOT decision_lifecycle_active AS INTEGER) decision_lifecycle_inactive,CAST(NOT entry_lifecycle_active AS INTEGER) entry_lifecycle_inactive,CAST(NOT exit_lifecycle_active AS INTEGER) exit_lifecycle_inactive,
  CASE WHEN decision_lifecycle_active THEN CAST(decision_tradable=0 AS INTEGER) ELSE 1 END decision_signal_invalid,
  CASE WHEN decision_close IS NULL THEN 0 ELSE CAST(decision_close<2.0 AS INTEGER) END decision_low_price_lt2,
  CASE WHEN entry_lifecycle_active AND entry_tradable=1 THEN CAST(abs(entry_high-entry_low)<=1e-12 AS INTEGER) ELSE 0 END entry_one_price,
  CASE WHEN entry_lifecycle_active AND entry_tradable=1 AND entry_limit_rule NOT IN {na} THEN CAST(abs(entry_high-entry_low)<=1e-12 AND entry_volume_shares>0 AND abs(entry_close-floor(entry_preclose*(1.0+entry_limit_up_rate)*100.0+0.5)/100.0)<=0.005001 AS INTEGER) ELSE 0 END entry_one_price_limit_up,
  CASE WHEN entry_lifecycle_active AND entry_tradable=1 AND entry_limit_rule NOT IN {na} THEN CAST(abs(entry_high-entry_low)<=1e-12 AND entry_volume_shares>0 AND abs(entry_close-floor(entry_preclose*(1.0-entry_limit_down_rate)*100.0+0.5)/100.0)<=0.005001 AS INTEGER) ELSE 0 END entry_one_price_limit_down,
  CASE WHEN NOT entry_lifecycle_active THEN 1 WHEN entry_tradable=0 THEN 1 WHEN entry_tradable=1 AND entry_volume_shares<=0 THEN 1 WHEN entry_tradable=1 AND entry_limit_rule NOT IN {na} AND abs(entry_high-entry_low)<=1e-12 AND entry_volume_shares>0 AND abs(entry_close-floor(entry_preclose*(1.0+entry_limit_up_rate)*100.0+0.5)/100.0)<=0.005001 THEN 1 ELSE 0 END hard_entry_veto,
  CASE WHEN exit_lifecycle_active AND exit_tradable=1 THEN CAST(abs(exit_high-exit_low)<=1e-12 AS INTEGER) ELSE 0 END exit_one_price,
  CASE WHEN exit_lifecycle_active AND exit_tradable=1 AND exit_limit_rule NOT IN {na} THEN CAST(abs(exit_high-exit_low)<=1e-12 AND exit_volume_shares>0 AND abs(exit_close-floor(exit_preclose*(1.0-exit_limit_down_rate)*100.0+0.5)/100.0)<=0.005001 AS INTEGER) ELSE 0 END exit_one_price_limit_down,
  CASE WHEN exit_lifecycle_active AND exit_tradable=1 AND exit_limit_rule NOT IN {na} THEN CAST(abs(exit_high-exit_low)<=1e-12 AND exit_volume_shares>0 AND abs(exit_close-floor(exit_preclose*(1.0+exit_limit_up_rate)*100.0+0.5)/100.0)<=0.005001 AS INTEGER) ELSE 0 END exit_one_price_limit_up,
  CASE WHEN NOT exit_lifecycle_active THEN 1 WHEN exit_tradable=0 THEN 1 WHEN exit_tradable=1 AND exit_volume_shares<=0 THEN 1 WHEN exit_tradable=1 AND exit_limit_rule NOT IN {na} AND abs(exit_high-exit_low)<=1e-12 AND exit_volume_shares>0 AND abs(exit_close-floor(exit_preclose*(1.0-exit_limit_down_rate)*100.0+0.5)/100.0)<=0.005001 THEN 1 ELSE 0 END hard_exit_veto
  FROM joined""")
 con.execute("CREATE TEMP TABLE flags AS SELECT *,CAST((decision_signal_invalid=1) OR (hard_entry_veto=1) OR (hard_exit_veto=1) AS INTEGER) runtime_hard_veto FROM f0")
 rows_path=out/b['outputs']['rows'];con.execute(f"COPY (SELECT * FROM flags ORDER BY coverage,trade_date,pred_rank) TO {q(str(rows_path))} (FORMAT PARQUET,COMPRESSION ZSTD)")
 comps=['decision_signal_invalid','hard_entry_veto','hard_exit_veto','runtime_hard_veto','decision_low_price_lt2','entry_lifecycle_inactive','exit_lifecycle_inactive','entry_one_price_limit_up','entry_one_price_limit_down','exit_one_price_limit_down','exit_one_price_limit_up']
 summaries=[]
 for cov in [0.05,0.10,0.20]:
  rs=one(con,"SELECT count(*)::BIGINT selected_rows,count(DISTINCT trade_date)::BIGINT cohort_count,"+','.join([f'sum(CAST({x} AS BIGINT))::BIGINT {x}_count' for x in comps])+f",sum(CAST(coalesce(decision_risk_warning,0) AS BIGINT))::BIGINT decision_risk_warning_count,sum(CAST(coalesce(entry_risk_warning,0) AS BIGINT))::BIGINT entry_risk_warning_count,sum(CAST(coalesce(exit_risk_warning,0) AS BIGINT))::BIGINT exit_risk_warning_count FROM flags WHERE coverage={cov}")
  cohorts=[dict(zip(['decision_date','selected_rows','runtime_hard_veto_rows','cohort_execution_valid'],r)) for r in con.execute(f"SELECT CAST(trade_date AS VARCHAR),count(*)::BIGINT,sum(runtime_hard_veto)::BIGINT,(sum(runtime_hard_veto)=0) FROM flags WHERE coverage={cov} GROUP BY trade_date ORDER BY trade_date").fetchall()]
  rs['coverage']=cov;rs['runtime_hard_veto_share']=int(rs['runtime_hard_veto_count'])/int(rs['selected_rows']);rs['coverage_execution_valid']=int(rs['runtime_hard_veto_count'])==0 and all(x['cohort_execution_valid'] for x in cohorts);rs['cohorts']=cohorts;summaries.append(rs)
 gate_checks={f"{int(x['coverage']*100):02d}pct_execution_valid":bool(x['coverage_execution_valid']) for x in summaries};gate_pass=all(gate_checks.values())
 summary={'schema_version':3,'status':'PASS' if gate_pass else 'FAIL','runtime_veto_contract_fingerprint':RUNTIME_FP,'physical_boundary_contract_fingerprint':BOUNDARY_FP,'selection_population':'FROZEN_OOS_PREDICTIONS_NO_SCORE_FILTER','rebalance_dates':rebalances,'backfill_performed':False,'replacement_performed':False,'post_selection_drop_performed':False,'oos_outcome_values_read':False,'risk_warning_hard_veto':False,'decision_low_price_lt2_hard_veto':False,'lifecycle_state_imputation_performed':False,'lifecycle_semantics':b['lifecycle_semantics'],'missing_required_execution_state_active_only':missing,'coverages':summaries,'gate_checks':gate_checks,'gate_pass':gate_pass,'alpha_oos_gate_modified':False,'runtime_veto_cannot_rescue_alpha_failure':True,'failure_action':'NO_PROMOTION_NO_BACKFILL_NO_RETUNING_ON_OOS'}
 summary_path=out/b['outputs']['summary'];summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');(out/b['outputs']['hashes']).write_text(json.dumps({rows_path.name:sha(rows_path),summary_path.name:sha(summary_path)},sort_keys=True,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False,indent=2,default=str));return 0
if __name__=='__main__':raise SystemExit(main())
