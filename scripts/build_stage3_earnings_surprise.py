#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import fitz
import requests

from stage3_earnings_forecast_parser import parse_parent_net_profit_forecast, compare_actual

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
FIELDS=[
 "exchange","effective_code","issuer_org_id","economic_date","actual_report_family",
 "actual_announcement_id","actual_available_at","actual_source_sha256","actual_parent_net_profit_cny",
 "forecast_announcement_id","forecast_available_at","forecast_source_url","forecast_source_sha256",
 "forecast_low_cny","forecast_high_cny","forecast_midpoint_cny","forecast_status","forecast_sign_inference",
 "surprise_cny","range_position","surprise_direction","expectation_is_strictly_prior","methodology_version"
]

def sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def readgz(p):
 with gzip.open(p,'rt',encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):yield r
def getpdf(s,u,attempts=6):
 last=None
 for i in range(attempts):
  try:
   r=s.get(u,headers={'User-Agent':UA,'Referer':'https://www.cninfo.com.cn/'},timeout=60);r.raise_for_status()
   if not r.content.startswith(b'%PDF'):raise ValueError(f'not PDF type={r.headers.get("Content-Type")}')
   return r.content
  except Exception as exc:
   last=exc
   if i+1<attempts:time.sleep(min(.6*2**i,8))
 raise RuntimeError(repr(last))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--announcements',required=True);ap.add_argument('--financial-values',required=True);ap.add_argument('--financial-documents',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True);errors=[]
 anns=[]
 for r in readgz(Path(a.announcements)):
  try:cats=json.loads(r['event_categories'])
  except Exception:cats=[]
  if 'EARNINGS_FORECAST' in cats and r.get('usable_in_stage2')=='1':anns.append(r)
 financial_docs={r['announcement_id']:r for r in readgz(Path(a.financial_documents))}
 actuals=[]
 for r in readgz(Path(a.financial_values)):
  if r['concept']!='NET_PROFIT_ATTRIBUTABLE_TO_PARENT':continue
  d=financial_docs.get(r['announcement_id'])
  if not d:errors.append(f"financial actual missing document {r['announcement_id']}");continue
  actuals.append({**r,'issuer_org_id':r['issuer_org_id'],'actual_doc':d})
 # Group forecast metadata by issuer; economic date is derived from original PDF, not title/category metadata.
 s=requests.Session();parsed_forecasts=[];non_numeric=[]
 for idx,r in enumerate(anns,1):
  try:
   raw=getpdf(s,r['source_url']);doc=fitz.open(stream=raw,filetype='pdf');text='\n'.join(doc[i].get_text('text') or '' for i in range(doc.page_count));p=parse_parent_net_profit_forecast(text)
   ev={**r,'source_sha256':sha(raw),'parser':p}
   if p.get('status') in ('FOUND','FOUND_POINT_ESTIMATE') and p.get('economic_date'):
    parsed_forecasts.append(ev)
   else:non_numeric.append({'announcement_id':r['announcement_id'],'code':r['effective_code'],'title':r['announcement_title'],'available_at':r['available_at'],'parser_status':p.get('status'),'source_sha256':sha(raw)})
  except Exception as exc:errors.append(f"forecast {r['announcement_id']}: {exc!r}")
  if idx%100==0:print(f'forecast PDFs {idx}/{len(anns)}',flush=True)
 by_period=defaultdict(list)
 for f in parsed_forecasts:by_period[(f['org_id'],f['parser']['economic_date'])].append(f)
 for fs in by_period.values():fs.sort(key=lambda x:(x['available_at'],x['announcement_id']))
 output=[];actual_without_prior=[]
 for r in actuals:
  key=(r['issuer_org_id'],r['economic_date']);fs=[f for f in by_period.get(key,[]) if f['available_at']<r['available_at']]
  if not fs:
   actual_without_prior.append([r['announcement_id'],r['issuer_org_id'],r['economic_date']]);continue
  f=fs[-1];cmp=compare_actual(f['parser'],r['normalized_cny_value']);d=r['actual_doc']
  output.append({
   'exchange':r['exchange'],'effective_code':r['effective_code'],'issuer_org_id':r['issuer_org_id'],'economic_date':r['economic_date'],'actual_report_family':r['report_family'],
   'actual_announcement_id':r['announcement_id'],'actual_available_at':r['available_at'],'actual_source_sha256':r['source_sha256'],'actual_parent_net_profit_cny':r['normalized_cny_value'],
   'forecast_announcement_id':f['announcement_id'],'forecast_available_at':f['available_at'],'forecast_source_url':f['source_url'],'forecast_source_sha256':f['source_sha256'],
   'forecast_low_cny':f['parser']['low_cny'],'forecast_high_cny':f['parser']['high_cny'],'forecast_midpoint_cny':f['parser']['midpoint_cny'],'forecast_status':f['parser']['status'],'forecast_sign_inference':f['parser'].get('sign_inference') or '',
   'surprise_cny':cmp['surprise_cny'],'range_position':cmp['range_position'] or '','surprise_direction':cmp['surprise_direction'],'expectation_is_strictly_prior':'1','methodology_version':'V3.3.4_OFFICIAL_GUIDANCE_VS_ACTUAL'
  })
 output.sort(key=lambda r:(r['actual_available_at'],r['exchange'],r['effective_code'],r['actual_announcement_id']))
 p=out/'stage3_earnings_surprise.csv.gz'
 with gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9) as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(output)
 report={'gate':'S3G4_OFFICIAL_EARNINGS_GUIDANCE_SURPRISE','pass':not errors,'earnings_forecast_announcements':len(anns),'numeric_forecast_versions':len(parsed_forecasts),'non_numeric_forecast_versions':len(non_numeric),'non_numeric_samples':non_numeric[:100],'financial_actual_observations':len(actuals),'surprise_observations':len(output),'actuals_without_prior_numeric_forecast':len(actual_without_prior),'actuals_without_prior_samples':actual_without_prior[:100],'surprise_ledger_sha256':sha(p.read_bytes()),'expectation_source':'OFFICIAL_COMPANY_EARNINGS_FORECAST_PDF','actual_source':'ORIGINAL_PERIODIC_FILING_PDF','analyst_consensus_used':False,'errors':errors}
 (out/'stage3_earnings_surprise_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':raise SystemExit(main())
