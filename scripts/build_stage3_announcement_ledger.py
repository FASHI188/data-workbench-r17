#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,math,time
from datetime import date,timedelta,datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

ROOT=Path(__file__).resolve().parents[1]
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
QUERY="https://www.cninfo.com.cn/new/hisAnnouncement/query";STOCKMAP="https://www.cninfo.com.cn/new/data/szse_stock.json";STATIC="https://static.cninfo.com.cn/"
START=date(2015,1,1);END=date(2026,7,24);PAGE=30;TZ=ZoneInfo('Asia/Shanghai')
CATEGORIES={
 'EARNINGS_FORECAST':'category_yjygjxz_szsh','DAILY_OPERATION':'category_rcjy_szsh','EQUITY_CHANGE':'category_gqbd_szsh',
 'CORRECTION_SUPPLEMENT':'category_bcgz_szsh','CLARIFICATION_APOLOGY':'category_cqdq_szsh','RISK_WARNING':'category_fxts_szsh',
 'SPECIAL_TREATMENT_DELISTING':'category_tbclts_szsh','DELISTING_PERIOD':'category_tszlq_szsh','UNLOCK':'category_jj_szsh',
 'EQUITY_INCENTIVE':'category_gqjl_szsh','ADDITIONAL_ISSUANCE':'category_zf_szsh','RIGHTS_ISSUE':'category_pg_szsh',
 'CONVERTIBLE_BOND':'category_kzzq_szsh','OTHER_FINANCING':'category_qtrz_szsh'}
FIELDS=['exchange','code','org_id','event_category','announcement_id','announcement_title','source_published_date','announcement_time_raw','source_url','query_page','query_response_sha256']

def sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def stable_shard(ex,code,n):return int(hashlib.sha256(f'{ex}:{code}'.encode()).hexdigest()[:16],16)%n
def intervals():
 out=[]
 with (ROOT/'data/security_lifecycle/security_intervals.csv').open(encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):
   a=date.fromisoformat(r['listed_from']);b=date.fromisoformat(r['listed_to_exclusive']) if r.get('listed_to_exclusive') else None
   if a<=END and (b is None or b>START):out.append({**r,'_from':a,'_to':b})
 return sorted(out,key=lambda r:(r['exchange'],r['code']))
def window(r):return max(START,r['_from']), END if r['_to'] is None else min(END,r['_to']-timedelta(days=1))
def pubdate(item):
 try:return datetime.fromtimestamp(int(item['announcementTime'])/1000,tz=ZoneInfo('UTC')).astimezone(TZ).date().isoformat()
 except Exception:return ''
def payload(code,org,cat,a,b,p):return {'pageNum':str(p),'pageSize':str(PAGE),'column':'szse','tabName':'fulltext','plate':'','stock':f'{code},{org}','searchkey':'','secid':'','category':cat,'trade':'','seDate':f'{a.isoformat()}~{b.isoformat()}','sortName':'','sortType':'','isHLtitle':'true'}
def post(s,pay,attempts=6):
 last=None
 for i in range(attempts):
  try:
   r=s.post(QUERY,data=pay,headers={'User-Agent':UA,'Referer':'https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search','X-Requested-With':'XMLHttpRequest'},timeout=60);r.raise_for_status();o=r.json()
   if not isinstance(o,dict) or 'announcements' not in o:raise ValueError('unexpected payload')
   return r.content,o
  except Exception as exc:
   last=exc
   if i+1<attempts:time.sleep(min(.6*2**i,8))
 raise RuntimeError(repr(last))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--shard',type=int,required=True);ap.add_argument('--shards',type=int,default=16);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 secs=[r for r in intervals() if stable_shard(r['exchange'],r['code'],a.shards)==a.shard];s=requests.Session();smr=s.get(STOCKMAP,headers={'User-Agent':UA,'Referer':'https://www.cninfo.com.cn/'},timeout=60);smr.raise_for_status();sl=smr.json().get('stockList') or [];sm={str(x.get('code')):str(x.get('orgId')) for x in sl if x.get('code') and x.get('orgId')}
 rows=[];req=[];errors=[];totals={k:0 for k in CATEGORIES}
 for i,sec in enumerate(secs,1):
  code=sec['code'];org=sm.get(code);wa,wb=window(sec)
  if not org:errors.append(f'missing orgId {sec["exchange"]}:{code}');continue
  for label,cat in CATEGORIES.items():
   try:
    raw,obj=post(s,payload(code,org,cat,wa,wb,1));total=int(obj.get('totalAnnouncement') or 0);pages=max(1,math.ceil(total/PAGE));packs=[(1,raw,obj)]
    for pn in range(2,pages+1):packs.append((pn,*post(s,payload(code,org,cat,wa,wb,pn))))
    seen=set()
    for pn,rb,ob in packs:
     anns=ob.get('announcements') or [];req.append({'exchange':sec['exchange'],'code':code,'category':label,'page':pn,'total':total,'rows':len(anns),'sha256':sha(rb)})
     for x in anns:
      aid=str(x.get('announcementId') or '');sc=str(x.get('secCode') or '')
      if not aid:errors.append(f'missing aid {code} {label}');continue
      if sc!=code:errors.append(f'code mismatch {code}->{sc} aid={aid}');continue
      if aid in seen:continue
      seen.add(aid);u=str(x.get('adjunctUrl') or '').lstrip('/')
      rows.append({'exchange':sec['exchange'],'code':code,'org_id':org,'event_category':label,'announcement_id':aid,'announcement_title':str(x.get('announcementTitle') or ''),'source_published_date':pubdate(x),'announcement_time_raw':str(x.get('announcementTime') or ''),'source_url':STATIC+u if u else '','query_page':str(pn),'query_response_sha256':sha(rb)})
    totals[label]+=total
   except Exception as exc:errors.append(f'{sec["exchange"]}:{code} {label}: {exc!r}')
   time.sleep(.02)
  if i%30==0:print(f'shard {a.shard}/{a.shards} {i}/{len(secs)}',flush=True)
 rows.sort(key=lambda r:(r['source_published_date'],r['exchange'],r['code'],r['announcement_id'],r['event_category']))
 p=out/f'announcement_ledger_shard{a.shard:02d}.csv.gz'
 with gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9) as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
 m={'gate':'S3G2_ANNOUNCEMENT_LEDGER_SHARD','shard':a.shard,'shards':a.shards,'security_identities':len(secs),'rows':len(rows),'query_pages':len(req),'category_totals':totals,'stock_map_sha256':sha(smr.content),'data_sha256':sha(p.read_bytes()),'errors':errors}
 (out/f'announcement_ledger_shard{a.shard:02d}.manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'shard':a.shard,'securities':len(secs),'rows':len(rows),'pages':len(req),'errors':len(errors)},ensure_ascii=False));return 0 if not errors else 2
if __name__=='__main__':raise SystemExit(main())
