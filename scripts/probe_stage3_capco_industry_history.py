#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import fitz
ROOT=Path(__file__).resolve().parents[1];BASE='https://www.capco.org.cn/xhgg/hyfl/hyfljg/';UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36'
def sha(b):return hashlib.sha256(b).hexdigest()
def get(s,u):
 r=s.get(u,headers={'User-Agent':UA,'Referer':'https://www.capco.org.cn/'},timeout=60);r.raise_for_status();return r
def main():
 out=ROOT/'data/stage3_source_probe';out.mkdir(parents=True,exist_ok=True);s=requests.Session();entries={};errors=[];index_evidence=[]
 for i in range(5):
  u=urljoin(BASE,'index.html' if i==0 else f'index_{i}.html')
  try:
   r=get(s,u);index_evidence.append({'url':u,'sha256':sha(r.content),'bytes':len(r.content)});soup=BeautifulSoup(r.text,'html.parser')
   for a in soup.find_all('a',href=True):
    t=' '.join(a.stripped_strings)
    if '上市公司行业分类结果' not in t:continue
    href=urljoin(u,a['href']);entries[href]={'title':t,'detail_url':href}
  except Exception as exc:errors.append(f'index {u}: {exc!r}')
 details=[]
 for u,e in sorted(entries.items()):
  try:
   r=get(s,u);soup=BeautifulSoup(r.text,'html.parser');text=' '.join(soup.stripped_strings);dm=re.search(r'(20\d{2})[-年](\d{1,2})[-月](\d{1,2})',text);pub=f'{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}' if dm else ''
   pdfs=[]
   for a in soup.find_all('a',href=True):
    h=urljoin(u,a['href']);tt=' '.join(a.stripped_strings)
    if '.pdf' in h.lower():pdfs.append({'title':tt,'url':h})
   preferred=[x for x in pdfs if '按股票代码' in x['title']] or [x for x in pdfs if '行业分类结果' in x['title']] or pdfs
   pe=[]
   for p in preferred[:2]:
    pr=get(s,p['url']);rec={'title':p['title'],'url':p['url'],'sha256':sha(pr.content),'bytes':len(pr.content),'pdf_magic':pr.content.startswith(b'%PDF')}
    if rec['pdf_magic']:
     d=fitz.open(stream=pr.content,filetype='pdf');txt='\n'.join(d[i].get_text('text') or '' for i in range(min(4,d.page_count)));rec['pages']=d.page_count;rec['sample_codes']=sorted(set(re.findall(r'(?<!\d)[036]\d{5}(?!\d)',txt)))[:30];rec['text_sample']=txt[:4000]
    pe.append(rec)
   details.append({**e,'publication_date':pub,'detail_sha256':sha(r.content),'attachments':pe})
  except Exception as exc:errors.append(f'detail {u}: {exc!r}')
 years=[]
 for d in details:
  m=re.search(r'(20\d{2})',d['title']);
  if m:years.append(int(m.group(1)))
 covered=[y for y in years if 2015<=y<=2025];usable=[d for d in details if d['publication_date'] and any(x.get('pdf_magic') for x in d['attachments'])]
 fatal=[]
 if not entries:fatal.append('no classification result entries discovered')
 if len(usable)<20:fatal.append(f'usable official result publications too few: {len(usable)}')
 if covered and (min(covered)>2015 or max(covered)<2025):fatal.append(f'historical coverage does not span 2015-2025: {min(covered)}-{max(covered)}')
 report={'gate':'S3G3A_CAPCO_INDUSTRY_HISTORY_SOURCE_PROBE','pass':not fatal,'index_evidence':index_evidence,'discovered_entries':len(entries),'usable_publications':len(usable),'covered_year_min':min(covered) if covered else None,'covered_year_max':max(covered) if covered else None,'details':details,'nonfatal_errors':errors,'errors':fatal}
 (out/'capco_industry_history_probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:report[k] for k in ('gate','pass','discovered_entries','usable_publications','covered_year_min','covered_year_max','errors')},ensure_ascii=False,indent=2));return 0 if not fatal else 2
if __name__=='__main__':raise SystemExit(main())
