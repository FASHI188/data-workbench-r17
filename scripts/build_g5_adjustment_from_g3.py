#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,heapq,json,sys
from datetime import date
from decimal import Decimal,InvalidOperation,getcontext
from pathlib import Path
getcontext().prec=28
FIELDS=['exchange','code','ex_date','action_type','cash_per_share','bonus_per_share','transfer_per_share','rights_per_share','rights_price','prior_reference_price','ex_reference_price','continuity_ratio','back_adjust_multiplier','cumulative_back_adjust_multiplier','source_count','source_evidence']
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
 sse=sorted((g3root/'build/g3/sse').glob(f'sse_{y}_shard*.csv.gz'));sz=g3root/f'build/g3/szse/szse_{y}.csv.gz'
 paths=sse+([sz] if sz.exists() else [])
 return paths
def row_key(r):return (r['trade_date'],r['exchange'],r['code'])
def calc_event(r,ref,cumulative):
 cash=D(r['cash_per_share']);bonus=D(r['bonus_per_share']);transfer=D(r['transfer_per_share']);rights=D(r['rights_per_share']);rp=D(r['rights_price'])
 denom=Decimal(1)+bonus+transfer+rights
 ex=(ref-cash+rp*rights)/denom
 if ref<=0 or denom<=0 or ex<=0:raise ValueError(f'invalid ex-reference input ref={ref} cash={cash} bonus={bonus} transfer={transfer} rights={rights} price={rp} -> ex={ex}')
 continuity=ex/ref;back=ref/ex;newcum=cumulative*back
 return ex,continuity,back,newcum
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--actions',required=True);ap.add_argument('--g3-root',required=True);ap.add_argument('--out',required=True);args=ap.parse_args();actions=read_actions(Path(args.actions));g3=Path(args.g3_root);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
 by_year={};expected=[]
 for r in actions:by_year.setdefault(int(r['ex_date'][:4]),[]).append(r)
 ref={};cum={};result=[];errors=[];processed=set();trade_rows=0
 for y in range(2015,2027):
  evs=by_year.get(y,[]);ei=0;paths=year_paths(g3,y)
  if not paths:errors.append(f'missing G3 files for {y}');continue
  merged=heapq.merge(*(iter_csv(p) for p in paths),key=row_key)
  current_day=None;day_rows=[]
  def process_events_until(day,include_equal=True):
   nonlocal ei
   while ei<len(evs) and (evs[ei]['ex_date']<day or (include_equal and evs[ei]['ex_date']==day)):
    e=evs[ei];k=(e['exchange'],e['code']);base=ref.get(k);c=cum.get(k,Decimal(1));idk=(e['exchange'],e['code'],e['ex_date'])
    if base is None:
     errors.append(f'missing prior close/reference for {idk}')
    else:
     try:
      ex,cont,back,newc=calc_event(e,base,c);ref[k]=ex;cum[k]=newc;processed.add(idk)
      result.append({'exchange':e['exchange'],'code':e['code'],'ex_date':e['ex_date'],'action_type':e['action_type'],'cash_per_share':e['cash_per_share'],'bonus_per_share':e['bonus_per_share'],'transfer_per_share':e['transfer_per_share'],'rights_per_share':e['rights_per_share'],'rights_price':e['rights_price'],'prior_reference_price':format(base,'f'),'ex_reference_price':format(ex,'f'),'continuity_ratio':format(cont,'f'),'back_adjust_multiplier':format(back,'f'),'cumulative_back_adjust_multiplier':format(newc,'f'),'source_count':e['source_count'],'source_evidence':e['source_evidence']})
     except Exception as exc:errors.append(f'{idk}: {exc}')
    ei+=1
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
  while ei<len(evs):
   e=evs[ei];k=(e['exchange'],e['code']);base=ref.get(k);c=cum.get(k,Decimal(1));idk=(e['exchange'],e['code'],e['ex_date'])
   if base is None:errors.append(f'missing prior close/reference for {idk}')
   else:
    try:
     ex,cont,back,newc=calc_event(e,base,c);ref[k]=ex;cum[k]=newc;processed.add(idk);result.append({'exchange':e['exchange'],'code':e['code'],'ex_date':e['ex_date'],'action_type':e['action_type'],'cash_per_share':e['cash_per_share'],'bonus_per_share':e['bonus_per_share'],'transfer_per_share':e['transfer_per_share'],'rights_per_share':e['rights_per_share'],'rights_price':e['rights_price'],'prior_reference_price':format(base,'f'),'ex_reference_price':format(ex,'f'),'continuity_ratio':format(cont,'f'),'back_adjust_multiplier':format(back,'f'),'cumulative_back_adjust_multiplier':format(newc,'f'),'source_count':e['source_count'],'source_evidence':e['source_evidence']})
    except Exception as exc:errors.append(f'{idk}: {exc}')
   ei+=1
 expected={(r['exchange'],r['code'],r['ex_date']) for r in actions}
 missing=sorted(expected-processed)
 if missing:errors.append(f'unprocessed official actions: {missing[:30]} count={len(missing)}')
 p=out/'g5_adjustment_chain.csv.gz';result.sort(key=lambda r:(r['ex_date'],r['exchange'],r['code']))
 with gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9) as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(result)
 digest=hashlib.sha256(p.read_bytes()).hexdigest();g3audit=Path(g3/'data/ohlcv/g3_audit.json');g3meta=json.loads(g3audit.read_text(encoding='utf-8')) if g3audit.exists() else {}
 report={'stage':'G5_ADJUSTMENT_CHAIN','pass':not errors,'coverage_start':'2015-01-01','coverage_end':'2026-07-24','official_action_count':len(actions),'adjustment_event_count':len(result),'g3_trade_rows_scanned':trade_rows,'g3_dataset_fingerprint':g3meta.get('dataset_fingerprint'),'adjustment_chain_sha256':digest,'errors':errors}
 (out/'g5_adjustment_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
