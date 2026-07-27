#!/usr/bin/env python3
from __future__ import annotations
import json,requests
from pathlib import Path
import build_g5_official_actions as b
OUT=Path('data/cninfo_raw_rights_probe');OUT.mkdir(parents=True,exist_ok=True)
js=b.init_cninfo();s=requests.Session()
raw,url,obj=b.cn_post(s,js,'https://webapi.cninfo.com.cn/api/stock/p_stock2232',{'scode':'600089','sdate':'2015-01-01','edate':'2026-07-24'})
rec=(obj.get('records') or [None])[0]
report={'url':url,'keys':list(obj.keys()),'record_type':type(rec).__name__,'record_len':len(rec) if hasattr(rec,'__len__') else None,'record':rec,'mapped':dict(zip(b.CNINFO_ALLOT_COLS,rec)) if isinstance(rec,list) and len(rec)==len(b.CNINFO_ALLOT_COLS) else None}
(OUT/'probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2,default=str))
