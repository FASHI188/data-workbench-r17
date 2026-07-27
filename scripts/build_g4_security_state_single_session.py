#!/usr/bin/env python3
from __future__ import annotations
import csv,gzip,hashlib,json,sys,time
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path
import baostock as bs

ROOT=Path(__file__).resolve().parents[1]
START=date(2015,1,1); END=date(2026,7,24); REGISTRATION_MAIN=date(2023,4,10); ST_10PCT=date(2026,7,6); DELIST_REFORM=date(2020,12,31); SHARDS=16
FIELDS=['exchange','code','trade_date','tradable','risk_warning','preclose','pct_chg','limit_rule','limit_up_rate','limit_down_rate','evidence']

def sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def read_intervals():
 out=[]
 with (ROOT/'data/security_lifecycle/security_intervals.csv').open(encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):
   a=date.fromisoformat(r['listed_from']);b=date.fromisoformat(r['listed_to_exclusive']) if r['listed_to_exclusive'] else None
   if a<=END and (b is None or b>START):out.append((r,a,b))
 return sorted(out,key=lambda x:(x[0]['exchange'],x[0]['code']))
def bscode(ex,c):return ('sh.' if ex=='SSE' else 'sz.')+c

def query(code,a,b):
 start=max(a,START);end=END if b is None else min(END,b-timedelta(days=1))
 if end<start:return []
 fields='date,code,open,high,low,close,preclose,volume,amount,adjustflag,tradestatus,pctChg,isST'
 rs=bs.query_history_k_data_plus(code,fields,start_date=start.isoformat(),end_date=end.isoformat(),frequency='d',adjustflag='3')
 rows=[]
 while rs.error_code=='0' and rs.next():rows.append(dict(zip(rs.fields,rs.get_row_data())))
 if rs.error_code!='0':raise RuntimeError(f'{code} {rs.error_code} {rs.error_msg}')
 return rows

def delisting_period(rows,listed_to):
 """Infer final delisting-consolidation block and its historical rule regime.

 Pre-2020-reform regime: 30 trading days, all days at 10%.
 New rules published 2020-12-31: 15 trading days, first day no daily price limit, later 10%.
 Transitional 2021 issuers can still use old rules, so a >15-day observed final block stays old-regime.
 """
 if not listed_to or not rows:return None
 near=[r for r in rows if 0 < (listed_to-date.fromisoformat(r['date'])).days <=120]
 if not near:return None
 trade_idx=[i for i,r in enumerate(near) if r['tradestatus']=='1']
 if not trade_idx:return None
 last=trade_idx[-1];candidate=None
 for i in range(max(0,last-55),last+1):
  if near[i]['tradestatus']!='1':continue
  prior=near[max(0,i-10):i]
  if len(prior)>=5 and sum(x['tradestatus']=='0' for x in prior)>=5:
   later=[x['date'] for x in near[i:last+1] if x['tradestatus']=='1']
   if 1<=len(later)<=30:
    candidate=later;break
 if not candidate:return None
 n=len(candidate);first=date.fromisoformat(candidate[0])
 if first < DELIST_REFORM or n>15:regime='OLD_30DAY_ALL_10PCT'
 else:regime='NEW_15DAY_FIRST_NO_LIMIT'
 return {'first_date':candidate[0],'last_date':candidate[-1],'trade_dates':set(candidate),'trade_days':n,'regime':regime}

def base_rule(r,listed_from,trade_index,delist):
 d=date.fromisoformat(r['date']);trad=r['tradestatus']=='1';st=r['isST']=='1'
 if not trad:return ('SUSPENDED','','','BAOSTOCK_POINT_IN_TIME')
 if delist and r['date'] in delist['trade_dates']:
  if delist['regime']=='NEW_15DAY_FIRST_NO_LIMIT' and r['date']==delist['first_date']:
   return ('DELISTING_15DAY_FIRST_DAY_NO_LIMIT','','','BAOSTOCK_POINT_IN_TIME+EXCHANGE_2020_DELISTING_REFORM+FINAL_TRADING_BLOCK')
  return ('DELISTING_CONSOLIDATION_10PCT','0.10','0.10','BAOSTOCK_POINT_IN_TIME+EXCHANGE_DELISTING_RULE+FINAL_TRADING_BLOCK')
 if listed_from>=REGISTRATION_MAIN and trade_index<=5:return ('IPO_FIRST5_NO_LIMIT','','','LIFECYCLE+EXCHANGE_REGISTRATION_RULE')
 if date(2014,1,1)<=listed_from<REGISTRATION_MAIN and trade_index==1:return ('IPO_FIRST_DAY_2014_RULE','0.44','0.36','LIFECYCLE+EXCHANGE_IPO_RULE')
 if st and d<ST_10PCT:return ('RISK_WARNING_5PCT','0.05','0.05','BAOSTOCK_POINT_IN_TIME+EXCHANGE_RULE_VERSION')
 if st and d>=ST_10PCT:return ('RISK_WARNING_10PCT','0.10','0.10','BAOSTOCK_POINT_IN_TIME+EXCHANGE_RULE_VERSION')
 return ('MAIN_BOARD_10PCT','0.10','0.10','EXCHANGE_RULE_VERSION')

def main():
 out=ROOT/'build/g4-single';out.mkdir(parents=True,exist_ok=True)
 files=[];writers=[];handles=[];man=[{'shard':i,'shards':SHARDS,'counts':{'securities':0,'rows':0,'tradable':0,'suspended':0,'risk_warning':0},'source_manifest':[],'zero_source_securities':[],'unclassified_special_days':[],'delisting_first_days':[],'delisting_periods':[]} for i in range(SHARDS)]
 try:
  for i in range(SHARDS):
   p=out/f'g4_state_shard{i:02d}.csv.gz';h=gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9);w=csv.DictWriter(h,fieldnames=FIELDS);w.writeheader();files.append(p);handles.append(h);writers.append(w)
  lg=bs.login()
  if lg.error_code!='0':raise RuntimeError('BaoStock login failed: '+lg.error_msg)
  try:
   for idx,(meta,a,b) in enumerate(read_intervals()):
    sid=idx%SHARDS;m=man[sid];m['counts']['securities']+=1;code=bscode(meta['exchange'],meta['code'])
    rows=query(code,a,b)
    raw=(json.dumps(rows,ensure_ascii=False,separators=(',',':'))+'\n').encode();m['source_manifest'].append({'exchange':meta['exchange'],'code':meta['code'],'rows':len(rows),'sha256':sha(raw),'first':rows[0]['date'] if rows else None,'last':rows[-1]['date'] if rows else None})
    if not rows:m['zero_source_securities'].append(f"{meta['exchange']}:{meta['code']}")
    dp=delisting_period(rows,b)
    if dp:
     m['delisting_first_days'].append({'exchange':meta['exchange'],'code':meta['code'],'date':dp['first_date']})
     m['delisting_periods'].append({'exchange':meta['exchange'],'code':meta['code'],'first_date':dp['first_date'],'last_date':dp['last_date'],'trade_days':dp['trade_days'],'regime':dp['regime']})
    ti=0
    for r in rows:
     d=date.fromisoformat(r['date'])
     if d<max(a,START) or d>END or (b is not None and d>=b):raise ValueError(f'lifecycle violation {code} {d}')
     if r['tradestatus']=='1':ti+=1
     lr,up,dn,evidence=base_rule(r,a,ti,dp)
     pct=Decimal(r['pctChg'] or '0')
     if r['tradestatus']=='1' and abs(pct)>Decimal('10.50') and 'NO_LIMIT' not in lr and lr!='IPO_FIRST_DAY_2014_RULE':m['unclassified_special_days'].append({'exchange':meta['exchange'],'code':meta['code'],'date':r['date'],'pctChg':r['pctChg'],'rule':lr})
     trad='1' if r['tradestatus']=='1' else '0';st='1' if r['isST']=='1' else '0';m['counts']['rows']+=1;m['counts']['tradable']+=trad=='1';m['counts']['suspended']+=trad=='0';m['counts']['risk_warning']+=st=='1'
     writers[sid].writerow({'exchange':meta['exchange'],'code':meta['code'],'trade_date':r['date'],'tradable':trad,'risk_warning':st,'preclose':r['preclose'],'pct_chg':r['pctChg'],'limit_rule':lr,'limit_up_rate':up,'limit_down_rate':dn,'evidence':evidence})
    if idx and idx%100==0:time.sleep(.25)
  finally:bs.logout()
 finally:
  for h in handles:h.close()
 for i,p in enumerate(files):
  man[i]['data_file']=p.name;man[i]['data_sha256']=sha(p.read_bytes());(out/f'g4_manifest_shard{i:02d}.json').write_text(json.dumps(man[i],ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'securities':sum(x['counts']['securities'] for x in man),'rows':sum(x['counts']['rows'] for x in man),'zero':sum(len(x['zero_source_securities']) for x in man),'unclassified':sum(len(x['unclassified_special_days']) for x in man),'delisting_periods':sum(len(x['delisting_periods']) for x in man)},ensure_ascii=False))
 return 0
if __name__=='__main__':sys.exit(main())
