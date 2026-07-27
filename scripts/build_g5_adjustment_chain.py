#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,sys,time
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path
import baostock as bs

ROOT=Path(__file__).resolve().parents[1]; START='2015-01-01'; END='2026-07-24'
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
 ap=argparse.ArgumentParser();ap.add_argument('--shard',type=int,required=True);ap.add_argument('--shards',type=int,required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 items=[r for i,r in enumerate(read_intervals()) if i%a.shards==a.shard]
 lg=bs.login();
 if lg.error_code!='0':raise RuntimeError(lg.error_msg)
 events=[];src=[];unmatched=[];qerrors=[];div_cache={};securities=0
 try:
  for i,r in enumerate(items):
   code=bscode(r);securities+=1
   try:factors=qfactor(code)
   except Exception as e:qerrors.append({'code':code,'error':repr(e)});continue
   src.append({'exchange':r['exchange'],'code':r['code'],'factor_rows':len(factors),'sha256':sha((json.dumps(factors,ensure_ascii=False,separators=(',',':'))+'\n').encode())})
   for f in factors:
    ed=f.get('dividOperateDate','')
    if not ed or not (START<=ed<=END):continue
    y=int(ed[:4]);k=(code,y)
    if k not in div_cache:
     try:div_cache[k]=qdiv(code,y)
     except Exception:div_cache[k]=[]
    matches=[d for d in div_cache[k] if d.get('dividOperateDate')==ed]
    d=matches[0] if matches else {}
    et=classify(d) if d else 'UNMATCHED_FACTOR_EVENT'
    if not d:unmatched.append({'exchange':r['exchange'],'code':r['code'],'effective_date':ed,'factor':f})
    for fld in ('foreAdjustFactor','backAdjustFactor','adjustFactor'):
     if dec(f.get(fld))<=0:raise ValueError(f'nonpositive factor {code} {ed} {fld}={f.get(fld)}')
    events.append({'exchange':r['exchange'],'code':r['code'],'effective_date':ed,'fore_adjust_factor':f.get('foreAdjustFactor',''),'back_adjust_factor':f.get('backAdjustFactor',''),'adjust_factor':f.get('adjustFactor',''),'event_type':et,'cash_ps_before_tax':d.get('dividCashPsBeforeTax',''),'stock_ps':d.get('dividStocksPs',''),'reserve_to_stock_ps':d.get('dividReserveToStockPs',''),'event_detail':d.get('dividCashStock',''),'evidence':'BAOSTOCK_ADJUST_FACTOR'+('+DIVIDEND_DETAIL' if d else '')})
   if i and i%50==0:time.sleep(.2)
 finally:bs.logout()
 p=out/f'g5_events_shard{a.shard:02d}.csv.gz';events.sort(key=lambda x:(x['effective_date'],x['exchange'],x['code']))
 with gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9) as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(events)
 m={'shard':a.shard,'shards':a.shards,'securities':securities,'events':len(events),'unmatched_factor_events':unmatched,'query_errors':qerrors,'source_manifest':src,'data_file':p.name,'data_sha256':sha(p.read_bytes())}
 (out/f'g5_manifest_shard{a.shard:02d}.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'shard':a.shard,'securities':securities,'events':len(events),'unmatched':len(unmatched),'errors':len(qerrors)},ensure_ascii=False));return 0
if __name__=='__main__':sys.exit(main())
