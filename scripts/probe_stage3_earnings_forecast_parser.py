#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from decimal import Decimal
from pathlib import Path
import fitz,requests
from stage3_earnings_forecast_parser import parse_parent_net_profit_forecast
ROOT=Path(__file__).resolve().parents[1];UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36'
SAMPLES=[
 {'code':'603636','url':'https://static.cninfo.com.cn/finalpage/2025-01-18/1222366739.PDF','economic_date':'2024-12-31','low':'-292000000','high':'-244000000'},
 {'code':'603799','url':'https://static.cninfo.com.cn/finalpage/2025-07-08/1224090893.PDF','economic_date':'2025-06-30','low':'2600000000','high':'2800000000'},
 {'code':'600675','url':'https://static.cninfo.com.cn/finalpage/2025-01-17/1222354087.PDF','economic_date':'2024-12-31','low':'-390000000','high':'-220000000'},
 {'code':'600187','url':'https://static.cninfo.com.cn/finalpage/2026-07-08/1225414043.PDF','economic_date':'2026-06-30','low':'6000000','high':'8000000'}]
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 out=ROOT/'data/stage3_source_probe';out.mkdir(parents=True,exist_ok=True);s=requests.Session();results=[];errors=[]
 for x in SAMPLES:
  try:
   r=s.get(x['url'],headers={'User-Agent':UA,'Referer':'https://www.cninfo.com.cn/'},timeout=60);r.raise_for_status();assert r.content.startswith(b'%PDF')
   d=fitz.open(stream=r.content,filetype='pdf');text='\n'.join(d[i].get_text('text') or '' for i in range(d.page_count));p=parse_parent_net_profit_forecast(text)
   ok=p.get('economic_date')==x['economic_date'] and Decimal(p.get('low_cny') or 'NaN')==Decimal(x['low']) and Decimal(p.get('high_cny') or 'NaN')==Decimal(x['high'])
   if not ok:errors.append(f"{x['code']} parsed={p} expected={x}")
   results.append({'code':x['code'],'url':x['url'],'sha256':sha(r.content),'bytes':len(r.content),'parsed':p,'expected':x,'pass':ok})
  except Exception as exc:errors.append(f"{x['code']}: {exc!r}");results.append({'code':x['code'],'url':x['url'],'error':repr(exc)})
 report={'gate':'S3G4A_OFFICIAL_EARNINGS_FORECAST_PARSER_PROBE','pass':not errors,'samples':results,'errors':errors}
 (out/'earnings_forecast_parser_probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':raise SystemExit(main())
