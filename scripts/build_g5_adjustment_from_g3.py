#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,heapq,json,sys
from decimal import Decimal,InvalidOperation,getcontext
from pathlib import Path
getcontext().prec=28
FIELDS=['exchange','code','ex_date','action_type','cash_per_share','bonus_per_share','transfer_per_share','rights_per_share','rights_price','prior_reference_price','ex_reference_price','continuity_ratio','back_adjust_multiplier','cumulative_back_adjust_multiplier','reference_source','source_count','source_evidence']
def D(v):
 try:return Decimal(str(v or '0'))
 except InvalidOperation:return Decimal('0')
def read_actions(path):
 rows=[]
 with gzip.open(path,'rt',encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):rows.append(r)
 rows.sort(key=lambda r:(r['ex_date'],r['exchange'],r['code']));return rows
def iter_csv(path):
 with gzip.open(path,'rt',encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):yield r
def year_paths(g3root,y):
 sse=sorted((g3root/'build/g3/sse').glob(f'sse_{y}_shard*.csv.gz'));sz=g3root/f'build/g3/szse/szse_{y}.csv.gz';return sse+([sz] if sz.exists() else [])
def row_key(r):return (r['trade_date'],r['exchange'],r['code'])
def calc_event(r,ref,cumulative):
 cash=D(r['cash_per_share']);bonus=D(r['bonus_per_share']);transfer=D(r['transfer_per_share']);rights=D(r['rights_per_share']);rp=D(r['rights_price']);denom=Decimal(1)+bonus+transfer+rights;ex=(ref-cash+rp*rights)/denom
 if ref<=0 or denom<=0 or ex<=0:raise ValueError(f'invalid ex-reference input ref={ref} cash={cash} bonus={bonus} transfer={transfer} rights={rights} price={rp} -> ex={ex}')
 continuity=ex/ref;back=ref/ex;newcum=cumulative*back;return ex,continuity,back,newcum
def load_g4_action_controls(g4root:Path|None,actions):
 if g4root is None:return {},0
 wanted={(r['exchange'],r['code'],r['ex_date']) for r in actions};out={};scanned=0
 for p in sorted(g4root.rglob('g4_state_shard*.csv.gz')):
  with gzip.open(p,'rt',encoding='utf-8',newline='') as f:
   for r in csv.DictReader(f):
    scanned+=1;k=(r['exchange'],r['code'],r['trade_date'])
    if k in wanted:out[k]=r
 return out,scanned
def bootstrap_suspended_reference(e,g4_controls):
 idk=(e['exchange'],e['code'],e['ex_date']);r=g4_controls.get(idk)
 if not r:return None,None
 if r.get('tradable')!='0':return None,None
 exref=D(r.get('preclose'))
 if exref<=0:return None,None
 cash=D(e['cash_per_share']);bonus=D(e['bonus_per_share']);transfer=D(e['transfer_per_share']);rights=D(e['rights_per_share']);rp=D(e['rights_price']);denom=Decimal(1)+bonus+transfer+rights;prior=exref*denom+cash-rp*rights
 if prior<=0:return None,None
 check,_,_,_=calc_event(e,prior,Decimal(1))
 if abs(check-exref)>Decimal('0.0000001'):raise ValueError(f'G4 suspended bootstrap inversion mismatch for {idk}: reconstructed={check} g4_preclose={exref}')
 return prior,{'exchange':e['exchange'],'code':e['code'],'ex_date':e['ex_date'],'g4_preclose':str(exref),'derived_prior_reference':str(prior),'g4_evidence':r.get('evidence'),'policy':'G4_SUSPENDED_EXDATE_PRECLOSE_INVERSION'}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--actions',required=True);ap.add_argument('--g3-root',required=True);ap.add_argument('--g4-root');ap.add_argument('--out',required=True);args=ap.parse_args();actions=read_actions(Path(args.actions));g3=Path(args.g3_root);out=Path(args.out);out.mkdir(parents=True,exist_ok=True);g4_controls,g4_rows_scanned=load_g4_action_controls(Path(args.g4_root) if args.g4_root else None,actions)
 by_year={}
 for r in actions:by_year.setdefault(int(r['ex_date'][:4]),[]).append(r)
 ref={};cum={};result=[];errors=[];processed=set();trade_rows=0;bootstraps=[]
 def append_event(e,base,c,newc,ex,cont,back,source):
  result.append({'exchange':e['exchange'],'code':e['code'],'ex_date':e['ex_date'],'action_type':e['action_type'],'cash_per_share':e['cash_per_share'],'bonus_per_share':e['bonus_per_share'],'transfer_per_share':e['transfer_per_share'],'rights_per_share':e['rights_per_share'],'rights_price':e['rights_price'],'prior_reference_price':format(base,'f'),'ex_reference_price':format(ex,'f'),'continuity_ratio':format(cont,'f'),'back_adjust_multiplier':format(back,'f'),'cumulative_back_adjust_multiplier':format(newc,'f'),'reference_source':source,'source_count':e['source_count'],'source_evidence':e['source_evidence']})
 def execute(e):
  idk=(e['exchange'],e['code'],e['ex_date']);k=(e['exchange'],e['code']);base=ref.get(k);source='G3_PRIOR_CLOSE_OR_PRIOR_OFFICIAL_ADJUSTMENT'
  if base is None:
   try:base,meta=bootstrap_suspended_reference(e,g4_controls)
   except Exception as exc:errors.append(f'{idk}: {exc}');return
   if base is None:errors.append(f'missing prior close/reference for {idk}');return
   bootstraps.append(meta);source='G4_SUSPENDED_EXDATE_PRECLOSE_INVERSION'
  c=cum.get(k,Decimal(1))
  try:
   ex,cont,back,newc=calc_event(e,base,c);ref[k]=ex;cum[k]=newc;processed.add(idk);append_event(e,base,c,newc,ex,cont,back,source)
  except Exception as exc:errors.append(f'{idk}: {exc}')
 for y in range(2015,2027):
  evs=by_year.get(y,[]);ei=0;paths=year_paths(g3,y)
  if not paths:errors.append(f'missing G3 files for {y}');continue
  merged=heapq.merge(*(iter_csv(p) for p in paths),key=row_key);current_day=None;day_rows=[]
  def process_events_until(day,include_equal=True):
   nonlocal ei
   while ei<len(evs) and (evs[ei]['ex_date']<day or (include_equal and evs[ei]['ex_date']==day)):
    execute(evs[ei]);ei+=1
  for r in merged:
   trade_rows+=1;d=r['trade_date']
   if current_day is None:current_day=d
   if d!=current_day:
    process_events_until(current_day,True)
    for q in day_rows:ref[(q['exchange'],q['code'])]=D(q['close'])
    day_rows=[];current_day=d
   day_rows.append(r)
  if current_day is not None:
   process_events_until(current_day,True)
   for q in day_rows:ref[(q['exchange'],q['code'])]=D(q['close'])
  while ei<len(evs):execute(evs[ei]);ei+=1
 expected={(r['exchange'],r['code'],r['ex_date']) for r in actions};missing=sorted(expected-processed)
 if missing:errors.append(f'unprocessed official actions: {missing[:30]} count={len(missing)}')
 p=out/'g5_adjustment_chain.csv.gz';result.sort(key=lambda r:(r['ex_date'],r['exchange'],r['code']))
 with gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9) as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(result)
 digest=hashlib.sha256(p.read_bytes()).hexdigest();g3audit=Path(g3/'data/ohlcv/g3_audit.json');g3meta=json.loads(g3audit.read_text(encoding='utf-8')) if g3audit.exists() else {}
 report={'stage':'G5_ADJUSTMENT_CHAIN','pass':not errors,'coverage_start':'2015-01-01','coverage_end':'2026-07-24','official_action_count':len(actions),'adjustment_event_count':len(result),'g3_trade_rows_scanned':trade_rows,'g4_control_rows_scanned':g4_rows_scanned,'suspended_reference_bootstrap_count':len(bootstraps),'suspended_reference_bootstraps':bootstraps,'g3_dataset_fingerprint':g3meta.get('dataset_fingerprint'),'adjustment_chain_sha256':digest,'errors':errors}
 (out/'g5_adjustment_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
