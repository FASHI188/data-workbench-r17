#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,time
from decimal import Decimal
from pathlib import Path
import requests
import build_g5_official_actions as b
from build_g5_cninfo_all import allotment_fields

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--shard',type=int,required=True);ap.add_argument('--shards',type=int,required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
 life=b.lifecycle_map('SZSE');codes=[c for i,c in enumerate(sorted(life)) if i%a.shards==a.shard]
 js=b.init_cninfo();s=requests.Session();rows=[];manifest={'source':'CNINFO_OFFICIAL_WEBAPI_SZSE_RIGHTS_SUPPLEMENT','shard':a.shard,'shards':a.shards,'coverage':[b.START.isoformat(),b.END.isoformat()],'expected_selected_securities':len(codes),'requests':[],'errors':[]}
 for i,code in enumerate(codes):
  try:
   raw,url,obj=b.cn_post(s,js,'https://webapi.cninfo.com.cn/api/stock/p_stock2232',{'scode':code,'sdate':'2015-01-01','edate':'2026-07-24'});digest=b.sha(raw);records=obj.get('records') or [];manifest['requests'].append({'exchange':'SZSE','code':code,'component':'RIGHTS','url':url,'rows':len(records),'sha256':digest})
   for arr in records:
    x=allotment_fields(arr)
    if not x:continue
    ex=b.norm_date(x.get('除权基准日'));record=b.norm_date(x.get('股权登记日'));ann=b.norm_date(x.get('公告日期'))
    if not ex or not b.active(life[code],ex):continue
    rr=b.num(x.get('配股比例'))/Decimal(10);rp=b.num(x.get('配股价格'))
    if rr<=0:continue
    rows.append({'exchange':'SZSE','code':code,'ex_date':ex,'record_date':record,'announcement_date':ann,'action_component':'RIGHTS','cash_per_share':'0','bonus_per_share':'0','transfer_per_share':'0','rights_per_share':str(rr),'rights_price':str(rp),'rights_listing_date':b.norm_date(x.get('配股上市日')),'source_system':'CNINFO','source_id':'p_stock2232','source_url':url,'source_sha256':digest,'source_payload':json.dumps(arr,ensure_ascii=False,sort_keys=True,default=str)})
  except Exception as e:manifest['errors'].append({'exchange':'SZSE','code':code,'component':'RIGHTS','error':repr(e)})
  if i and i%50==0:time.sleep(.12)
 if manifest['errors']:raise RuntimeError(json.dumps(manifest['errors'][:30],ensure_ascii=False)+f' count={len(manifest["errors"])}')
 b.write_rows(Path(a.out),rows,manifest,f'g5_cninfo_rights_supplement_shard{a.shard:02d}.csv.gz')
 return 0
if __name__=='__main__':raise SystemExit(main())
