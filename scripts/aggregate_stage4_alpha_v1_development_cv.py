#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, itertools, json, math
from pathlib import Path


def sha256_file(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def safe_float(x): return None if x is None else float(x)

def sharpe(xs, np):
    a=np.asarray(xs,dtype=float); a=a[np.isfinite(a)]
    if len(a)<2: return None
    sd=float(np.std(a,ddof=1))
    return None if not math.isfinite(sd) or sd<=0 else float(np.mean(a)/sd*math.sqrt(252.0/20.0))


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--metrics-root',required=True); ap.add_argument('--authorization',required=True); ap.add_argument('--execution-contract',required=True); ap.add_argument('--out',required=True)
    args=ap.parse_args()
    import numpy as np, pyarrow.parquet as pq
    from scipy.stats import rankdata, norm, skew, kurtosis

    auth=json.loads(Path(args.authorization).read_text(encoding='utf-8')); exe=json.loads(Path(args.execution_contract).read_text(encoding='utf-8')); root=Path(args.metrics_root); out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    if auth['fingerprint']!='2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c': raise ValueError('authorization mismatch')
    if exe['fingerprint']!='9b449b9c12ac98f1516812dfa4d3f40922668e35462087637cea79e81c1645dc': raise ValueError('execution mismatch')
    catalog={c['candidate_id']:c for c in auth['fingerprint_basis']['candidate_catalog']}; expected=list(exe['fingerprint_basis']['candidate_execution']['candidate_ids'])

    dirs={}
    for cid in expected:
        hits=[p for p in root.rglob('*') if p.is_dir() and p.name.endswith(cid) and (p/'candidate_summary.json').is_file()]
        if len(hits)!=1: raise ValueError(f'expected exactly one metrics dir for {cid}, found {hits}')
        dirs[cid]=hits[0]

    summaries=[]; audits={}; daily={}; trials={}
    for cid in expected:
        d=dirs[cid]; s=json.loads((d/'candidate_summary.json').read_text(encoding='utf-8')); a=json.loads((d/'candidate_audit.json').read_text(encoding='utf-8')); t=json.loads((d/'trial_log.json').read_text(encoding='utf-8'))
        if s['candidate_id']!=cid or not a['pass'] or a['candidate_id']!=cid or len(t)!=5: raise ValueError(f'structural candidate audit failure {cid}')
        summaries.append(s); audits[cid]=a; trials[cid]=t
        table=pq.read_table(d/'daily_metrics.parquet'); rows=table.to_pylist(); daily[cid]=rows

    total_trials=sum(len(v) for v in trials.values()); successful_trials=sum(sum(x['status']=='SUCCESS' for x in v) for v in trials.values())
    all_valid=all(s['candidate_valid'] for s in summaries)
    valid_summaries=[s for s in summaries if s['candidate_valid']]
    def selkey(s): return (-float(s['primary_median_split_mean_daily_ic_20d']),-float(s['worst_split_mean_daily_ic_20d']),int(s['complexity_rank']),int(s['ordinal']))
    selected=min(valid_summaries,key=selkey) if valid_summaries else None

    # Per-date OOF IC maps.
    maps={}
    unions=set(); intersections=None
    for cid in expected:
        m={r['trade_date']:float(r['daily_ic_20d']) for r in daily[cid] if r.get('daily_ic_20d') is not None and math.isfinite(float(r['daily_ic_20d']))}
        maps[cid]=m; ds=set(m); unions |= ds; intersections=ds if intersections is None else intersections & ds
    common=sorted(intersections or []); common_fraction=(len(common)/len(unions)) if unions else 0.0

    pbo_cfg=exe['fingerprint_basis']['pbo_exact']; pbo_rows=[]; pbo_value=None; pbo_pass=False; block_defs=[]
    if all_valid and common and common_fraction>=pbo_cfg['minimum_common_date_fraction']:
        n=len(common); base,rem=divmod(n,10); sizes=[base+(1 if i<rem else 0) for i in range(10)]; pos=0; blocks=[]
        for i,size in enumerate(sizes):
            part=common[pos:pos+size]; blocks.append(part); block_defs.append({'block_id':i,'start':part[0],'end':part[-1],'date_count':len(part)}); pos+=size
        for combo in itertools.combinations(range(10),5):
            is_blocks=set(combo); oos_blocks=[i for i in range(10) if i not in is_blocks]
            is_dates=[d for i in combo for d in blocks[i]]
            oos_dates=[d for i in oos_blocks for d in blocks[i]]
            is_scores={cid:float(np.mean([maps[cid][d] for d in is_dates])) for cid in expected}
            best=min(expected,key=lambda cid:(-is_scores[cid],catalog[cid]['ordinal']))
            oos_scores={cid:float(np.mean([maps[cid][d] for d in oos_dates])) for cid in expected}
            vals=np.asarray([oos_scores[cid] for cid in expected],dtype=float); ranks=rankdata(vals,method='average')
            rank=float(ranks[expected.index(best)]); frac=(rank-0.5)/11.0; logit=float(math.log(frac/(1.0-frac)))
            pbo_rows.append({'is_blocks':list(combo),'selected_candidate':best,'selected_is_score':is_scores[best],'selected_oos_score':oos_scores[best],'selected_oos_rank_1_worst':rank,'rank_fraction':frac,'logit':logit,'overfit_event':logit<=0.0})
        pbo_value=float(np.mean([r['overfit_event'] for r in pbo_rows])); pbo_pass=pbo_value<=float(pbo_cfg['pass_ceiling'])
    pbo_diag={'method':'CSCV_ON_CAUSAL_FORWARD_OOF_CANDIDATE_PERFORMANCE_SERIES','score_weighting':'DAILY_OBSERVATION_WEIGHTED_ACROSS_SELECTED_BLOCKS','all_candidates_valid':all_valid,'union_nonnull_ic_dates':len(unions),'common_nonnull_ic_dates':len(common),'common_date_fraction':common_fraction,'minimum_common_date_fraction':pbo_cfg['minimum_common_date_fraction'],'blocks':block_defs,'combination_count':len(pbo_rows),'expected_combinations':252,'pbo':pbo_value,'pass_ceiling':pbo_cfg['pass_ceiling'],'pass':pbo_pass,'model_refit_inside_pbo':False,'rows':pbo_rows}
    (out/'pbo_diagnostic.json').write_text(json.dumps(pbo_diag,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    # DSR: fixed non-overlapping test-session anchor within each split.
    dsr_cfg=exe['fingerprint_basis']['dsr_exact']; ret_series={}; sharpes={}; stress={}
    for cid in expected:
        rs=[float(r['top10_gross_excess_20d']) for r in daily[cid] if int(r['test_session_index_within_split'])%20==0 and r.get('top10_gross_excess_20d') is not None and math.isfinite(float(r['top10_gross_excess_20d']))]
        ret_series[cid]=rs; sharpes[cid]=sharpe(rs,np); stress[cid]={str(bps):sharpe([x-bps/10000.0 for x in rs],np) for bps in dsr_cfg['stress_diagnostics_round_trip_bps']}
    dsr_value=None; sr_star=None; selected_sr=None; selected_skew=None; selected_kurt=None; dsr_den=None; dsr_pass=False
    finite_trial=[sharpes[cid] for cid in expected if sharpes[cid] is not None and math.isfinite(sharpes[cid])]
    if selected is not None and len(finite_trial)==11:
        selected_id=selected['candidate_id']; selected_sr=float(sharpes[selected_id]); sigma=float(np.std(np.asarray(finite_trial),ddof=1)); N=11; gamma=0.5772156649015329
        sr_star=float(sigma*((1-gamma)*norm.ppf(1-1/N)+gamma*norm.ppf(1-1/(N*math.e))))
        a=np.asarray(ret_series[selected_id],dtype=float); T=len(a); selected_skew=float(skew(a,bias=False)); selected_kurt=float(kurtosis(a,fisher=False,bias=False)); dsr_den=float(1-selected_skew*selected_sr+((selected_kurt-1)/4)*(selected_sr**2))
        if T>=2 and dsr_den>0:
            z=(selected_sr-sr_star)*math.sqrt(T-1)/math.sqrt(dsr_den); dsr_value=float(norm.cdf(z)); dsr_pass=dsr_value>=float(dsr_cfg['pass_floor'])
    dsr_diag={'method':'BAILEY_LOPEZ_DE_PRADO_DEFLATED_SHARPE_RATIO','trial_count_required':11,'trial_count_finite_sharpe':len(finite_trial),'candidate_sharpes':sharpes,'candidate_stress_sharpes':stress,'selected_candidate':None if selected is None else selected['candidate_id'],'selected_sharpe':selected_sr,'selected_series_observations':0 if selected is None else len(ret_series[selected['candidate_id']]),'selected_skewness':selected_skew,'selected_pearson_kurtosis':selected_kurt,'candidate_sharpe_std':None if len(finite_trial)<2 else float(np.std(np.asarray(finite_trial),ddof=1)),'expected_max_sharpe':sr_star,'dsr_denominator':dsr_den,'dsr_probability':dsr_value,'pass_floor':dsr_cfg['pass_floor'],'pass':dsr_pass,'changes_candidate_selection':False}
    (out/'dsr_diagnostic.json').write_text(json.dumps(dsr_diag,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    selection={'selection_status':'SELECTED' if selected is not None else 'NO_SELECTABLE_CANDIDATE','selected_candidate':None if selected is None else selected['candidate_id'],'primary_median_split_mean_daily_ic_20d':None if selected is None else selected['primary_median_split_mean_daily_ic_20d'],'worst_split_mean_daily_ic_20d':None if selected is None else selected['worst_split_mean_daily_ic_20d'],'complexity_rank':None if selected is None else selected['complexity_rank'],'candidate_ordinal':None if selected is None else selected['ordinal'],'candidate_identity_frozen_by_preregistered_metric_only':True,'pbo_and_dsr_do_not_change_candidate_identity':True}
    (out/'candidate_selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    candidate_table=[{'candidate_id':s['candidate_id'],'ordinal':s['ordinal'],'family':s['family'],'candidate_valid':s['candidate_valid'],'successful_trials':s['successful_trials'],'primary_median_split_mean_daily_ic_20d':s['primary_median_split_mean_daily_ic_20d'],'worst_split_mean_daily_ic_20d':s['worst_split_mean_daily_ic_20d'],'complexity_rank':s['complexity_rank'],'dsr_sharpe':sharpes[s['candidate_id']]} for s in summaries]
    (out/'all_candidate_summary.json').write_text(json.dumps(candidate_table,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    structural_complete=(len(summaries)==11 and total_trials==55 and all(audits[cid]['pass'] for cid in expected))
    overfit_controls_pass=bool(pbo_pass and dsr_pass and all_valid)
    next_gate='SEPARATE_FINAL_DEVELOPMENT_REFIT_AUTHORIZATION' if overfit_controls_pass and selected is not None else 'STOP_OVERFIT_CONTROLS_FAIL_RESEARCH_ONLY'
    manifest={'schema_version':1,'gate':'STAGE4_ALPHA_V1_DEVELOPMENT_CV_EXECUTION','execution_complete':structural_complete,'authorization_fingerprint':auth['fingerprint'],'execution_fingerprint':exe['fingerprint'],'candidate_count':11,'required_trial_records':55,'trial_records':total_trials,'successful_trial_records':successful_trials,'all_candidates_valid':all_valid,'selected_candidate':None if selected is None else selected['candidate_id'],'pbo':pbo_value,'pbo_pass':pbo_pass,'dsr_probability':dsr_value,'dsr_pass':dsr_pass,'overfit_controls_pass':overfit_controls_pass,'research_gate_pass':bool(structural_complete and overfit_controls_pass and selected is not None),'final_development_refit_executed':False,'oos_accessed':False,'lockbox_accessed':False,'live_signal_allowed':False,'authoritative_model_output':False,'next_gate':next_gate}
    (out/'training_execution_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    hashes={p.name:sha256_file(p) for p in out.iterdir() if p.is_file()}; (out/'aggregate_hashes.json').write_text(json.dumps(hashes,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2)); return 0 if structural_complete else 2

if __name__=='__main__': raise SystemExit(main())