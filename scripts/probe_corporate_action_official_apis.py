#!/usr/bin/env python3
from __future__ import annotations
import json,re,requests
from urllib.parse import urljoin,urlparse
from pathlib import Path
OUT=Path('data/corp_action_api_probe');OUT.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36','Accept-Language':'zh-CN,zh;q=0.9,en;q=0.7'})
pages=[
 'https://www.sse.com.cn/market/stockdata/dividends/dividend/',
 'https://www.sse.com.cn/market/stockdata/dividends/dividend/index_his.shtml',
 'https://www.sse.com.cn/market/stockdata/dividends/bonus/',
 'https://www.sse.com.cn/market/stockdata/dividends/bonus/index_his.shtml',
 'https://www.sse.com.cn/market/stockdata/raise/allotment/',
 'https://www.szse.cn/market/stock/dividend/index.html',
]
report={'pages':{},'assets':{},'hits':[]}
patterns=[r'sqlId[^\n]{0,240}',r'query\.sse\.com\.cn[^\"\'\s<]{0,400}',r'COMMON_SSE_[A-Za-z0-9_]+',r'ShowReport[^\"\'\s<]{0,400}',r'CATALOGID[^\n]{0,200}',r'api/report/[^\"\'\s<]{0,400}']
assets=[]
for u in pages:
 try:
  r=S.get(u,timeout=45);r.raise_for_status();t=r.text
  report['pages'][u]={'status':r.status_code,'bytes':len(r.content),'final_url':r.url}
  for p in patterns:
   for m in re.findall(p,t,re.I):report['hits'].append({'source':u,'hit':m[:700]})
  for src in re.findall(r'<script[^>]+src=["\']([^"\']+)',t,re.I):
   au=urljoin(r.url,src)
   if urlparse(au).netloc.endswith(('sse.com.cn','szse.cn')):assets.append(au)
 except Exception as e:report['pages'][u]={'error':repr(e)}
# Search page-specific assets plus a cap to avoid huge crawl.
seen=set()
for au in assets[:80]:
 if au in seen:continue
 seen.add(au)
 try:
  r=S.get(au,timeout=45);r.raise_for_status();t=r.text
  relevant=[]
  for p in patterns:
   relevant.extend(re.findall(p,t,re.I))
  if relevant:
   report['assets'][au]={'bytes':len(r.content),'hits':[x[:1000] for x in relevant[:100]]}
   for x in relevant:report['hits'].append({'source':au,'hit':x[:1000]})
 except Exception as e:
  report['assets'][au]={'error':repr(e)}
# De-duplicate preserving source/hit.
uniq=[];keys=set()
for x in report['hits']:
 k=(x['source'],x['hit'])
 if k not in keys:keys.add(k);uniq.append(x)
report['hits']=uniq
(OUT/'official_api_probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'pages':report['pages'],'assets_with_hits':len([x for x in report['assets'].values() if x.get('hits')]),'hit_count':len(report['hits']),'hits':report['hits'][:120]},ensure_ascii=False,indent=2))
