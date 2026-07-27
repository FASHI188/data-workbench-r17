#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys, requests
from pathlib import Path

OUT=Path('data/g4_g5_probe'); OUT.mkdir(parents=True,exist_ok=True)
report={}

# Baostock historical point-in-time fields.
import baostock as bs
lg=bs.login(); report['baostock_login']={'code':lg.error_code,'msg':lg.error_msg}
if lg.error_code!='0': raise SystemExit(2)

def qhist(code,start,end,adjust='3'):
    fields='date,code,open,high,low,close,preclose,volume,amount,adjustflag,tradestatus,pctChg,isST'
    rs=bs.query_history_k_data_plus(code,fields,start_date=start,end_date=end,frequency='d',adjustflag=adjust)
    rows=[]
    while rs.error_code=='0' and rs.next(): rows.append(dict(zip(rs.fields,rs.get_row_data())))
    if rs.error_code!='0': raise RuntimeError((code,rs.error_code,rs.error_msg))
    return rows

cases={
 'current_sh600000':('sh.600000','2024-05-20','2024-06-20'),
 'delisted_sh601268':('sh.601268','2015-01-01','2015-12-31'),
 'delisted_sz000024':('sz.000024','2015-01-01','2015-12-31'),
 'risk_warning_candidate_sh600145':('sh.600145','2015-01-01','2015-12-31'),
}
for k,args in cases.items():
    rows=qhist(*args)
    report[k]={'rows':len(rows),'first':rows[:2],'last':rows[-2:],
               'isST_values':sorted({r['isST'] for r in rows}),
               'tradestatus_values':sorted({r['tradestatus'] for r in rows})}

# Adjustment-factor observability on a liquid long-history stock.
adj={}
for flag in ('1','2','3'):
    rows=qhist('sh.600000','2023-05-01','2023-08-31',flag)
    adj[flag]={'rows':len(rows),'sample':rows[:2]+rows[-2:]}
report['adjustment_variants']=adj
report['baostock_functions']=[x for x in dir(bs) if any(t in x.lower() for t in ('dividend','adjust','profit'))]
try:
    rs=bs.query_dividend_data(code='sh.600000',year='2023',yearType='report')
    d=[]
    while rs.error_code=='0' and rs.next(): d.append(dict(zip(rs.fields,rs.get_row_data())))
    report['baostock_dividend_600000_2023']={'code':rs.error_code,'msg':rs.error_msg,'rows':d[:20]}
except Exception as e:
    report['baostock_dividend_600000_2023']={'error':repr(e)}
bs.logout()

# CNINFO official announcement full-text search probe.
s=requests.Session(); s.headers.update({
 'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36',
 'Referer':'https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search&lastPage=index',
 'Origin':'https://www.cninfo.com.cn','X-Requested-With':'XMLHttpRequest',
 'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'})
try: s.get('https://www.cninfo.com.cn/new/index',timeout=30)
except Exception: pass
url='https://www.cninfo.com.cn/new/hisAnnouncement/query'
def cnq(searchkey,seDate):
    data={'pageNum':'1','pageSize':'30','column':'szse','tabName':'fulltext','plate':'','stock':'','searchkey':searchkey,'secid':'','category':'','trade':'','seDate':seDate,'sortName':'','sortType':'','isHLtitle':'true'}
    r=s.post(url,data=data,timeout=60); r.raise_for_status(); obj=r.json()
    anns=obj.get('announcements') or []
    return {'totalAnnouncement':obj.get('totalAnnouncement'),'totalpages':obj.get('totalpages'),'sample':[{k:a.get(k) for k in ('secCode','secName','announcementTitle','announcementTime','adjunctUrl')} for a in anns[:5]]}
for key in ('实施退市风险警示','实施其他风险警示','撤销退市风险警示','撤销其他风险警示','权益分派实施公告','配股实施公告'):
    try: report['cninfo_'+key]=cnq(key,'2024-01-01~2024-12-31')
    except Exception as e: report['cninfo_'+key]={'error':repr(e)}

(OUT/'probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
