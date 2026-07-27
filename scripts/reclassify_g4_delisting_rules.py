#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,sys
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REFORM=date(2020,12,31)
RELISTING={('SSE','601975'):'2019-01-08',('SSE','601399'):'2020-06-08',('SZSE','001267'):'2021-11-17'}
OFFICIAL_NONTRADING_OVERRIDES={('SSE','600656','2016-05-12'):'SSE_OFFICIAL_DELISTING_SCHEDULE'}
FIELDS=['exchange','code','trade_date','tradable','risk_warning','preclose','pct_chg','limit_rule','limit_up_rate','limit_down_rate','evidence']

def sha(p:Path):return hashlib.sha256(p.read_bytes()).hexdigest()
def transitions():
 p=ROOT/'config/security_code_transitions.json'
 return json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
def transition_maps():
 ts=transitions();new={(t['exchange'],t['new_code']):t for t in ts};old={(t['exchange'],t['old_code']):t for t in ts};return new,old
def lifecycle_end():
 out={};_,old=transition_maps()
 with (ROOT/'data/security_lifecycle/security_intervals.csv').open(encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):
   k=(r['exchange'],r['code'])
   if r['listed_to_exclusive'] and k not in old:out[k]=date.fromisoformat(r['listed_to_exclusive'])
 return out
def detect_period(rows,listed_to):
 if listed_to is None:return None
 near=[r for r in rows if 0 < (listed_to-date.fromisoformat(r['trade_date'])).days <=120];trades=[i for i,r in enumerate(near) if r['tradable']=='1']
 if not trades:return None
 last=trades[-1]
 for i in range(max(0,last-55),last+1):
  if near[i]['tradable']!='1':continue
  prior=near[max(0,i-10):i]
  if len(prior)>=5 and sum(x['tradable']=='0' for x in prior)>=5:
   later=[x['trade_date'] for x in near[i:last+1] if x['tradable']=='1']
   if 1<=len(later)<=30:
    first=date.fromisoformat(later[0]);regime='OLD_30DAY_ALL_10PCT' if first<REFORM or len(later)>15 else 'NEW_15DAY_FIRST_NO_LIMIT'
    return {'first_date':later[0],'last_date':later[-1],'trade_dates':set(later),'trade_days':len(later),'regime':regime}
 return None
def remap_identity_rows(rows):
 new,_=transition_maps();remapped=[]
 for r in rows:
  t=new.get((r['exchange'],r['code']))
  if t and r['trade_date']<t['effective_date']:
   r['code']=t['old_code'];r['evidence']=r['evidence']+'+OFFICIAL_CODE_TIME_IDENTITY_REMAP';remapped.append({'exchange':t['exchange'],'old_code':t['old_code'],'new_code':t['new_code'],'date':r['trade_date']})
 return remapped
def split_source_manifest(source_manifest,rows):
 new,_=transition_maps();by={}
 for r in rows:by.setdefault((r['exchange'],r['code']),[]).append(r)
 out=[]
 for s in source_manifest:
  k=(s['exchange'],s['code']);t=new.get(k)
  if not t:out.append(s);continue
  for code in (t['old_code'],t['new_code']):
   rs=sorted(by.get((t['exchange'],code),[]),key=lambda x:x['trade_date'])
   if not rs:continue
   x=dict(s);x['code']=code;x['rows']=len(rs);x['first']=rs[0]['trade_date'];x['last']=rs[-1]['trade_date'];x['identity_source_query_code']=t['new_code'];x['identity_effective_date']=t['effective_date'];out.append(x)
 return out
def apply_nontrading_overrides(rows):
 changed=[]
 for r in rows:
  k=(r['exchange'],r['code'],r['trade_date']);reason=OFFICIAL_NONTRADING_OVERRIDES.get(k)
  if not reason:continue
  if r['tradable']!='0' or r['limit_rule']!='SUSPENDED':changed.append({'exchange':r['exchange'],'code':r['code'],'date':r['trade_date'],'old_tradable':r['tradable'],'old_rule':r['limit_rule']})
  r['tradable']='0';r['limit_rule']='SUSPENDED';r['limit_up_rate']='';r['limit_down_rate']='';r['evidence']=reason+'+OFFLINE_OVERRIDE'
 return changed
def counts_for(rows,source_manifest):
 return {'securities':len(source_manifest),'rows':len(rows),'tradable':sum(r['tradable']=='1' for r in rows),'suspended':sum(r['tradable']=='0' for r in rows),'risk_warning':sum(r['risk_warning']=='1' for r in rows)}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();src=Path(a.input);out=Path(a.out);out.mkdir(parents=True,exist_ok=True);ends=lifecycle_end();summary={'periods':[],'rewritten_rows':0,'relisting_overrides':[],'identity_remapped_rows':0,'identity_transitions':transitions(),'nontrading_overrides':[],'remaining_unclassified':[]}
 for sid in range(16):
  inp=src/f'g4_state_shard{sid:02d}.csv.gz';mp=src/f'g4_manifest_shard{sid:02d}.json'
  if not inp.exists() or not mp.exists():raise FileNotFoundError(f'missing shard {sid}')
  with gzip.open(inp,'rt',encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
  remapped=remap_identity_rows(rows);summary['identity_remapped_rows']+=len(remapped);summary['nontrading_overrides']+=apply_nontrading_overrides(rows)
  by={}
  for r in rows:by.setdefault((r['exchange'],r['code']),[]).append(r)
  periods=[];relist=[]
  for k,rs in by.items():
   rs.sort(key=lambda r:r['trade_date']);p=detect_period(rs,ends.get(k))
   if p:
    periods.append({'exchange':k[0],'code':k[1],'first_date':p['first_date'],'last_date':p['last_date'],'trade_days':p['trade_days'],'regime':p['regime']})
    for r in rs:
     if r['trade_date'] not in p['trade_dates']:continue
     if p['regime']=='NEW_15DAY_FIRST_NO_LIMIT' and r['trade_date']==p['first_date']:target=('DELISTING_15DAY_FIRST_DAY_NO_LIMIT','','','BAOSTOCK_POINT_IN_TIME+EXCHANGE_2020_DELISTING_REFORM+OFFLINE_FINAL_BLOCK_RECLASS')
     else:target=('DELISTING_CONSOLIDATION_10PCT','0.10','0.10','BAOSTOCK_POINT_IN_TIME+EXCHANGE_DELISTING_RULE+OFFLINE_FINAL_BLOCK_RECLASS')
     if (r['limit_rule'],r['limit_up_rate'],r['limit_down_rate'])!=target[:3]:summary['rewritten_rows']+=1
     r['limit_rule'],r['limit_up_rate'],r['limit_down_rate'],r['evidence']=target
   rd=RELISTING.get(k)
   if rd:
    matches=[r for r in rs if r['trade_date']==rd]
    if len(matches)!=1:raise ValueError(f'relisting override date missing/duplicate {k} {rd}: {len(matches)}')
    r=matches[0];target=('RELISTING_FIRST_DAY_NO_LIMIT','','','EXCHANGE_OFFICIAL_RELISTING_ANNOUNCEMENT+OFFLINE_OVERRIDE')
    if (r['limit_rule'],r['limit_up_rate'],r['limit_down_rate'])!=target[:3]:summary['rewritten_rows']+=1
    r['limit_rule'],r['limit_up_rate'],r['limit_down_rate'],r['evidence']=target;relist.append({'exchange':k[0],'code':k[1],'date':rd})
  rows.sort(key=lambda r:(r['trade_date'],r['exchange'],r['code']))
  remaining=[{'exchange':r['exchange'],'code':r['code'],'date':r['trade_date'],'pctChg':r['pct_chg']} for r in rows if r['limit_rule']=='UNCLASSIFIED_SPECIAL_NO_LIMIT']
  op=out/inp.name
  with gzip.open(op,'wt',encoding='utf-8',newline='',compresslevel=9) as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
  m=json.loads(mp.read_text(encoding='utf-8'));m['source_manifest']=split_source_manifest(m['source_manifest'],rows);m['counts']=counts_for(rows,m['source_manifest']);m['delisting_periods']=periods;m['delisting_first_days']=[{'exchange':p['exchange'],'code':p['code'],'date':p['first_date']} for p in periods];m['relisting_overrides']=relist;m['unclassified_special_days']=remaining;m['data_file']=op.name;m['data_sha256']=sha(op);m['offline_delisting_rule_reclassified']=True;m['offline_relisting_rule_reclassified']=True;m['offline_unclassified_manifest_rebuilt']=True;m['offline_code_time_identity_remapped']=True;m['offline_nontrading_overrides_applied']=True
  (out/mp.name).write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8');summary['periods']+=periods;summary['relisting_overrides']+=relist;summary['remaining_unclassified']+=remaining
 (out/'g4_reclassification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'period_count':len(summary['periods']),'relisting_overrides':len(summary['relisting_overrides']),'rewritten_rows':summary['rewritten_rows'],'identity_remapped_rows':summary['identity_remapped_rows'],'nontrading_overrides':len(summary['nontrading_overrides']),'remaining_unclassified':len(summary['remaining_unclassified']),'regimes':{x:sum(p['regime']==x for p in summary['periods']) for x in sorted({p['regime'] for p in summary['periods']})}},ensure_ascii=False));return 0
if __name__=='__main__':sys.exit(main())
