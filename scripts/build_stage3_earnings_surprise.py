#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import fitz
import requests

from stage3_earnings_forecast_parser import parse_parent_net_profit_forecast, compare_actual

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
FIELDS=[
 "exchange","effective_code","issuer_org_id","economic_date","actual_report_family",
 "actual_announcement_id","actual_available_at","actual_source_url","actual_source_sha256","actual_parent_net_profit_cny",
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
   r=s.get(u,headers={'User-Agent':UA,'Referer':'https://www.cninfo.com.cn/'},timeout=90);r.raise_for_status()
   if not r.content.startswith(b'%PDF'):raise ValueError(f'not PDF type={r.headers.get("Content-Type")}')
   return r.content
  except Exception as exc:
   last=exc
   if i+1<attempts:time.sleep(min(.8*2**i,10))
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
  if not d:
   errors.append(f"financial actual missing document {r['announcement_id']}");continue
  if d.get('document_status')!='PASS' or not d.get('selected_source_sha256'):
   errors.append(f"financial actual document not clean PASS {r['announcement_id']}");continue
  if r.get('source_sha256')!=d.get('selected_source_sha256'):
   errors.append(f"financial actual/document SHA mismatch {r['announcement_id']}");continue
  actuals.append({**r,'actual_doc':d})

 # Economic date comes from the original forecast PDF itself, never from title metadata.
 s=requests.Session();parsed_forecasts=[];non_numeric=[];forecast_failures=[];status_counts=Counter()
 for idx,r in enumerate(anns,1):
  try:
   raw=getpdf(s,r['source_url']);doc=fitz.open(stream=raw,filetype='pdf');text='\n'.join(doc[i].get_text('text') or '' for i in range(doc.page_count));p=parse_parent_net_profit_forecast(text);digest=sha(raw)
   status=str(p.get('status') or 'NOT_FOUND');status_counts[status]+=1
   ev={**r,'source_sha256':digest,'parser':p}
   if status in ('FOUND','FOUND_POINT_ESTIMATE') and p.get('economic_date'):
    parsed_forecasts.append(ev)
   else:
    non_numeric.append({'announcement_id':r['announcement_id'],'code':r['effective_code'],'title':r['announcement_title'],'available_at':r['available_at'],'parser_status':status,'source_sha256':digest})
  except Exception as exc:
   forecast_failures.append([r.get('announcement_id'),r.get('source_url'),repr(exc)])
  if idx%100==0:print(f'forecast PDFs {idx}/{len(anns)}',flush=True)
 if forecast_failures:errors.append(f'forecast PDF failures {forecast_failures[:20]} count={len(forecast_failures)}')

 by_period=defaultdict(list)
 for f in parsed_forecasts:by_period[(f['org_id'],f['parser']['economic_date'])].append(f)
 for fs in by_period.values():fs.sort(key=lambda x:(x['available_at'],x['announcement_id']))

 output=[];actual_without_prior=[];historical_forecast_without_actual=[]
 # Append-only cross product of every numeric forecast revision and every later
 # formal actual revision for the same issuer/economic period. No earlier forecast
 # is overwritten by a later forecast correction, and no earlier actual is replaced
 # by a later restatement.
 actual_by_period=defaultdict(list)
 for r in actuals:actual_by_period[(r['issuer_org_id'],r['economic_date'])].append(r)
 for rs in actual_by_period.values():rs.sort(key=lambda x:(x['available_at'],x['announcement_id']))

 for key,fs in by_period.items():
  ars=actual_by_period.get(key,[])
  for f in fs:
   later=[r for r in ars if f['available_at']<r['available_at']]
   if not later:
    try:econ=date.fromisoformat(f['parser']['economic_date'])
    except Exception:econ=None
    if econ and econ.year<=2025:historical_forecast_without_actual.append([f['announcement_id'],key[0],key[1],f['available_at']])
    continue
   for r in later:
    cmp=compare_actual(f['parser'],r['normalized_cny_value']);d=r['actual_doc']
    output.append({
     'exchange':r['exchange'],'effective_code':r['effective_code'],'issuer_org_id':r['issuer_org_id'],'economic_date':r['economic_date'],'actual_report_family':r['report_family'],
     'actual_announcement_id':r['announcement_id'],'actual_available_at':r['available_at'],'actual_source_url':r['source_url'],'actual_source_sha256':r['source_sha256'],'actual_parent_net_profit_cny':r['normalized_cny_value'],
     'forecast_announcement_id':f['announcement_id'],'forecast_available_at':f['available_at'],'forecast_source_url':f['source_url'],'forecast_source_sha256':f['source_sha256'],
     'forecast_low_cny':f['parser']['low_cny'],'forecast_high_cny':f['parser']['high_cny'],'forecast_midpoint_cny':f['parser']['midpoint_cny'],'forecast_status':f['parser']['status'],'forecast_sign_inference':f['parser'].get('sign_inference') or '',
     'surprise_cny':cmp['surprise_cny'],'range_position':cmp['range_position'] or '','surprise_direction':cmp['surprise_direction'],'expectation_is_strictly_prior':'1','methodology_version':'V3.3.6_OFFICIAL_GUIDANCE_VS_ACTUAL_APPEND_ONLY'
    })

 for r in actuals:
  fs=[f for f in by_period.get((r['issuer_org_id'],r['economic_date']),[]) if f['available_at']<r['available_at']]
  if not fs:actual_without_prior.append([r['announcement_id'],r['issuer_org_id'],r['economic_date']])

 if historical_forecast_without_actual:
  errors.append(f'historical numeric forecasts without later formal actual {historical_forecast_without_actual[:20]} count={len(historical_forecast_without_actual)}')

 keys=set();dups=[]
 for r in output:
  k=(r['forecast_announcement_id'],r['actual_announcement_id'])
  if k in keys:dups.append(k)
  keys.add(k)
  if not r['forecast_source_sha256'] or not r['actual_source_sha256']:errors.append(f'missing provenance SHA {k}')
  if r['forecast_available_at']>=r['actual_available_at']:errors.append(f'non-causal availability {k}')
 if dups:errors.append(f'duplicate surprise revision keys {dups[:20]} count={len(dups)}')

 output.sort(key=lambda r:(r['actual_available_at'],r['exchange'],r['effective_code'],r['forecast_announcement_id'],r['actual_announcement_id']))
 p=out/'stage3_earnings_surprise.csv.gz'
 with gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9) as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(output)
 report={
  'gate':'S3G4_OFFICIAL_EARNINGS_GUIDANCE_SURPRISE','pass':not errors,
  'earnings_forecast_announcements':len(anns),'forecast_parse_status':dict(status_counts),'numeric_forecast_versions':len(parsed_forecasts),'non_numeric_forecast_versions':len(non_numeric),'non_numeric_samples':non_numeric[:100],
  'financial_actual_observations':len(actuals),'surprise_revision_observations':len(output),'actuals_without_prior_numeric_forecast':len(actual_without_prior),'actuals_without_prior_samples':actual_without_prior[:100],
  'historical_numeric_forecasts_without_later_actual':len(historical_forecast_without_actual),'forecast_pdf_failure_count':len(forecast_failures),
  'surprise_ledger_sha256':sha(p.read_bytes()),'expectation_source':'OFFICIAL_COMPANY_EARNINGS_FORECAST_PDF','actual_source':'S3G1J_ORIGINAL_PERIODIC_FILING_PDF',
  'analyst_consensus_used':False,'percentage_only_forecast_scalar_fabrication':False,'revision_policy':'append-only forecast x actual filing revision pairs; downstream PIT join selects latest available version','errors':errors
 }
 (out/'stage3_earnings_surprise_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':raise SystemExit(main())
