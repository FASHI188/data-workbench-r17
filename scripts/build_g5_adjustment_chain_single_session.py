#!/usr/bin/env python3
from __future__ import annotations
import csv,gzip,hashlib,json,sys,time
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path
import baostock as bs

ROOT=Path(__file__).resolve().parents[1]; START='2015-01-01'; END='2026-07-24'; SHARDS=16
FIELDS=['exchange','code','effective_date','fore_adjust_factor','back_adjust_factor','adjust_factor','event_type','cash_ps_before_tax','stock_ps','reserve_to_stock_ps','event_detail','evidence']
def sha(b):return hashlib.sha256(b).hexdigest()
def dec(x):
 try:return Decimal(str(x or '0'))
 except InvalidOperation:return Decimal('0')
def read_intervals():
 out=[]
 with (ROOT/'data/security_lifecycle/security_intervals.csv').open(encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):
   a=date.fromisoformat(r['listed_from']);b=date.fromisoformat(r['listed_to_exclusive']) if r['listed_to_exclusive'] else None
   if a<=date.fromisoformat(END) and (b is None or b>date.fromisoformat(START)):out.append(r)
 return sorted(out,key=lambda r:(r['exchange'],r['code']))
def bscode(r):return ('sh.' if r['exchange']=='SSE' else 'sz.')+r['code']
def collect(rs):
 rows=[]
 while rs.error_code=='0' and rs.next():rows.append(dict(zip(rs.fields,rs.get_row_data())))
 if rs.error_code!='0':raise RuntimeError(f'{rs.error_code} {rs.error_msg}')
 return rows
def qfactor(code):return collect(bs.query_adjust_factor(code=code,start_date=START,end_date=END))
def qdiv(code,year):return collect(bs.query_dividend_data(code=code,year=str(year),yearType='operate'))
def classify(d):
 cash=dec(d.get('dividCashPsBeforeTax'));stock=dec(d.get('dividStocksPs'));reserve=dec(d.get('dividReserveToStockPs'))
 if cash>0 and (stock>0 or reserve>0):return 'CASH_AND_STOCK_DISTRIBUTION'
 if cash>0:return 'CASH_DIVIDEND'
 if stock>0 or reserve>0:return 'STOCK_DIVIDEND_OR_CAPITAL_TRANSFER'
 return 'DIVIDEND_RECORD_OTHER'
def main():
 out=ROOT/'build/g5-single';out.mkdir(parents=True,exist_ok=True)
 handles=[];writers=[];files=[];mans=[{'shard':i,'shards':SHARDS,'securities':0,'events':0,'matched_events':0,'unmatched_factor_events':[],'query_errors':[],'source_manifest':[]} for i in range(SHARDS)]
 try:
  for i in range(SHARDS):
   p=out/f'g5_events_shard{i:02d}.csv.gz';h=gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9);w=csv.DictWriter(h,fieldnames=FIELDS);w.writeheader();files.append(p);handles.append(h);writers.append(w)
  lg=bs.login()
  if lg.error_code!='0':raise RuntimeError('BaoStock login failed: '+lg.error_msg)
  div_cache={}
  try:
   for idx,r in enumerate(read_intervals()):
    sid=idx%SHARDS;m=mans[sid];m['securities']+=1;code=bscode(r)
    try:factors=qfactor(code)
    except Exception as e:m['query_errors'].append({'code':code,'error':repr(e)});continue
    raw=(json.dumps(factors,ensure_ascii=False,separators=(',',':'))+'\n').encode();m['source_manifest'].append({'exchange':r['exchange'],'code':r['code'],'factor_rows':len(factors),'sha256':sha(raw)})
    for f in factors:
     ed=f.get('dividOperateDate','')
     if not ed or not (START<=ed<=END):continue
     if min(dec(f.get('foreAdjustFactor')),dec(f.get('backAdjustFactor')),dec(f.get('adjustFactor')))<=0:raise ValueError(f'nonpositive factor {code} {ed} {f}')
     y=int(ed[:4]);key=(code,y)
     if key not in div_cache:
      try:div_cache[key]=qdiv(code,y)
      except Exception as e:div_cache[key]=[];m['query_errors'].append({'code':code,'year':y,'kind':'dividend','error':repr(e)})
     matches=[d for d in div_cache[key] if d.get('dividOperateDate')==ed];d=matches[0] if matches else {}
     et=classify(d) if d else 'UNMATCHED_FACTOR_EVENT'
     if not d:m['unmatched_factor_events'].append({'exchange':r['exchange'],'code':r['code'],'effective_date':ed,'factor':f})
     else:m['matched_events']+=1
     writers[sid].writerow({'exchange':r['exchange'],'code':r['code'],'effective_date':ed,'fore_adjust_factor':f.get('foreAdjustFactor',''),'back_adjust_factor':f.get('backAdjustFactor',''),'adjust_factor':f.get('adjustFactor',''),'event_type':et,'cash_ps_before_tax':d.get('dividCashPsBeforeTax',''),'stock_ps':d.get('dividStocksPs',''),'reserve_to_stock_ps':d.get('dividReserveToStockPs',''),'event_detail':d.get('dividCashStock',''),'evidence':'BAOSTOCK_ADJUST_FACTOR'+('+DIVIDEND_DETAIL' if d else '')});m['events']+=1
    if idx and idx%100==0:time.sleep(.25)
  finally:bs.logout()
 finally:
  for h in handles:h.close()
 for i,p in enumerate(files):
  mans[i]['data_file']=p.name;mans[i]['data_sha256']=sha(p.read_bytes());(out/f'g5_manifest_shard{i:02d}.json').write_text(json.dumps(mans[i],ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'securities':sum(m['securities'] for m in mans),'events':sum(m['events'] for m in mans),'matched':sum(m['matched_events'] for m in mans),'unmatched':sum(len(m['unmatched_factor_events']) for m in mans),'query_errors':sum(len(m['query_errors']) for m in mans)},ensure_ascii=False));return 0
if __name__=='__main__':sys.exit(main())
