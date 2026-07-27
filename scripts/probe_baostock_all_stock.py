#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from pathlib import Path
import baostock as bs
OUT=Path('data/baostock_all_stock_probe');OUT.mkdir(parents=True,exist_ok=True)
report={}
lg=bs.login();report['login']={'code':lg.error_code,'msg':lg.error_msg}
if lg.error_code!='0':
 (OUT/'probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False));sys.exit(2)
try:
 for day in ['2015-01-05','2020-03-24','2026-07-24']:
  rs=bs.query_all_stock(day=day);rows=[]
  while rs.error_code=='0' and rs.next():rows.append(dict(zip(rs.fields,rs.get_row_data())))
  report[day]={'code':rs.error_code,'msg':rs.error_msg,'fields':rs.fields,'rows':len(rows),'sample':rows[:10],'st_count':sum(('ST' in (r.get('code_name') or '').upper()) for r in rows),'suspended_count':sum((r.get('tradeStatus')=='0') for r in rows)}
finally:bs.logout()
(OUT/'probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))
