#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,sys,time
from datetime import date,timedelta
from pathlib import Path
from decimal import Decimal
import baostock as bs

ROOT=Path(__file__).resolve().parents[1]
START=date(2015,1,1); END=date(2026,7,24); REGISTRATION_MAIN=date(2023,4,10); ST_10PCT=date(2026,7,6)
FIELDS=['exchange','code','trade_date','tradable','risk_warning','preclose','pct_chg','limit_rule','limit_up_rate','limit_down_rate','evidence']

def sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def read_intervals():
    out=[]
    with (ROOT/'data/security_lifecycle/security_intervals.csv').open(encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            a=date.fromisoformat(r['listed_from']); b=date.fromisoformat(r['listed_to_exclusive']) if r['listed_to_exclusive'] else None
            if a<=END and (b is None or b>START): out.append((r,a,b))
    return sorted(out,key=lambda x:(x[0]['exchange'],x[0]['code']))
def bscode(ex,code):return ('sh.' if ex=='SSE' else 'sz.')+code

def query(code,a,b):
    fields='date,code,open,high,low,close,preclose,volume,amount,adjustflag,tradestatus,pctChg,isST'
    rs=bs.query_history_k_data_plus(code,fields,start_date=max(a,START).isoformat(),end_date=min(b or (END+timedelta(days=1)),END).isoformat(),frequency='d',adjustflag='3')
    rows=[]
    while rs.error_code=='0' and rs.next(): rows.append(dict(zip(rs.fields,rs.get_row_data())))
    if rs.error_code!='0': raise RuntimeError(f'{code} {rs.error_code} {rs.error_msg}')
    return rows

def rule(row,listed_from,listed_to,trade_index):
    d=date.fromisoformat(row['date']); trad=row['tradestatus']=='1'; st=row['isST']=='1'
    if not trad:return ('SUSPENDED','','')
    if listed_from>=REGISTRATION_MAIN and trade_index<=5:return ('IPO_FIRST5_NO_LIMIT','','')
    if date(2014,1,1)<=listed_from<REGISTRATION_MAIN and trade_index==1:return ('IPO_FIRST_DAY_2014_RULE','0.44','0.36')
    pct=Decimal(row['pctChg'] or '0')
    # Delisting-consolidation first day / relisting / other exchange-defined no-limit day.
    if abs(pct)>Decimal('10.50'):
        if listed_to and 0 < (listed_to-d).days <= 45:return ('DELISTING_OR_TERMINATION_SPECIAL_NO_LIMIT','','')
        return ('UNCLASSIFIED_SPECIAL_NO_LIMIT','','')
    if st and d<ST_10PCT:return ('RISK_WARNING_5PCT','0.05','0.05')
    if st and d>=ST_10PCT:return ('RISK_WARNING_10PCT','0.10','0.10')
    return ('MAIN_BOARD_10PCT','0.10','0.10')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--shard',type=int,required=True);ap.add_argument('--shards',type=int,required=True);ap.add_argument('--out',required=True);args=ap.parse_args()
    intervals=read_intervals(); selected=[x for i,x in enumerate(intervals) if i%args.shards==args.shard]
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    lg=bs.login();
    if lg.error_code!='0':raise RuntimeError(lg.error_msg)
    normalized=[]; source_manifest=[]; unknown=[]; zero=[]; counts={'securities':0,'rows':0,'tradable':0,'suspended':0,'risk_warning':0}
    try:
      for idx,(meta,a,b) in enumerate(selected):
        code=bscode(meta['exchange'],meta['code']); rows=query(code,a,b); counts['securities']+=1
        if not rows: zero.append(f"{meta['exchange']}:{meta['code']}")
        raw=(json.dumps(rows,ensure_ascii=False,separators=(',',':'))+'\n').encode()
        source_manifest.append({'exchange':meta['exchange'],'code':meta['code'],'rows':len(rows),'sha256':sha(raw),'first':rows[0]['date'] if rows else None,'last':rows[-1]['date'] if rows else None})
        ti=0
        for r in rows:
          d=date.fromisoformat(r['date'])
          if d<max(a,START) or d>END or (b is not None and d>=b): raise ValueError(f'lifecycle violation {code} {d}')
          if r['tradestatus']=='1': ti+=1
          lr,up,dn=rule(r,a,b,ti)
          if lr=='UNCLASSIFIED_SPECIAL_NO_LIMIT': unknown.append({'exchange':meta['exchange'],'code':meta['code'],'date':r['date'],'pctChg':r['pctChg']})
          trad='1' if r['tradestatus']=='1' else '0'; st='1' if r['isST']=='1' else '0'
          counts['rows']+=1;counts['tradable']+=trad=='1';counts['suspended']+=trad=='0';counts['risk_warning']+=st=='1'
          normalized.append({'exchange':meta['exchange'],'code':meta['code'],'trade_date':r['date'],'tradable':trad,'risk_warning':st,'preclose':r['preclose'],'pct_chg':r['pctChg'],'limit_rule':lr,'limit_up_rate':up,'limit_down_rate':dn,'evidence':'BAOSTOCK_POINT_IN_TIME+EXCHANGE_RULE_VERSION'})
        if idx and idx%50==0: time.sleep(0.2)
    finally: bs.logout()
    p=out/f'g4_state_shard{args.shard:02d}.csv.gz'
    normalized.sort(key=lambda r:(r['trade_date'],r['exchange'],r['code']))
    with gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9) as f:
      w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(normalized)
    manifest={'shard':args.shard,'shards':args.shards,'counts':counts,'data_file':p.name,'data_sha256':sha(p.read_bytes()),'source_manifest':source_manifest,'zero_source_securities':zero,'unclassified_special_days':unknown}
    (out/f'g4_manifest_shard{args.shard:02d}.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'shard':args.shard,'counts':counts,'zero':len(zero),'unknown_special':len(unknown)},ensure_ascii=False))
    return 0
if __name__=='__main__':sys.exit(main())
