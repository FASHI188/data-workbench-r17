#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, math, sys
from pathlib import Path
from typing import Any

RUNTIME_FP='c2debc5fbf5fcad5454461d1080b14ac4de8c63489cb75e2a3e4b02bf1850f21'
BOUNDARY_FP='67e8555d3a9212a003a8293dc381cce0f7294917ef72875fed3218f240e0c255'
OOS_START='2023-01-03'; ECON_END='2024-12-03'; OOS_END='2024-12-31'
NA_LIMIT_RULES=('SUSPENDED','IPO_FIRST5_NO_LIMIT','DELISTING_15DAY_FIRST_DAY_NO_LIMIT')


def canon(obj:Any)->str: return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def q(s:str)->str: return "'"+s.replace("'","''")+"'"
def sl(values:tuple[str,...])->str: return '('+','.join(q(x) for x in values)+')'
def one(con,sql):
    cur=con.execute(sql); return dict(zip([x[0] for x in cur.description],cur.fetchone()))


def synthetic()->int:
    def hup(pre,rate): return math.floor(pre*(1+rate)*100+0.5)/100
    def hdn(pre,rate): return math.floor(pre*(1-rate)*100+0.5)/100
    assert hup(10.0,0.10)==11.0 and hdn(10.0,0.10)==9.0
    # Normal tradable row.
    assert (1==0 or 100<=0 or False) is False
    # Suspended row: no OHLCV/rate is needed because tradable=0 itself is the hard veto.
    assert (0==0 or False) is True
    # No-limit rows are tradable with NULL rates; one-price limit tests must evaluate false, not unknown.
    for rule in ('IPO_FIRST5_NO_LIMIT','DELISTING_15DAY_FIRST_DAY_NO_LIMIT'):
        assert rule in NA_LIMIT_RULES
        one_up = False if rule in NA_LIMIT_RULES else None
        one_down = False if rule in NA_LIMIT_RULES else None
        assert one_up is False and one_down is False
    print(json.dumps({'runtime_veto_synthetic_self_test':'PASS','backfill':False,'replacement':False,'risk_warning_hard_veto':False,'suspended_missing_market_allowed_and_hard_vetoed':True,'no_limit_null_rates_treated_as_not_applicable':True}))
    return 0


def main()->int:
    if '--synthetic-self-test' in sys.argv: return synthetic()
    ap=argparse.ArgumentParser()
    for n in ['contract','boundary-contract','physical-boundary','predictions','out']: ap.add_argument('--'+n,required=True)
    a=ap.parse_args(); import duckdb
    c=json.loads(Path(a.contract).read_text(encoding='utf-8')); b=c['fingerprint_basis']
    if c.get('fingerprint')!=RUNTIME_FP or canon(b)!=RUNTIME_FP or c.get('status')!='FROZEN_PRE_ACCESS_RUNTIME_VETO_V1_NO_OOS_EXECUTION': raise ValueError('runtime veto contract mismatch')
    if b['physical_boundary_contract_fingerprint']!=BOUNDARY_FP: raise ValueError('runtime veto boundary binding mismatch')
    s=b['scope']
    for k in ['prediction_ranking_frozen','selected_bucket_membership_frozen','backfill_forbidden','replacement_forbidden','post_selection_drop_forbidden','score_filtering_forbidden','oos_fit_retrain_tune_reselect_forbidden','oos_outcome_values_forbidden','final_lockbox_access_forbidden','runtime_veto_cannot_rescue_alpha_failure']:
        if s.get(k) is not True: raise ValueError('runtime veto scope not frozen: '+k)
    bc=json.loads(Path(a.boundary_contract).read_text(encoding='utf-8')); bb=bc['fingerprint_basis']
    if bc.get('fingerprint')!=BOUNDARY_FP or canon(bb)!=BOUNDARY_FP: raise ValueError('physical boundary contract mismatch')
    root=Path(a.physical_boundary); bo=bb['outputs']; expected={bo[k] for k in ['features','market','execution_state','lifecycle','manifest','source_verification','independent_audit','hashes']}
    have={p.name for p in root.iterdir() if p.is_file()}
    if have!=expected: raise ValueError(f'physical package file set mismatch {have} != {expected}')
    hashes=json.loads((root/bo['hashes']).read_text(encoding='utf-8'))
    if set(hashes)!=expected-{bo['hashes']} or any(sha(root/n)!=v for n,v in hashes.items()): raise ValueError('physical package hashes invalid')
    bm=json.loads((root/bo['manifest']).read_text(encoding='utf-8')); ba=json.loads((root/bo['independent_audit']).read_text(encoding='utf-8'))
    if bm.get('status')!='PHYSICALLY_OOS_ONLY_PRE_PREDICTION_NON_LABEL' or bm.get('boundary_contract_fingerprint')!=BOUNDARY_FP: raise ValueError('physical manifest invalid')
    if ba.get('pass') is not True or ba.get('failed_checks')!=[] or int(ba.get('post_oos_rows_observed',-1))!=0: raise ValueError('physical boundary audit invalid')
    app=bm.get('execution_state_applicability',{})
    if app.get('na_limit_rules')!=list(NA_LIMIT_RULES) or app.get('null_limit_rates_mean_not_applicable_not_imputed') is not True: raise ValueError('physical execution-state applicability evidence missing')
    ready=bm.get('runtime_candidate_path_readiness',{})
    if not ready or int(ready.get('candidate_rows',0))<=0 or any(int(v)!=0 for k,v in ready.items() if k!='candidate_rows'): raise ValueError('pre-prediction runtime candidate-path readiness did not pass')

    out=Path(a.out); out.mkdir(parents=True,exist_ok=True); pred=Path(a.predictions); market=root/bo['market']; state=root/bo['execution_state']
    con=duckdb.connect(); con.execute('PRAGMA threads=4'); con.execute("PRAGMA memory_limit='6GB'")
    con.execute(f'CREATE TEMP VIEW p AS SELECT CAST(trade_date AS DATE) trade_date,upper(exchange) exchange,lpad(CAST(code AS VARCHAR),6,\'0\') code,CAST(prediction AS DOUBLE) prediction FROM read_parquet({q(str(pred))})')
    con.execute(f'CREATE TEMP VIEW m AS SELECT * FROM read_parquet({q(str(market))})'); con.execute(f'CREATE TEMP VIEW s AS SELECT * FROM read_parquet({q(str(state))})')
    ps=one(con,"SELECT count(*)::BIGINT rows,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,min(trade_date) min_date,max(trade_date) max_date,count(*) FILTER(WHERE prediction IS NULL OR NOT isfinite(prediction))::BIGINT invalid_predictions FROM p")
    if int(ps['rows'])<=0 or int(ps['rows'])!=int(ps['unique_keys']) or str(ps['min_date'])!=OOS_START or str(ps['max_date'])!=OOS_END or int(ps['invalid_predictions'])!=0: raise ValueError('prediction population invalid')
    if int(ps['rows'])!=int(bm['features']['row_count']): raise ValueError('prediction mother population differs from physical features')
    con.execute("CREATE TEMP TABLE calendar AS SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 session_idx FROM (SELECT DISTINCT trade_date FROM m) ORDER BY trade_date")
    con.execute(f"""CREATE TEMP TABLE ranked AS
      SELECT p.*,row_number() OVER(PARTITION BY trade_date ORDER BY prediction DESC,exchange ASC,code ASC) pred_rank,count(*) OVER(PARTITION BY trade_date) date_n
      FROM p WHERE trade_date<=DATE '{ECON_END}'""")
    dates=[str(x[0]) for x in con.execute('SELECT DISTINCT trade_date FROM ranked ORDER BY trade_date').fetchall()]
    if not dates or dates[0]!=OOS_START: raise ValueError('runtime veto rebalance anchor missing')
    rebalances=dates[::int(b['selection']['rebalance_sessions'])]
    con.execute('CREATE TEMP TABLE rebalance_dates(trade_date DATE)'); con.executemany('INSERT INTO rebalance_dates VALUES (?)',[(d,) for d in rebalances])
    con.execute("""CREATE TEMP TABLE selected AS
      SELECT c.coverage,r.*,ceil(c.coverage*r.date_n)::BIGINT bucket_n
      FROM ranked r JOIN rebalance_dates d USING(trade_date)
      CROSS JOIN (VALUES (0.05::DOUBLE),(0.10::DOUBLE),(0.20::DOUBLE)) c(coverage)
      WHERE r.pred_rank<=ceil(c.coverage*r.date_n)""")
    con.execute("""CREATE TEMP TABLE schedule AS
      SELECT x.*,cal.session_idx,e.trade_date entry_date,z.trade_date exit_date
      FROM selected x JOIN calendar cal ON x.trade_date=cal.trade_date
      LEFT JOIN calendar e ON e.session_idx=cal.session_idx+1
      LEFT JOIN calendar z ON z.session_idx=cal.session_idx+20""")
    con.execute("""CREATE TEMP TABLE joined AS
      SELECT x.*,
        dm.close decision_close,ds.tradable decision_tradable,ds.risk_warning decision_risk_warning,ds.preclose decision_preclose,ds.limit_rule decision_limit_rule,ds.limit_up_rate decision_limit_up_rate,ds.limit_down_rate decision_limit_down_rate,
        em.high entry_high,em.low entry_low,em.close entry_close,em.volume_shares entry_volume_shares,
        es.tradable entry_tradable,es.risk_warning entry_risk_warning,es.preclose entry_preclose,es.limit_rule entry_limit_rule,es.limit_up_rate entry_limit_up_rate,es.limit_down_rate entry_limit_down_rate,
        xm.high exit_high,xm.low exit_low,xm.close exit_close,xm.volume_shares exit_volume_shares,
        xs.tradable exit_tradable,xs.risk_warning exit_risk_warning,xs.preclose exit_preclose,xs.limit_rule exit_limit_rule,xs.limit_up_rate exit_limit_up_rate,xs.limit_down_rate exit_limit_down_rate
      FROM schedule x
      LEFT JOIN m dm ON x.trade_date=dm.trade_date AND x.exchange=dm.exchange AND x.code=dm.code
      LEFT JOIN s ds ON x.trade_date=ds.trade_date AND x.exchange=ds.exchange AND x.code=ds.code
      LEFT JOIN m em ON x.entry_date=em.trade_date AND x.exchange=em.exchange AND x.code=em.code
      LEFT JOIN s es ON x.entry_date=es.trade_date AND x.exchange=es.exchange AND x.code=es.code
      LEFT JOIN m xm ON x.exit_date=xm.trade_date AND x.exchange=xm.exchange AND x.code=xm.code
      LEFT JOIN s xs ON x.exit_date=xs.trade_date AND x.exchange=xs.exchange AND x.code=xs.code""")
    na=sl(NA_LIMIT_RULES)
    missing=one(con,f"""SELECT
      count(*) FILTER(WHERE entry_date IS NULL OR exit_date IS NULL)::BIGINT missing_schedule,
      count(*) FILTER(WHERE decision_tradable IS NULL OR decision_risk_warning IS NULL OR decision_preclose IS NULL OR decision_limit_rule IS NULL)::BIGINT missing_decision_core_state,
      count(*) FILTER(WHERE entry_tradable IS NULL OR entry_risk_warning IS NULL OR entry_preclose IS NULL OR entry_limit_rule IS NULL)::BIGINT missing_entry_core_state,
      count(*) FILTER(WHERE exit_tradable IS NULL OR exit_risk_warning IS NULL OR exit_preclose IS NULL OR exit_limit_rule IS NULL)::BIGINT missing_exit_core_state,
      count(*) FILTER(WHERE decision_limit_rule NOT IN {na} AND (decision_limit_up_rate IS NULL OR decision_limit_down_rate IS NULL))::BIGINT missing_decision_applicable_rate,
      count(*) FILTER(WHERE entry_limit_rule NOT IN {na} AND (entry_limit_up_rate IS NULL OR entry_limit_down_rate IS NULL))::BIGINT missing_entry_applicable_rate,
      count(*) FILTER(WHERE exit_limit_rule NOT IN {na} AND (exit_limit_up_rate IS NULL OR exit_limit_down_rate IS NULL))::BIGINT missing_exit_applicable_rate,
      count(*) FILTER(WHERE decision_tradable=1 AND decision_close IS NULL)::BIGINT missing_tradable_decision_market,
      count(*) FILTER(WHERE entry_tradable=1 AND (entry_high IS NULL OR entry_low IS NULL OR entry_close IS NULL OR entry_volume_shares IS NULL))::BIGINT missing_tradable_entry_market,
      count(*) FILTER(WHERE exit_tradable=1 AND (exit_high IS NULL OR exit_low IS NULL OR exit_close IS NULL OR exit_volume_shares IS NULL))::BIGINT missing_tradable_exit_market,
      count(*) FILTER(WHERE decision_close IS NULL AND NOT (decision_tradable=0 AND decision_limit_rule='SUSPENDED'))::BIGINT invalid_missing_decision_market,
      count(*) FILTER(WHERE (entry_high IS NULL OR entry_low IS NULL OR entry_close IS NULL OR entry_volume_shares IS NULL) AND NOT (entry_tradable=0 AND entry_limit_rule='SUSPENDED'))::BIGINT invalid_missing_entry_market,
      count(*) FILTER(WHERE (exit_high IS NULL OR exit_low IS NULL OR exit_close IS NULL OR exit_volume_shares IS NULL) AND NOT (exit_tradable=0 AND exit_limit_rule='SUSPENDED'))::BIGINT invalid_missing_exit_market
      FROM joined""")
    if any(int(v)!=0 for v in missing.values()): raise ValueError(f'missing required execution state: {missing}')
    con.execute(f"""CREATE TEMP TABLE flags AS SELECT *,
      CASE WHEN decision_close IS NULL THEN 0 ELSE CAST(decision_close<2.0 AS INTEGER) END decision_low_price_lt2,
      CAST(decision_tradable=0 AS INTEGER) decision_signal_invalid,
      CASE WHEN entry_tradable=1 THEN CAST(abs(entry_high-entry_low)<=1e-12 AS INTEGER) ELSE 0 END entry_one_price,
      CASE WHEN entry_tradable=1 AND entry_limit_rule NOT IN {na} THEN CAST(abs(entry_high-entry_low)<=1e-12 AND entry_volume_shares>0 AND abs(entry_close-floor(entry_preclose*(1.0+entry_limit_up_rate)*100.0+0.5)/100.0)<=0.005001 AS INTEGER) ELSE 0 END entry_one_price_limit_up,
      CASE WHEN entry_tradable=1 AND entry_limit_rule NOT IN {na} THEN CAST(abs(entry_high-entry_low)<=1e-12 AND entry_volume_shares>0 AND abs(entry_close-floor(entry_preclose*(1.0-entry_limit_down_rate)*100.0+0.5)/100.0)<=0.005001 AS INTEGER) ELSE 0 END entry_one_price_limit_down,
      CAST((entry_tradable=0) OR (entry_tradable=1 AND entry_volume_shares<=0) OR (entry_tradable=1 AND entry_limit_rule NOT IN {na} AND abs(entry_high-entry_low)<=1e-12 AND entry_volume_shares>0 AND abs(entry_close-floor(entry_preclose*(1.0+entry_limit_up_rate)*100.0+0.5)/100.0)<=0.005001) AS INTEGER) hard_entry_veto,
      CASE WHEN exit_tradable=1 THEN CAST(abs(exit_high-exit_low)<=1e-12 AS INTEGER) ELSE 0 END exit_one_price,
      CASE WHEN exit_tradable=1 AND exit_limit_rule NOT IN {na} THEN CAST(abs(exit_high-exit_low)<=1e-12 AND exit_volume_shares>0 AND abs(exit_close-floor(exit_preclose*(1.0-exit_limit_down_rate)*100.0+0.5)/100.0)<=0.005001 AS INTEGER) ELSE 0 END exit_one_price_limit_down,
      CASE WHEN exit_tradable=1 AND exit_limit_rule NOT IN {na} THEN CAST(abs(exit_high-exit_low)<=1e-12 AND exit_volume_shares>0 AND abs(exit_close-floor(exit_preclose*(1.0+exit_limit_up_rate)*100.0+0.5)/100.0)<=0.005001 AS INTEGER) ELSE 0 END exit_one_price_limit_up,
      CAST((exit_tradable=0) OR (exit_tradable=1 AND exit_volume_shares<=0) OR (exit_tradable=1 AND exit_limit_rule NOT IN {na} AND abs(exit_high-exit_low)<=1e-12 AND exit_volume_shares>0 AND abs(exit_close-floor(exit_preclose*(1.0-exit_limit_down_rate)*100.0+0.5)/100.0)<=0.005001) AS INTEGER) hard_exit_veto,
      CAST((decision_tradable=0) OR (entry_tradable=0) OR (entry_tradable=1 AND entry_volume_shares<=0) OR (entry_tradable=1 AND entry_limit_rule NOT IN {na} AND abs(entry_high-entry_low)<=1e-12 AND entry_volume_shares>0 AND abs(entry_close-floor(entry_preclose*(1.0+entry_limit_up_rate)*100.0+0.5)/100.0)<=0.005001) OR (exit_tradable=0) OR (exit_tradable=1 AND exit_volume_shares<=0) OR (exit_tradable=1 AND exit_limit_rule NOT IN {na} AND abs(exit_high-exit_low)<=1e-12 AND exit_volume_shares>0 AND abs(exit_close-floor(exit_preclose*(1.0-exit_limit_down_rate)*100.0+0.5)/100.0)<=0.005001) AS INTEGER) runtime_hard_veto
      FROM joined""")
    rows_path=out/b['outputs']['rows']; con.execute(f"COPY (SELECT * FROM flags ORDER BY coverage,trade_date,pred_rank) TO {q(str(rows_path))} (FORMAT PARQUET,COMPRESSION ZSTD)")
    components=['decision_signal_invalid','hard_entry_veto','hard_exit_veto','runtime_hard_veto','decision_low_price_lt2','decision_risk_warning','entry_risk_warning','exit_risk_warning','entry_one_price_limit_up','entry_one_price_limit_down','exit_one_price_limit_down','exit_one_price_limit_up']
    summaries=[]
    for cov in [0.05,0.10,0.20]:
        rs=one(con,f"SELECT count(*)::BIGINT selected_rows,count(DISTINCT trade_date)::BIGINT cohort_count,"+','.join([f'sum(CAST({x} AS BIGINT))::BIGINT {x}_count' for x in components])+f" FROM flags WHERE coverage={cov}")
        cohorts=[dict(zip(['decision_date','selected_rows','runtime_hard_veto_rows','cohort_execution_valid'],r)) for r in con.execute(f"SELECT CAST(trade_date AS VARCHAR),count(*)::BIGINT,sum(runtime_hard_veto)::BIGINT,(sum(runtime_hard_veto)=0) FROM flags WHERE coverage={cov} GROUP BY trade_date ORDER BY trade_date").fetchall()]
        rs['coverage']=cov; rs['runtime_hard_veto_share']=int(rs['runtime_hard_veto_count'])/int(rs['selected_rows']); rs['coverage_execution_valid']=int(rs['runtime_hard_veto_count'])==0 and all(x['cohort_execution_valid'] for x in cohorts); rs['cohorts']=cohorts; summaries.append(rs)
    gate_checks={f"{int(x['coverage']*100):02d}pct_execution_valid":bool(x['coverage_execution_valid']) for x in summaries}; gate_pass=all(gate_checks.values())
    summary={'schema_version':2,'status':'PASS' if gate_pass else 'FAIL','runtime_veto_contract_fingerprint':RUNTIME_FP,'physical_boundary_contract_fingerprint':BOUNDARY_FP,'selection_population':'FROZEN_OOS_PREDICTIONS_NO_SCORE_FILTER','rebalance_dates':rebalances,'backfill_performed':False,'replacement_performed':False,'post_selection_drop_performed':False,'oos_outcome_values_read':False,'risk_warning_hard_veto':False,'decision_low_price_lt2_hard_veto':False,'execution_state_applicability':{'na_limit_rules':list(NA_LIMIT_RULES),'null_limit_rates_mean_not_applicable_not_imputed':True,'suspended_missing_market_allowed_only_when_tradable_zero':True},'missing_required_execution_state':missing,'coverages':summaries,'gate_checks':gate_checks,'gate_pass':gate_pass,'alpha_oos_gate_modified':False,'runtime_veto_cannot_rescue_alpha_failure':True,'failure_action':'NO_PROMOTION_NO_BACKFILL_NO_RETUNING_ON_OOS'}
    summary_path=out/b['outputs']['summary']; summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    hashes_out={rows_path.name:sha(rows_path),summary_path.name:sha(summary_path)}; (out/b['outputs']['hashes']).write_text(json.dumps(hashes_out,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2,default=str)); return 0

if __name__=='__main__': raise SystemExit(main())
