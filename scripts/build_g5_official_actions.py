#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,html,json,re,sys,time
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
START=date(2015,1,1); END=date(2026,7,24)
FIELDS=['exchange','code','ex_date','record_date','announcement_date','action_component','cash_per_share','bonus_per_share','transfer_per_share','rights_per_share','rights_price','rights_listing_date','source_system','source_id','source_url','source_sha256','source_payload']
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36'

def sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def clean(v):return html.unescape('' if v is None else str(v)).strip()
def num(v):
 s=clean(v).replace(',','')
 if not s or s in {'-','None','nan','NaN'}:return Decimal('0')
 try:return Decimal(s)
 except InvalidOperation:return Decimal('0')
def norm_date(v):
 s=clean(v)
 if not s or s in {'-','None','nan','NaT','1970-01-01'}:return ''
 s=s[:10].replace('/','-').replace('.','-')
 if re.fullmatch(r'\d{8}',s):s=f'{s[:4]}-{s[4:6]}-{s[6:]}'
 try:return date.fromisoformat(s).isoformat()
 except Exception:return ''
def lifecycle_map(exchange):
 out={}
 with (ROOT/'data/security_lifecycle/security_intervals.csv').open(encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):
   if r['exchange']!=exchange:continue
   a=date.fromisoformat(r['listed_from']);b=date.fromisoformat(r['listed_to_exclusive']) if r['listed_to_exclusive'] else None
   if a<=END and (b is None or b>START):out[r['code']]=(a,b)
 return out
def active(interval,dstr):
 if not dstr:return False
 d=date.fromisoformat(dstr);a,b=interval
 return START<=d<=END and a<=d and (b is None or d<b)
def write_rows(out,rows,manifest,name):
 out.mkdir(parents=True,exist_ok=True);p=out/name
 rows.sort(key=lambda r:(r['ex_date'],r['exchange'],r['code'],r['action_component']))
 with gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9) as f:
  w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
 manifest['data_file']=p.name;manifest['data_sha256']=sha(p.read_bytes());manifest['rows']=len(rows)
 (out/(name.replace('.csv.gz','.manifest.json'))).write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'file':p.name,'rows':len(rows),'requests':len(manifest.get('requests',[])),'errors':len(manifest.get('errors',[]))},ensure_ascii=False))
def parse_jsonp(raw):
 s=raw.decode('utf-8',errors='strict').strip();m=re.match(r'^[^(]+\((.*)\)\s*;?$',s,re.S)
 if m:s=m.group(1)
 obj=json.loads(s)
 if not isinstance(obj,dict):raise ValueError('SSE payload not object')
 return obj
def http_get(session,url,params,headers,attempts=5,timeout=45):
 last=None
 for i in range(attempts):
  try:
   r=session.get(url,params=params,headers=headers,timeout=timeout);r.raise_for_status()
   if not r.content:raise RuntimeError('empty response')
   return r.content,r.url
  except Exception as e:
   last=e
   if i+1<attempts:time.sleep(0.8*(2**i))
 raise last
def sse_get(session,sql_id,extra):
 params={'jsonCallBack':'cb_g5_123','sqlId':sql_id,'isPagination':'true','pageHelp.pageSize':'5000','pageHelp.pageNo':'1','pageHelp.beginPage':'1','pageHelp.cacheSize':'1','pageHelp.endPage':'1',**extra}
 url='https://query.sse.com.cn/sseQuery/commonQuery.do'
 raw,final=http_get(session,url,params,{'User-Agent':UA,'Referer':'https://www.sse.com.cn/','Accept':'*/*','X-Requested-With':'XMLHttpRequest'})
 obj=parse_jsonp(raw);rows=obj.get('result') or []
 if not isinstance(rows,list):raise ValueError(f'SSE {sql_id} result not list')
 return raw,final,rows
def build_sse(out):
 life=lifecycle_map('SSE');s=requests.Session();rows=[];manifest={'source':'SSE_OFFICIAL_COMMON_QUERY','coverage':[START.isoformat(),END.isoformat()],'expected_lifecycle_securities':len(life),'requests':[],'errors':[]}
 for y in range(2015,2027):
  specs=[('DIVIDEND','COMMON_SSE_SJ_GPSJ_FHSG_SSGSFHQK_L',{'CONDITION_AG':'1','A_REG_DATE':str(y),'A_STOCK_CODE':''}),('BONUS','COMMON_SSE_SJ_GPSJ_FHSG_SG_L',{'SEARCH_YEAR':str(y),'COMPANY_CODE':''}),('RIGHTS','COMMON_SSE_SJ_GPSJ_MJZJ_PG_ZBAKCB_L',{'SEARCH_YEAR':str(y),'LIST_BOARD':'1'})]
  for component,sql_id,extra in specs:
   try:
    raw,url,src=sse_get(s,sql_id,extra);digest=sha(raw);manifest['requests'].append({'year':y,'component':component,'sql_id':sql_id,'url':url,'rows':len(src),'sha256':digest})
    for x in src:
     if component=='DIVIDEND':
      code=clean(x.get('A_STOCK_CODE'));ex=norm_date(x.get('A_DIV_DATE'));record=norm_date(x.get('A_REG_DATE'));vals={'cash_per_share':str(num(x.get('A_BEFR_TAX_DIV'))),'bonus_per_share':'0','transfer_per_share':'0','rights_per_share':'0','rights_price':'0','rights_listing_date':''}
     elif component=='BONUS':
      code=clean(x.get('A_STOCK_CODE'));ex=norm_date(x.get('A_DERIGHTS_DATE'));record=norm_date(x.get('A_REG_DATE'));vals={'cash_per_share':'0','bonus_per_share':str(num(x.get('BONUS_RATIO'))/Decimal(10)),'transfer_per_share':str(num(x.get('CONVERT_RATIO'))/Decimal(10)),'rights_per_share':'0','rights_price':'0','rights_listing_date':''}
     else:
      code=clean(x.get('COMPANY_CODE'));ex=norm_date(x.get('DERIGHTS_DATE'));record=norm_date(x.get('REG_DATE'));vals={'cash_per_share':'0','bonus_per_share':'0','transfer_per_share':'0','rights_per_share':str(num(x.get('RIGHTS_RATIO'))/Decimal(10)),'rights_price':str(num(x.get('RIGHTS_PRICE'))),'rights_listing_date':norm_date(x.get('RIGHTS_LIST_DATE'))}
     if code not in life or not ex or not active(life[code],ex):continue
     if component=='DIVIDEND' and num(vals['cash_per_share'])<=0:continue
     if component=='BONUS' and num(vals['bonus_per_share'])<=0 and num(vals['transfer_per_share'])<=0:continue
     if component=='RIGHTS' and num(vals['rights_per_share'])<=0:continue
     rows.append({'exchange':'SSE','code':code,'ex_date':ex,'record_date':record,'announcement_date':'','action_component':component,**vals,'source_system':'SSE','source_id':sql_id,'source_url':url,'source_sha256':digest,'source_payload':json.dumps(x,ensure_ascii=False,sort_keys=True)})
   except Exception as e:manifest['errors'].append({'year':y,'component':component,'error':repr(e)})
 if manifest['errors']:raise RuntimeError(json.dumps(manifest['errors'],ensure_ascii=False))
 write_rows(out,rows,manifest,'g5_sse_official_actions.csv.gz')
def init_cninfo():
 from py_mini_racer import py_mini_racer
 from akshare.datasets import get_ths_js
 js=py_mini_racer.MiniRacer();js.eval(Path(get_ths_js('cninfo.js')).read_text(encoding='utf-8'));return js
CNINFO_ALLOT_COLS=['记录标识','证券简称','停牌起始日','上市公告日期','配股缴款起始日','可转配股数量','停牌截止日','实际配股数量','配股价格','配股比例','配股前总股本','每股配权转让费(元)','法人股实配数量','实际募资净额','大股东认购方式','其他配售简称','发行方式','配股失败，退还申购款日期','除权基准日','预计发行费用','配股发行结果公告日','证券代码','配股权证交易截止日','其他股份实配数量','国家股实配数量','委托单位','公众获转配数量','其他配售代码','配售对象','配股权证交易起始日','资金到账日','机构名称','股权登记日','实际募资总额','预计募集资金','大股东认购数量','公众股实配数量','转配股实配数量','承销费用','法人获转配数量','配股后流通股本','股票类别','公众配售简称','发行方式编码','承销方式','公告日期','配股上市日','配股缴款截止日','承销余额(股)','预计配股数量','配股后总股本','职工股实配数量','承销方式编码','发行费用总额','配股前流通股本','股票类别编码','公众配售代码']
def cn_headers(js):
 return {'Accept':'*/*','Accept-Enckey':js.call('getResCode1'),'Accept-Encoding':'gzip, deflate','Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8','Cache-Control':'no-cache','Content-Length':'0','Host':'webapi.cninfo.com.cn','Origin':'https://webapi.cninfo.com.cn','Pragma':'no-cache','Referer':'https://webapi.cninfo.com.cn/','User-Agent':UA,'X-Requested-With':'XMLHttpRequest'}
def cn_post(session,js,url,params):
 last=None
 for i in range(5):
  try:
   r=session.post(url,params=params,headers=cn_headers(js),timeout=45);r.raise_for_status();obj=r.json();return r.content,r.url,obj
  except Exception as e:
   last=e
   if i+1<5:time.sleep(0.7*(2**i))
 raise last
def build_szse(shard,shards,out):
 life=lifecycle_map('SZSE');codes=[c for i,c in enumerate(sorted(life)) if i%shards==shard];js=init_cninfo();s=requests.Session();rows=[];manifest={'source':'CNINFO_OFFICIAL_WEBAPI','shard':shard,'shards':shards,'coverage':[START.isoformat(),END.isoformat()],'expected_selected_securities':len(codes),'requests':[],'errors':[]}
 for i,code in enumerate(codes):
  try:
   raw,url,obj=cn_post(s,js,'https://webapi.cninfo.com.cn/api/sysapi/p_sysapi1139',{'scode':code});digest=sha(raw);records=obj.get('records') or [];manifest['requests'].append({'code':code,'component':'DIVIDEND','url':url,'rows':len(records),'sha256':digest})
   for x in records:
    if not isinstance(x,dict):continue
    ex=norm_date(x.get('F020D'));record=norm_date(x.get('F018D'));ann=norm_date(x.get('F006D'))
    if not ex or not active(life[code],ex):continue
    cash=num(x.get('F012N'))/Decimal(10);bonus=num(x.get('F010N'))/Decimal(10);transfer=num(x.get('F011N'))/Decimal(10)
    if cash<=0 and bonus<=0 and transfer<=0:continue
    rows.append({'exchange':'SZSE','code':code,'ex_date':ex,'record_date':record,'announcement_date':ann,'action_component':'DIVIDEND_BONUS_TRANSFER','cash_per_share':str(cash),'bonus_per_share':str(bonus),'transfer_per_share':str(transfer),'rights_per_share':'0','rights_price':'0','rights_listing_date':'','source_system':'CNINFO','source_id':'p_sysapi1139','source_url':url,'source_sha256':digest,'source_payload':json.dumps(x,ensure_ascii=False,sort_keys=True)})
  except Exception as e:manifest['errors'].append({'code':code,'component':'DIVIDEND','error':repr(e)})
  try:
   raw,url,obj=cn_post(s,js,'https://webapi.cninfo.com.cn/api/stock/p_stock2232',{'scode':code,'sdate':'2015-01-01','edate':'2026-07-24'});digest=sha(raw);records=obj.get('records') or [];manifest['requests'].append({'code':code,'component':'RIGHTS','url':url,'rows':len(records),'sha256':digest})
   for arr in records:
    if isinstance(arr,dict):x=arr
    elif isinstance(arr,list) and len(arr)==len(CNINFO_ALLOT_COLS):x=dict(zip(CNINFO_ALLOT_COLS,arr))
    else:continue
    ex=norm_date(x.get('除权基准日'));record=norm_date(x.get('股权登记日'));ann=norm_date(x.get('公告日期'))
    if not ex or not active(life[code],ex):continue
    rr=num(x.get('配股比例'))/Decimal(10);rp=num(x.get('配股价格'))
    if rr<=0:continue
    rows.append({'exchange':'SZSE','code':code,'ex_date':ex,'record_date':record,'announcement_date':ann,'action_component':'RIGHTS','cash_per_share':'0','bonus_per_share':'0','transfer_per_share':'0','rights_per_share':str(rr),'rights_price':str(rp),'rights_listing_date':norm_date(x.get('配股上市日')),'source_system':'CNINFO','source_id':'p_stock2232','source_url':url,'source_sha256':digest,'source_payload':json.dumps(x,ensure_ascii=False,sort_keys=True,default=str)})
  except Exception as e:manifest['errors'].append({'code':code,'component':'RIGHTS','error':repr(e)})
  if i and i%50==0:time.sleep(.15)
 if manifest['errors']:raise RuntimeError(json.dumps(manifest['errors'][:30],ensure_ascii=False)+f' count={len(manifest["errors"])}')
 write_rows(out,rows,manifest,f'g5_szse_official_actions_shard{shard:02d}.csv.gz')
def main():
 ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='cmd',required=True);a=sub.add_parser('sse');a.add_argument('--out',required=True);b=sub.add_parser('szse-shard');b.add_argument('--shard',type=int,required=True);b.add_argument('--shards',type=int,required=True);b.add_argument('--out',required=True);args=ap.parse_args()
 if args.cmd=='sse':build_sse(Path(args.out))
 else:build_szse(args.shard,args.shards,Path(args.out))
 return 0
if __name__=='__main__':sys.exit(main())
