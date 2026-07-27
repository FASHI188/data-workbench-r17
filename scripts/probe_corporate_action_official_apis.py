#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re,requests
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
report={'pages':{},'assets':{},'hits':[],'scripts':[],'contexts':[]}
patterns=[r'sqlId[^\n]{0,500}',r'query\.sse\.com\.cn[^\"\'\s<]{0,800}',r'COMMON_SSE_[A-Za-z0-9_]+',r'ShowReport[^\"\'\s<]{0,800}',r'CATALOGID[^\n]{0,500}',r'api/report/[^\"\'\s<]{0,800}',r'commonQuery\.do[^\n]{0,600}']
assets=[]
for u in pages:
 try:
  r=S.get(u,timeout=45);r.raise_for_status();t=r.text
  report['pages'][u]={'status':r.status_code,'bytes':len(r.content),'final_url':r.url}
  safe=re.sub(r'[^A-Za-z0-9]+','_',urlparse(u).path).strip('_') or 'index'
  (OUT/f'page_{safe}.html').write_text(t,encoding='utf-8')
  for needle in ('query.sse.com.cn','sqlId','COMMON_SSE_','ShowReport','CATALOGID'):
   pos=0
   while True:
    i=t.find(needle,pos)
    if i<0:break
    report['contexts'].append({'source':u,'needle':needle,'context':t[max(0,i-1000):min(len(t),i+1800)]})
    pos=i+len(needle)
  for p in patterns:
   for m in re.findall(p,t,re.I):report['hits'].append({'source':u,'hit':m[:1200]})
  for src in re.findall(r'<script[^>]+src\s*=\s*["\']([^"\']+)',t,re.I):
   au=urljoin(r.url,src);report['scripts'].append({'page':u,'src':au});assets.append(au)
 except Exception as e:report['pages'][u]={'error':repr(e)}
seen=set()
for au in assets[:160]:
 if au in seen:continue
 seen.add(au)
 try:
  r=S.get(au,timeout=45);r.raise_for_status();t=r.text
  relevant=[]
  for p in patterns:relevant.extend(re.findall(p,t,re.I))
  if any(k in t for k in ('dividend','allotment','bonus','分红','配股','送股','COMMON_SSE_','sqlId')):
   name=hashlib.sha256(au.encode()).hexdigest()[:12];(OUT/f'asset_{name}.js').write_text(t,encoding='utf-8')
  if relevant:
   report['assets'][au]={'bytes':len(r.content),'hits':[x[:1500] for x in relevant[:200]]}
   for x in relevant:report['hits'].append({'source':au,'hit':x[:1500]})
 except Exception as e:report['assets'][au]={'error':repr(e)}
uniq=[];keys=set()
for x in report['hits']:
 k=(x['source'],x['hit'])
 if k not in keys:keys.add(k);uniq.append(x)
report['hits']=uniq
(OUT/'official_api_probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'pages':report['pages'],'scripts':report['scripts'][:100],'assets_with_hits':len([x for x in report['assets'].values() if x.get('hits')]),'hit_count':len(report['hits']),'hits':report['hits'][:200],'contexts':report['contexts'][:50]},ensure_ascii=False,indent=2))
