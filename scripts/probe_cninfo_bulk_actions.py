#!/usr/bin/env python3
from __future__ import annotations
import json,requests,traceback
from pathlib import Path
import build_g5_official_actions as b
OUT=Path('data/cninfo_bulk_probe');OUT.mkdir(parents=True,exist_ok=True)
js=b.init_cninfo();s=requests.Session();report={}
for name,url,params in [
 ('dividend_empty','https://webapi.cninfo.com.cn/api/sysapi/p_sysapi1139',{'scode':''}),
 ('dividend_none','https://webapi.cninfo.com.cn/api/sysapi/p_sysapi1139',{}),
 ('rights_empty','https://webapi.cninfo.com.cn/api/stock/p_stock2232',{'scode':'','sdate':'2015-01-01','edate':'2026-07-24'}),
 ('rights_none','https://webapi.cninfo.com.cn/api/stock/p_stock2232',{'sdate':'2015-01-01','edate':'2026-07-24'}),
]:
 try:
  raw,final,obj=b.cn_post(s,js,url,params);records=obj.get('records') or []
  report[name]={'bytes':len(raw),'url':final,'keys':list(obj)[:30],'record_count':len(records),'sample':records[:2]}
 except Exception as e:report[name]={'error':repr(e),'trace':traceback.format_exc()}
(OUT/'probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2,default=str))
