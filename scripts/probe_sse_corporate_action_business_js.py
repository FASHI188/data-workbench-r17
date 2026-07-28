#!/usr/bin/env python3
import json,re,requests
from pathlib import Path
OUT=Path('data/corp_action_business_js');OUT.mkdir(parents=True,exist_ok=True)
urls=[
 'https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_stockData_2021.js',
 'https://www.sse.com.cn/xhtml/home/2020public/querySearch/search_stockData.js',
 'https://www.sse.com.cn/xhtml/home/2020public/querySearch/search_stockData_2020.js',
]
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://www.sse.com.cn/market/stockdata/dividends/dividend/'})
report={}
for u in urls:
 try:
  r=s.get(u,timeout=45);r.raise_for_status();t=r.text
  name=u.rsplit('/',1)[-1];(OUT/name).write_text(t,encoding='utf-8')
  lines=t.splitlines();hits=[]
  for i,line in enumerate(lines):
   if any(k.lower() in line.lower() for k in ('dividend','bonus','allotment','配股','分红','送股','sqlid','common_sse_')):
    hits.append({'line':i+1,'context':'\n'.join(lines[max(0,i-5):min(len(lines),i+10)])})
  report[u]={'status':r.status_code,'bytes':len(r.content),'hits':hits[:300]}
 except Exception as e:report[u]={'error':repr(e)}
(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
