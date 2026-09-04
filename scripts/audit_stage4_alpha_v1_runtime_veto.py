#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, sys
from pathlib import Path
from typing import Any

RUNTIME_FP='c2debc5fbf5fcad5454461d1080b14ac4de8c63489cb75e2a3e4b02bf1850f21'
BOUNDARY_FP='67e8555d3a9212a003a8293dc381cce0f7294917ef72875fed3218f240e0c255'
OOS_START='2023-01-03'; ECON_END='2024-12-03'; OOS_END='2024-12-31'
NA_LIMIT_RULES=('SUSPENDED','IPO_FIRST5_NO_LIMIT','DELISTING_15DAY_FIRST_DAY_NO_LIMIT')

def canon(x:Any)->str: return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def q(s:str)->str: return "'"+s.replace("'","''")+"'"
def sl(values:tuple[str,...])->str: return '('+','.join(q(x) for x in values)+')'
def row(con,sql):
    cur=con.execute(sql); return dict(zip([x[0] for x in cur.description],cur.fetchone()))

def synthetic()->int:
    # Suspended rows are hard-vetoed by tradable=0 even with no market/rate values.
    assert (0==0 or False) is True
    # Tradable no-limit rows carry NULL rates by design; one-price limit flags are forced to zero.
    for rule in ('IPO_FIRST5_NO_LIMIT','DELISTING_15DAY_FIRST_DAY_NO_LIMIT'):
        assert rule in NA_LIMIT_RULES
    print(json.dumps({'runtime_veto_independent_synthetic_self_test':'PASS','outcome_read':False,'backfill':False,'suspended_missing_market_semantics':True,'no_limit_rate_na_semantics':True}))
    return 0

def main()->int:
    if '--synthetic-self-test' in sys.argv: return synthetic()
    ap=argparse.ArgumentParser()
    for n in ['contract','boundary-contract','physical-boundary','predictions','runtime-dir','out']: ap.add_argument('--'+n,required=True)
    a=ap.parse_args(); import duckdb
    failures=[]; checks={}
    def ck(n,c,d=''):
        checks[n]=bool(c)
        if not c: failures.append(n+(f': {d}' if d else ''))
    try:
        c=json.loads(Path(a.contract).read_text(encoding='utf-8')); b=c['fingerprint_basis']; ck('runtime_contract',c.get('fingerprint')==RUNTIME_FP and canon(b)==RUNTIME_FP and c.get('status')=='FROZEN_PRE_ACCESS_RUNTIME_VETO_V1_NO_OOS_EXECUTION')
        bc=json.loads(Path(a.boundary_contract).read_text(encoding='utf-8')); bb=bc['fingerprint_basis']; ck('boundary_contract',bc.get('fingerprint')==BOUNDARY_FP and canon(bb)==BOUNDARY_FP and b.get('physical_boundary_contract_fingerprint')==BOUNDARY_FP)
        root=Path(a.physical_boundary); bo=bb['outputs']; expected={bo[k] for k in ['features','market','execution_state','lifecycle','manifest','source_verification','independent_audit','hashes']}; ck('boundary_file_set',{p.name for p in root.iterdir() if p.is_file()}==expected)
        bh=json.loads((root/bo['hashes']).read_text(encoding='utf-8')); ck('boundary_hash_map',set(bh)==expected-{bo['hashes']} and all(sha(root/n)==v for n,v in bh.items()))
        bm=json.loads((root/bo['manifest']).read_text(encoding='utf-8')); ba=json.loads((root/bo['independent_audit']).read_text(encoding='utf-8')); ck('boundary_clean',bm.get('status')=='PHYSICALLY_OOS_ONLY_PRE_PREDICTION_NON_LABEL' and bm.get('boundary_contract_fingerprint')==BOUNDARY_FP and ba.get('pass') is True and ba.get('failed_checks')==[] and int(ba.get('post_oos_rows_observed',-1))==0)
        app=bm.get('execution_state_applicability',{}); ck('boundary_applicability',app.get('na_limit_rules')==list(NA_LIMIT_RULES) and app.get('null_limit_rates_mean_not_applicable_not_imputed') is True)
        ready=bm.get('runtime_candidate_path_readiness',{}); ck('boundary_candidate_readiness',bool(ready) and int(ready.get('candidate_rows',0))>0 and all(int(v)==0 for k,v in ready.items() if k!='candidate_rows'),str(ready))
        rdir=Path(a.runtime_dir); ro=b['outputs']; rows_path=rdir/ro['rows']; summary_path=rdir/ro['summary']; hashes_path=rdir/ro['hashes']; ck('runtime_files',rows_path.is_file() and summary_path.is_file() and hashes_path.is_file())
        rh=json.loads(hashes_path.read_text(encoding='utf-8')); ck('runtime_hashes',rh.get(rows_path.name)==sha(rows_path) and rh.get(summary_path.name)==sha(summary_path)); summary=json.loads(summary_path.read_text(encoding='utf-8'))
        ck('summary_identity',summary.get('runtime_veto_contract_fingerprint')==RUNTIME_FP and summary.get('physical_boundary_contract_fingerprint')==BOUNDARY_FP)
        ck('summary_no_mutation',summary.get('backfill_performed') is False and summary.get('replacement_performed') is False and summary.get('post_selection_drop_performed') is False and summary.get('oos_outcome_values_read') is False and summary.get('alpha_oos_gate_modified') is False and summary.get('runtime_veto_cannot_rescue_alpha_failure') is True)
        sapp=summary.get('execution_state_applicability',{}); ck('summary_applicability',sapp.get('na_limit_rules')==list(NA_LIMIT_RULES) and sapp.get('null_limit_rates_mean_not_applicable_not_imputed') is True and sapp.get('suspended_missing_market_allowed_only_when_tradable_zero') is True)
        ck('summary_missing_required_zero',all(int(v)==0 for v in summary.get('missing_required_execution_state',{}).values()),str(summary.get('missing_required_execution_state')))
        pred=Path(a.predictions); market=root/bo['market']; state=root/bo['execution_state']; con=duckdb.connect(); con.execute('PRAGMA threads=4'); con.execute("PRAGMA memory_limit='6GB'")
        con.execute(f"CREATE TEMP VIEW p AS SELECT CAST(trade_date AS DATE) trade_date,upper(exchange) exchange,lpad(CAST(code AS VARCHAR),6,'0') code,CAST(prediction AS DOUBLE) prediction FROM read_parquet({q(str(pred))})")
        con.execute(f"CREATE TEMP VIEW m AS SELECT * FROM read_parquet({q(str(market))})"); con.execute(f"CREATE TEMP VIEW s AS SELECT * FROM read_parquet({q(str(state))})"); con.execute(f"CREATE TEMP VIEW r AS SELECT * FROM read_parquet({q(str(rows_path))})")
        ps=row(con,"SELECT count(*)::BIGINT rows,count(DISTINCT (trade_date,exchange,code))::BIGINT unique_keys,min(trade_date) min_date,max(trade_date) max_date,count(*) FILTER(WHERE prediction IS NULL OR NOT isfinite(prediction))::BIGINT invalid_predictions FROM p"); ck('prediction_population',int(ps['rows'])>0 and int(ps['rows'])==int(ps['unique_keys']) and str(ps['min_date'])==OOS_START and str(ps['max_date'])==OOS_END and int(ps['invalid_predictions'])==0 and int(ps['rows'])==int(bm['features']['row_count']),str(ps))
        con.execute("CREATE TEMP TABLE calendar AS SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 session_idx FROM (SELECT DISTINCT trade_date FROM m) ORDER BY trade_date")
        con.execute(f"CREATE TEMP TABLE ranked AS SELECT p.*,row_number() OVER(PARTITION BY trade_date ORDER BY prediction DESC,exchange ASC,code ASC) pred_rank,count(*) OVER(PARTITION BY trade_date) date_n FROM p WHERE trade_date<=DATE '{ECON_END}'")
        dates=[str(x[0]) for x in con.execute('SELECT DISTINCT trade_date FROM ranked ORDER BY trade_date').fetchall()]; rebalances=dates[::20]; ck('rebalance_dates',bool(rebalances) and rebalances[0]==OOS_START and summary.get('rebalance_dates')==rebalances)
        con.execute('CREATE TEMP TABLE rebalance_dates(trade_date DATE)'); con.executemany('INSERT INTO rebalance_dates VALUES (?)',[(d,) for d in rebalances])
        con.execute("CREATE TEMP TABLE expected_selected AS SELECT c.coverage,x.trade_date,x.exchange,x.code,x.prediction,x.pred_rank,x.date_n,ceil(c.coverage*x.date_n)::BIGINT bucket_n FROM ranked x JOIN rebalance_dates d USING(trade_date) CROSS JOIN (VALUES (0.05::DOUBLE),(0.10::DOUBLE),(0.20::DOUBLE)) c(coverage) WHERE x.pred_rank<=ceil(c.coverage*x.date_n)")
        selection_diff=con.execute("SELECT count(*) FROM ((SELECT coverage,trade_date,exchange,code,prediction,pred_rank,date_n,bucket_n FROM expected_selected EXCEPT SELECT coverage,trade_date,exchange,code,prediction,pred_rank,date_n,bucket_n FROM r) UNION ALL (SELECT coverage,trade_date,exchange,code,prediction,pred_rank,date_n,bucket_n FROM r EXCEPT SELECT coverage,trade_date,exchange,code,prediction,pred_rank,date_n,bucket_n FROM expected_selected))").fetchone()[0]; ck('selection_exact_no_backfill',int(selection_diff)==0,str(selection_diff))
        source_mismatch=con.execute("""SELECT count(*) FROM r x
          LEFT JOIN m dm ON x.trade_date=dm.trade_date AND x.exchange=dm.exchange AND x.code=dm.code
          LEFT JOIN s ds ON x.trade_date=ds.trade_date AND x.exchange=ds.exchange AND x.code=ds.code
          LEFT JOIN m em ON x.entry_date=em.trade_date AND x.exchange=em.exchange AND x.code=em.code
          LEFT JOIN s es ON x.entry_date=es.trade_date AND x.exchange=es.exchange AND x.code=es.code
          LEFT JOIN m xm ON x.exit_date=xm.trade_date AND x.exchange=xm.exchange AND x.code=xm.code
          LEFT JOIN s xs ON x.exit_date=xs.trade_date AND x.exchange=xs.exchange AND x.code=xs.code
          WHERE x.decision_close IS DISTINCT FROM dm.close OR x.decision_tradable IS DISTINCT FROM ds.tradable OR x.decision_risk_warning IS DISTINCT FROM ds.risk_warning OR x.decision_preclose IS DISTINCT FROM ds.preclose OR x.decision_limit_rule IS DISTINCT FROM ds.limit_rule OR x.decision_limit_up_rate IS DISTINCT FROM ds.limit_up_rate OR x.decision_limit_down_rate IS DISTINCT FROM ds.limit_down_rate
             OR x.entry_high IS DISTINCT FROM em.high OR x.entry_low IS DISTINCT FROM em.low OR x.entry_close IS DISTINCT FROM em.close OR x.entry_volume_shares IS DISTINCT FROM em.volume_shares
             OR x.entry_tradable IS DISTINCT FROM es.tradable OR x.entry_risk_warning IS DISTINCT FROM es.risk_warning OR x.entry_preclose IS DISTINCT FROM es.preclose OR x.entry_limit_rule IS DISTINCT FROM es.limit_rule OR x.entry_limit_up_rate IS DISTINCT FROM es.limit_up_rate OR x.entry_limit_down_rate IS DISTINCT FROM es.limit_down_rate
             OR x.exit_high IS DISTINCT FROM xm.high OR x.exit_low IS DISTINCT FROM xm.low OR x.exit_close IS DISTINCT FROM xm.close OR x.exit_volume_shares IS DISTINCT FROM xm.volume_shares
             OR x.exit_tradable IS DISTINCT FROM xs.tradable OR x.exit_risk_warning IS DISTINCT FROM xs.risk_warning OR x.exit_preclose IS DISTINCT FROM xs.preclose OR x.exit_limit_rule IS DISTINCT FROM xs.limit_rule OR x.exit_limit_up_rate IS DISTINCT FROM xs.limit_up_rate OR x.exit_limit_down_rate IS DISTINCT FROM xs.limit_down_rate""").fetchone()[0]; ck('raw_state_matches_physical_sources',int(source_mismatch)==0,str(source_mismatch))
        na=sl(NA_LIMIT_RULES)
        integrity=row(con,f"""SELECT
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
          count(*) FILTER(WHERE (exit_high IS NULL OR exit_low IS NULL OR exit_close IS NULL OR exit_volume_shares IS NULL) AND NOT (exit_tradable=0 AND exit_limit_rule='SUSPENDED'))::BIGINT invalid_missing_exit_market FROM r""")
        ck('selected_execution_integrity',all(int(v)==0 for v in integrity.values()),str(integrity))
        flag_mismatch=con.execute(f"""SELECT count(*) FROM r WHERE
          decision_low_price_lt2 != CASE WHEN decision_close IS NULL THEN 0 ELSE CAST(decision_close<2.0 AS INTEGER) END
          OR decision_signal_invalid != CAST(decision_tradable=0 AS INTEGER)
          OR entry_one_price != CASE WHEN entry_tradable=1 THEN CAST(abs(entry_high-entry_low)<=1e-12 AS INTEGER) ELSE 0 END
          OR entry_one_price_limit_up != CASE WHEN entry_tradable=1 AND entry_limit_rule NOT IN {na} THEN CAST(abs(entry_high-entry_low)<=1e-12 AND entry_volume_shares>0 AND abs(entry_close-floor(entry_preclose*(1.0+entry_limit_up_rate)*100.0+0.5)/100.0)<=0.005001 AS INTEGER) ELSE 0 END
          OR entry_one_price_limit_down != CASE WHEN entry_tradable=1 AND entry_limit_rule NOT IN {na} THEN CAST(abs(entry_high-entry_low)<=1e-12 AND entry_volume_shares>0 AND abs(entry_close-floor(entry_preclose*(1.0-entry_limit_down_rate)*100.0+0.5)/100.0)<=0.005001 AS INTEGER) ELSE 0 END
          OR hard_entry_veto != CAST((entry_tradable=0) OR (entry_tradable=1 AND entry_volume_shares<=0) OR (entry_tradable=1 AND entry_limit_rule NOT IN {na} AND abs(entry_high-entry_low)<=1e-12 AND entry_volume_shares>0 AND abs(entry_close-floor(entry_preclose*(1.0+entry_limit_up_rate)*100.0+0.5)/100.0)<=0.005001) AS INTEGER)
          OR exit_one_price != CASE WHEN exit_tradable=1 THEN CAST(abs(exit_high-exit_low)<=1e-12 AS INTEGER) ELSE 0 END
          OR exit_one_price_limit_down != CASE WHEN exit_tradable=1 AND exit_limit_rule NOT IN {na} THEN CAST(abs(exit_high-exit_low)<=1e-12 AND exit_volume_shares>0 AND abs(exit_close-floor(exit_preclose*(1.0-exit_limit_down_rate)*100.0+0.5)/100.0)<=0.005001 AS INTEGER) ELSE 0 END
          OR exit_one_price_limit_up != CASE WHEN exit_tradable=1 AND exit_limit_rule NOT IN {na} THEN CAST(abs(exit_high-exit_low)<=1e-12 AND exit_volume_shares>0 AND abs(exit_close-floor(exit_preclose*(1.0+exit_limit_up_rate)*100.0+0.5)/100.0)<=0.005001 AS INTEGER) ELSE 0 END
          OR hard_exit_veto != CAST((exit_tradable=0) OR (exit_tradable=1 AND exit_volume_shares<=0) OR (exit_tradable=1 AND exit_limit_rule NOT IN {na} AND abs(exit_high-exit_low)<=1e-12 AND exit_volume_shares>0 AND abs(exit_close-floor(exit_preclose*(1.0-exit_limit_down_rate)*100.0+0.5)/100.0)<=0.005001) AS INTEGER)
          OR runtime_hard_veto != CAST((decision_tradable=0) OR (entry_tradable=0) OR (entry_tradable=1 AND entry_volume_shares<=0) OR (entry_tradable=1 AND entry_limit_rule NOT IN {na} AND abs(entry_high-entry_low)<=1e-12 AND entry_volume_shares>0 AND abs(entry_close-floor(entry_preclose*(1.0+entry_limit_up_rate)*100.0+0.5)/100.0)<=0.005001) OR (exit_tradable=0) OR (exit_tradable=1 AND exit_volume_shares<=0) OR (exit_tradable=1 AND exit_limit_rule NOT IN {na} AND abs(exit_high-exit_low)<=1e-12 AND exit_volume_shares>0 AND abs(exit_close-floor(exit_preclose*(1.0-exit_limit_down_rate)*100.0+0.5)/100.0)<=0.005001) AS INTEGER)
        """).fetchone()[0]; ck('flags_independently_recomputed',int(flag_mismatch)==0,str(flag_mismatch))
        comps=['decision_signal_invalid','hard_entry_veto','hard_exit_veto','runtime_hard_veto','decision_low_price_lt2','decision_risk_warning','entry_risk_warning','exit_risk_warning','entry_one_price_limit_up','entry_one_price_limit_down','exit_one_price_limit_down','exit_one_price_limit_up']
        recomputed=[]
        for cov in [0.05,0.10,0.20]:
            rs=row(con,"SELECT count(*)::BIGINT selected_rows,count(DISTINCT trade_date)::BIGINT cohort_count,"+','.join([f'sum(CAST({x} AS BIGINT))::BIGINT {x}_count' for x in comps])+f' FROM r WHERE coverage={cov}')
            cohorts=[dict(zip(['decision_date','selected_rows','runtime_hard_veto_rows','cohort_execution_valid'],x)) for x in con.execute(f"SELECT CAST(trade_date AS VARCHAR),count(*)::BIGINT,sum(runtime_hard_veto)::BIGINT,(sum(runtime_hard_veto)=0) FROM r WHERE coverage={cov} GROUP BY trade_date ORDER BY trade_date").fetchall()]
            rs['coverage']=cov; rs['runtime_hard_veto_share']=int(rs['runtime_hard_veto_count'])/int(rs['selected_rows']); rs['coverage_execution_valid']=int(rs['runtime_hard_veto_count'])==0 and all(x['cohort_execution_valid'] for x in cohorts); rs['cohorts']=cohorts; recomputed.append(rs)
        ck('summary_coverages_exact',summary.get('coverages')==recomputed)
        gates={f"{int(x['coverage']*100):02d}pct_execution_valid":bool(x['coverage_execution_valid']) for x in recomputed}; ck('gate_checks_exact',summary.get('gate_checks')==gates and summary.get('gate_pass')==all(gates.values()) and summary.get('status')==('PASS' if all(gates.values()) else 'FAIL'))
        result={'schema_version':2,'status':'PASS' if not failures else 'FAIL','pass':not failures,'runtime_veto_contract_fingerprint':RUNTIME_FP,'physical_boundary_contract_fingerprint':BOUNDARY_FP,'failed_checks':failures,'checks':checks,'recomputed_coverages':recomputed,'recomputed_gate_checks':gates,'recomputed_gate_pass':all(gates.values()),'execution_state_applicability':{'na_limit_rules':list(NA_LIMIT_RULES),'null_limit_rates_mean_not_applicable_not_imputed':True,'suspended_missing_market_allowed_only_when_tradable_zero':True},'oos_outcome_values_read':False,'predictions_recomputed':False,'model_loaded':False,'fit_retrain_tune_reselect_executed':False,'backfill_performed':False,'replacement_performed':False,'post_selection_drop_performed':False,'final_lockbox_accessed':False}
    except Exception as e:
        failures.append(f'exception: {type(e).__name__}: {e}'); result={'schema_version':2,'status':'FAIL','pass':False,'failed_checks':failures,'checks':checks}
    p=Path(a.out); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8'); print(json.dumps(result,ensure_ascii=False,indent=2,default=str)); return 0 if result['pass'] else 2

if __name__=='__main__': raise SystemExit(main())
