#!/usr/bin/env python3
from __future__ import annotations
import json,traceback
from pathlib import Path
import akshare as ak
OUT=Path('data/cninfo_action_probe');OUT.mkdir(parents=True,exist_ok=True)
report={}
for code in ['600055','600089','600123','600162','000001','000024']:
    item={}
    try:
        df=ak.stock_dividend_cninfo(symbol=code)
        item['dividend']={'columns':list(df.columns),'rows':df.astype(object).where(df.notna(),None).to_dict('records')}
    except Exception as e:item['dividend']={'error':repr(e),'trace':traceback.format_exc()}
    try:
        df=ak.stock_allotment_cninfo(symbol=code,start_date='20150101',end_date='20260724')
        item['allotment']={'columns':list(df.columns),'rows':df.astype(object).where(df.notna(),None).to_dict('records')}
    except Exception as e:item['allotment']={'error':repr(e),'trace':traceback.format_exc()}
    report[code]=item
(OUT/'probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2,default=str))
