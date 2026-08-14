#!/usr/bin/env python3
from __future__ import annotations

import argparse, itertools, json, math
from pathlib import Path


def close(a,b,tol=1e-10):
    if a is None or b is None: return a is None and b is None
    return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a)-float(b))<=tol

def sharpe(xs,np):
    a=np.asarray(xs,dtype=float); a=a[np.isfinite(a)]
    if len(a)<2:return None
    sd=float(np.std(a,ddof=1)); return None if sd<=0 or not math.isfinite(sd) else float(np.mean(a)/sd*math.sqrt(252.0/20.0))


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--metrics-root',required=True); ap.add_argument('--aggregate-dir',required=True); ap.add_argument('--authorization',required=True); ap.add_argument('--execution-contract',required=True); ap.add_argument('--out',required=True)
    args=ap.parse_args()
    import numpy as np, pyarrow.parquet as pq
    from scipy.stats import rankdata,norm,skew,kurtosis

    auth=json.loads(Path(args.authorization).read_text(encoding='utf-8')); exe=json.loads(Path(args.execution_contract).read_text(encoding='utf-8')); root=Path(args.metrics_root); agg=Path(args.aggregate_dir)
    manifest=json.loads((agg/'training_execution_manifest.json').read_text(encoding='utf-8')); selection=json.loads((agg/'candidate_selection.json').read_text(encoding='utf-8')); pbo=json.loads((agg/'pbo_diagnostic.json').read_text(encoding='utf-8')); dsr=json.loads((agg/'dsr_diagnostic.json').read_text(encoding='utf-8')); table=json.loads((agg/'all_candidate_summary.json').read_text(encoding='utf-8'))
    checks:dict[str,bool]={}
    checks['authority_exact']=(auth['fingerprint']=='2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c' and exe['fingerprint']=='9b449b9c12ac98f1516812dfa4d3f40922668e35462087637cea79e81c1645dc' and manifest['authorization_fingerprint']==auth['fingerprint'] and manifest['execution_fingerprint']==exe['fingerprint'])
    expected=[f'C{i:03d}' for i in range(1,12)]; catalog={c['candidate_id']:c for c in auth['fingerprint_basis']['candidate_catalog']}
    dirs={}
    for cid in expected:
        hits=[p for p in root.rglob('*') if p.is_dir() and p.name.endswith(cid) and (p/'candidate_summary.json').is_file()]
        if len(hits)!=1: raise ValueError(f'metrics directory resolution failed {cid}: {hits}')
        dirs[cid]=hits[0]
    summaries={cid:json.loads((dirs[cid]/'candidate_summary.json').read_text(encoding='utf-8')) for cid in expected}; audits={cid:json.loads((dirs[cid]/'candidate_audit.json').read_text(encoding='utf-8')) for cid in expected}; trials={cid:json.loads((dirs[cid]/'trial_log.json').read_text(encoding='utf-8')) for cid in expected}
    checks['all_11_artifacts_and_audits_present']=all(audits[c]['pass'] for c in expected) and len(table)==11 and [x['candidate_id'] for x in table]==expected
    total_trials=sum(len(trials[c]) for c in expected); success=sum(sum(t['status']=='SUCCESS' for t in trials[c]) for c in expected); all_valid=all(summaries[c]['candidate_valid'] for c in expected)
    checks['trial_accounting_exact']=total_trials==manifest['trial_records']==55 and success==manifest['successful_trial_records'] and all_valid==manifest['all_candidates_valid']

    valid=[summaries[c] for c in expected if summaries[c]['candidate_valid']]
    def key(s):return (-float(s['primary_median_split_mean_daily_ic_20d']),-float(s['worst_split_mean_daily_ic_20d']),int(s['complexity_rank']),int(s['ordinal']))
    selected=min(valid,key=key) if valid else None; selected_id=None if selected is None else selected['candidate_id']
    checks['candidate_selection_recomputed']=(selected_id==selection['selected_candidate']==manifest['selected_candidate'] and selection['candidate_identity_frozen_by_preregistered_metric_only'] is True and selection['pbo_and_dsr_do_not_change_candidate_identity'] is True)

    daily={cid:pq.read_table(dirs[cid]/'daily_metrics.parquet').to_pylist() for cid in expected}
    maps={}; union=set(); common=None
    for cid in expected:
        m={r['trade_date']:float(r['daily_ic_20d']) for r in daily[cid] if r.get('daily_ic_20d') is not None and math.isfinite(float(r['daily_ic_20d']))}; maps[cid]=m; ds=set(m); union|=ds; common=ds if common is None else common&ds
    common=sorted(common or []); common_fraction=len(common)/len(union) if union else 0.0
    pbo_re=None; combo_count=0; blocks=[]
    if all_valid and common and common_fraction>=0.9:
        n=len(common); base,rem=divmod(n,10); sizes=[base+(1 if i<rem else 0) for i in range(10)]; pos=0
        for size in sizes:blocks.append(common[pos:pos+size]);pos+=size
        block_scores={cid:[float(np.mean([maps[cid][d] for d in b])) for b in blocks] for cid in expected}; events=[]
        for combo in itertools.combinations(range(10),5):
            comp=[i for i in range(10) if i not in combo]; ins={cid:float(np.mean([block_scores[cid][i] for i in combo])) for cid in expected}; best=min(expected,key=lambda c:(-ins[c],catalog[c]['ordinal'])); outs=np.asarray([float(np.mean([block_scores[c][i] for i in comp])) for c in expected]); ranks=rankdata(outs,method='average'); rank=float(ranks[expected.index(best)]); f=(rank-.5)/11.0; events.append(math.log(f/(1-f))<=0);combo_count+=1
        pbo_re=float(np.mean(events))
    checks['pbo_recomputed']=(close(pbo_re,pbo['pbo']) and combo_count==pbo['combination_count'] and combo_count in (0,252) and close(common_fraction,pbo['common_date_fraction']) and bool(pbo_re is not None and pbo_re<=0.2)==pbo['pass']==manifest['pbo_pass'])

    ret={}; sharpes={}
    for cid in expected:
        rs=[float(r['top10_gross_excess_20d']) for r in daily[cid] if int(r['test_session_index_within_split'])%20==0 and r.get('top10_gross_excess_20d') is not None and math.isfinite(float(r['top10_gross_excess_20d']))]; ret[cid]=rs; sharpes[cid]=sharpe(rs,np)
    finite=[sharpes[c] for c in expected if sharpes[c] is not None and math.isfinite(sharpes[c])]; dsr_re=None; srstar=None; sr=None; sk=None; ku=None; den=None
    if selected_id is not None and len(finite)==11:
        sr=float(sharpes[selected_id]); sigma=float(np.std(np.asarray(finite),ddof=1)); gamma=.5772156649015329;N=11;srstar=float(sigma*((1-gamma)*norm.ppf(1-1/N)+gamma*norm.ppf(1-1/(N*math.e)))); a=np.asarray(ret[selected_id],dtype=float);sk=float(skew(a,bias=False));ku=float(kurtosis(a,fisher=False,bias=False));den=float(1-sk*sr+((ku-1)/4)*(sr**2))
        if len(a)>=2 and den>0:dsr_re=float(norm.cdf((sr-srstar)*math.sqrt(len(a)-1)/math.sqrt(den)))
    checks['dsr_recomputed']=(close(dsr_re,dsr['dsr_probability']) and close(srstar,dsr['expected_max_sharpe']) and close(sr,dsr['selected_sharpe']) and close(sk,dsr['selected_skewness']) and close(ku,dsr['selected_pearson_kurtosis']) and bool(dsr_re is not None and dsr_re>=.95)==dsr['pass']==manifest['dsr_pass'])
    controls=bool(all_valid and pbo.get('pass') and dsr.get('pass')); checks['research_gate_semantics_exact']=(controls==manifest['overfit_controls_pass'] and manifest['research_gate_pass']==bool(manifest['execution_complete'] and controls and selected_id is not None) and manifest['next_gate']==('SEPARATE_FINAL_DEVELOPMENT_REFIT_AUTHORIZATION' if controls and selected_id is not None else 'STOP_OVERFIT_CONTROLS_FAIL_RESEARCH_ONLY'))
    checks['sealed_permissions_preserved']=(manifest['final_development_refit_executed'] is False and manifest['oos_accessed'] is False and manifest['lockbox_accessed'] is False and manifest['live_signal_allowed'] is False and manifest['authoritative_model_output'] is False)

    failed=[k for k,v in checks.items() if not v]; report={'gate':'STAGE4_ALPHA_V1_DEVELOPMENT_CV_AGGREGATE_INDEPENDENT_AUDIT','pass':not failed,'checks':checks,'failed_checks':failed,'selected_candidate_recomputed':selected_id,'pbo_recomputed':pbo_re,'dsr_probability_recomputed':dsr_re,'trial_records':total_trials,'successful_trial_records':success,'research_gate_pass':manifest['research_gate_pass'],'final_development_refit_executed':False,'oos_accessed':False,'lockbox_accessed':False}
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if report['pass'] else 2

if __name__=='__main__':raise SystemExit(main())
