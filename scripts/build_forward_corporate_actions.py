#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,json,time
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path

import requests
import build_g5_official_actions as g5

ROOT=Path(__file__).resolve().parents[1]
MASTER=ROOT/'data/current_master/cn_main_a.csv'
MASTER_MANIFEST=ROOT/'data/current_master/manifest.json'
STAGE2_FINAL=ROOT/'data/stage2_final/manifest.json'
FIELDS=g5.FIELDS

def bounds():
 s2=json.loads(STAGE2_FINAL.read_text(encoding='utf-8')); mm=json.loads(MASTER_MANIFEST.read_text(encoding='utf-8'))
 frozen=date.fromisoformat(str((s2.get('fingerprint_basis') or {}).get('coverage_end') or ''))
 current=date.fromisoformat(str((mm.get('szse') or {}).get('as_of') or ''))
 nxt=current+timedelta(days=1)
 while nxt.weekday()>=5:nxt+=timedelta(days=1)
 return frozen,current,nxt

def codes(exchange):
 out=[]
 with MASTER.open(encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):
   if r.get('exchange')==exchange:out.append(r['code'])
 if len(out)!=len(set(out)):raise ValueError(f'duplicate current {exchange} codes')
 return sorted(out)

def in_window(ex,frozen,nxt):
 if not ex:return False
 d=date.fromisoformat(ex);return frozen<d<=nxt

def write(out,name,rows,manifest):
 out.mkdir(parents=True,exist_ok=True);p=out/name;rows.sort(key=lambda r:(r['ex_date'],r['exchange'],r['code'],r['action_component']))
 with gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9) as f:
  w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
 manifest['data_file']=p.name;manifest['data_sha256']=g5.sha(p.read_bytes());manifest['rows']=len(rows)
 (out/name.replace('.csv.gz','.manifest.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'file':name,'rows':len(rows),'requests':len(manifest['requests']),'errors':len(manifest['errors'])},ensure_ascii=False))

def build_sse(out):
 frozen,current,nxt=bounds(); universe=set(codes('SSE')); s=requests.Session();rows=[];m={'gate':'FORWARD_CORPORATE_ACTION_SSE','frozen_coverage_end':frozen.isoformat(),'current_session':current.isoformat(),'next_session':nxt.isoformat(),'current_identities':len(universe),'requests':[],'errors':[]}
 specs=[('DIVIDEND','COMMON_SSE_SJ_GPSJ_FHSG_SSGSFHQK_L',{'CONDITION_AG':'1','A_REG_DATE':str(current.year),'A_STOCK_CODE':''}),('BONUS','COMMON_SSE_SJ_GPSJ_FHSG_SG_L',{'SEARCH_YEAR':str(current.year),'COMPANY_CODE':''}),('RIGHTS','COMMON_SSE_SJ_GPSJ_MJZJ_PG_ZBAKCB_L',{'SEARCH_YEAR':str(current.year),'LIST_BOARD':'1'})]
 for component,sql_id,extra in specs:
  try:
   raw,url,src=g5.sse_get(s,sql_id,extra);digest=g5.sha(raw);m['requests'].append({'component':component,'sql_id':sql_id,'url':url,'rows':len(src),'sha256':digest})
   for x in src:
    if component=='DIVIDEND':
     code=g5.clean(x.get('A_STOCK_CODE'));ex=g5.norm_date(x.get('A_DIV_DATE'));record=g5.norm_date(x.get('A_REG_DATE'));vals={'cash_per_share':str(g5.num(x.get('A_BEFR_TAX_DIV'))),'bonus_per_share':'0','transfer_per_share':'0','rights_per_share':'0','rights_price':'0','rights_listing_date':''}
    elif component=='BONUS':
     code=g5.clean(x.get('A_STOCK_CODE'));ex=g5.norm_date(x.get('A_DERIGHTS_DATE'));record=g5.norm_date(x.get('A_REG_DATE'));vals={'cash_per_share':'0','bonus_per_share':str(g5.num(x.get('BONUS_RATIO'))/Decimal(10)),'transfer_per_share':str(g5.num(x.get('CONVERT_RATIO'))/Decimal(10)),'rights_per_share':'0','rights_price':'0','rights_listing_date':''}
    else:
     code=g5.clean(x.get('COMPANY_CODE'));ex=g5.norm_date(x.get('DERIGHTS_DATE'));record=g5.norm_date(x.get('REG_DATE'));vals={'cash_per_share':'0','bonus_per_share':'0','transfer_per_share':'0','rights_per_share':str(g5.num(x.get('RIGHTS_RATIO'))/Decimal(10)),'rights_price':str(g5.num(x.get('RIGHTS_PRICE'))),'rights_listing_date':g5.norm_date(x.get('RIGHTS_LIST_DATE'))}
    if code not in universe or not in_window(ex,frozen,nxt):continue
    if component=='DIVIDEND' and g5.num(vals['cash_per_share'])<=0:continue
    if component=='BONUS' and g5.num(vals['bonus_per_share'])<=0 and g5.num(vals['transfer_per_share'])<=0:continue
    if component=='RIGHTS' and g5.num(vals['rights_per_share'])<=0:continue
    rows.append({'exchange':'SSE','code':code,'ex_date':ex,'record_date':record,'announcement_date':'','action_component':component,**vals,'source_system':'SSE','source_id':sql_id,'source_url':url,'source_sha256':digest,'source_payload':json.dumps(x,ensure_ascii=False,sort_keys=True)})
  except Exception as exc:m['errors'].append({'component':component,'error':repr(exc)})
 if m['errors']:raise RuntimeError(json.dumps(m['errors'],ensure_ascii=False))
 write(out,'forward_sse_actions.csv.gz',rows,m)

def build_szse(shard,shards,out):
 frozen,current,nxt=bounds(); allcodes=codes('SZSE'); selected=[c for i,c in enumerate(allcodes) if i%shards==shard];js=g5.init_cninfo();s=requests.Session();rows=[];m={'gate':'FORWARD_CORPORATE_ACTION_SZSE_SHARD','shard':shard,'shards':shards,'frozen_coverage_end':frozen.isoformat(),'current_session':current.isoformat(),'next_session':nxt.isoformat(),'selected_identities':len(selected),'requests':[],'errors':[]}
 for i,code in enumerate(selected,1):
  try:
   raw,url,obj=g5.cn_post(s,js,'https://webapi.cninfo.com.cn/api/sysapi/p_sysapi1139',{'scode':code});digest=g5.sha(raw);recs=obj.get('records') or [];m['requests'].append({'code':code,'component':'DIVIDEND','url':url,'rows':len(recs),'sha256':digest})
   for x in recs:
    if not isinstance(x,dict):continue
    ex=g5.norm_date(x.get('F020D'));record=g5.norm_date(x.get('F018D'));ann=g5.norm_date(x.get('F006D'))
    if not in_window(ex,frozen,nxt):continue
    cash=g5.num(x.get('F012N'))/Decimal(10);bonus=g5.num(x.get('F010N'))/Decimal(10);transfer=g5.num(x.get('F011N'))/Decimal(10)
    if cash<=0 and bonus<=0 and transfer<=0:continue
    rows.append({'exchange':'SZSE','code':code,'ex_date':ex,'record_date':record,'announcement_date':ann,'action_component':'DIVIDEND_BONUS_TRANSFER','cash_per_share':str(cash),'bonus_per_share':str(bonus),'transfer_per_share':str(transfer),'rights_per_share':'0','rights_price':'0','rights_listing_date':'','source_system':'CNINFO','source_id':'p_sysapi1139','source_url':url,'source_sha256':digest,'source_payload':json.dumps(x,ensure_ascii=False,sort_keys=True)})
  except Exception as exc:m['errors'].append({'code':code,'component':'DIVIDEND','error':repr(exc)})
  try:
   raw,url,obj=g5.cn_post(s,js,'https://webapi.cninfo.com.cn/api/stock/p_stock2232',{'scode':code,'sdate':(frozen+timedelta(days=1)).isoformat(),'edate':nxt.isoformat()});digest=g5.sha(raw);recs=obj.get('records') or [];m['requests'].append({'code':code,'component':'RIGHTS','url':url,'rows':len(recs),'sha256':digest})
   for arr in recs:
    if isinstance(arr,dict):x=arr
    elif isinstance(arr,list) and len(arr)==len(g5.CNINFO_ALLOT_COLS):x=dict(zip(g5.CNINFO_ALLOT_COLS,arr))
    else:continue
    ex=g5.norm_date(x.get('除权基准日'));record=g5.norm_date(x.get('股权登记日'));ann=g5.norm_date(x.get('公告日期'))
    if not in_window(ex,frozen,nxt):continue
    rr=g5.num(x.get('配股比例'))/Decimal(10);rp=g5.num(x.get('配股价格'))
    if rr<=0:continue
    rows.append({'exchange':'SZSE','code':code,'ex_date':ex,'record_date':record,'announcement_date':ann,'action_component':'RIGHTS','cash_per_share':'0','bonus_per_share':'0','transfer_per_share':'0','rights_per_share':str(rr),'rights_price':str(rp),'rights_listing_date':g5.norm_date(x.get('配股上市日')),'source_system':'CNINFO','source_id':'p_stock2232','source_url':url,'source_sha256':digest,'source_payload':json.dumps(x,ensure_ascii=False,sort_keys=True,default=str)})
  except Exception as exc:m['errors'].append({'code':code,'component':'RIGHTS','error':repr(exc)})
  if i%40==0:print(f'SZSE forward actions shard {shard}/{shards} {i}/{len(selected)}',flush=True)
  time.sleep(.02)
 if m['errors']:raise RuntimeError(json.dumps(m['errors'][:30],ensure_ascii=False)+f' count={len(m["errors"])}')
 write(out,f'forward_szse_actions_shard{shard:02d}.csv.gz',rows,m)

def main():
 ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='cmd',required=True);a=sub.add_parser('sse');a.add_argument('--out',required=True);b=sub.add_parser('szse-shard');b.add_argument('--shard',type=int,required=True);b.add_argument('--shards',type=int,default=8);b.add_argument('--out',required=True);x=ap.parse_args()
 if x.cmd=='sse':build_sse(Path(x.out))
 else:build_szse(x.shard,x.shards,Path(x.out))
 return 0
if __name__=='__main__':raise SystemExit(main())
