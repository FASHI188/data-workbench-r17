#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path

FIELDS=['exchange','code','ex_date','record_date','announcement_date','action_component','cash_per_share','bonus_per_share','transfer_per_share','rights_per_share','rights_price','rights_listing_date','source_system','source_id','source_url','source_sha256','source_payload']

def sha(path:Path):return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path:Path):return json.loads(path.read_text(encoding='utf-8'))
def read_master(path:Path):
 out=set()
 with path.open(encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):out.add((r['exchange'],r['code']))
 return out

def dec(v):
 try:return Decimal(str(v or '0'))
 except InvalidOperation:raise ValueError(f'invalid decimal {v!r}')
def audit_file(path,universe,frozen,nxt,seen,errors):
 n=0;rows=[]
 with gzip.open(path,'rt',encoding='utf-8',newline='') as f:
  r=csv.DictReader(f)
  if r.fieldnames!=FIELDS:errors.append(f'bad schema {path.name}')
  for i,x in enumerate(r,2):
   n+=1
   key=(x['exchange'],x['code'])
   if key not in universe:errors.append(f'row outside current universe {path.name}:{i} {key}')
   try:d=date.fromisoformat(x['ex_date'])
   except Exception:errors.append(f'bad ex_date {path.name}:{i}');continue
   if not (frozen<d<=nxt):errors.append(f'row outside forward window {path.name}:{i} {d}')
   if len(x.get('source_sha256') or '')!=64:errors.append(f'missing source sha {path.name}:{i}')
   try:json.loads(x.get('source_payload') or '')
   except Exception:errors.append(f'invalid source payload {path.name}:{i}')
   vals=[dec(x[k]) for k in ('cash_per_share','bonus_per_share','transfer_per_share','rights_per_share','rights_price')]
   if any(v<0 for v in vals):errors.append(f'negative action value {path.name}:{i}')
   if not any(v>0 for v in vals[:4]):errors.append(f'zero action row {path.name}:{i}')
   dedupe=(x['exchange'],x['code'],x['ex_date'],x['action_component'],x['source_system'],x['source_id'],x['source_sha256'],x.get('source_payload',''))
   if dedupe in seen:errors.append(f'duplicate action evidence {path.name}:{i}')
   seen.add(dedupe);rows.append(x)
 return n,rows

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',default='build/freshness-phase3');ap.add_argument('--master',default='data/current_master/cn_main_a.csv');ap.add_argument('--shards',type=int,default=8);ap.add_argument('--out',default='build/freshness-phase3/forward_corporate_action_audit.json');a=ap.parse_args()
 root=Path(a.root);master=Path(a.master);universe=read_master(master);errors=[];seen=set();allrows=[]
 sse_m=root/'sse/forward_sse_actions.manifest.json';sse_d=root/'sse/forward_sse_actions.csv.gz'
 if not sse_m.exists() or not sse_d.exists():errors.append('missing SSE evidence');frozen=date(1970,1,1);nxt=date(1970,1,1)
 else:
  m=load(sse_m);frozen=date.fromisoformat(m['frozen_coverage_end']);nxt=date.fromisoformat(m['next_session'])
  sse_current=sum(1 for x in universe if x[0]=='SSE')
  if m.get('current_identities')!=sse_current:errors.append('SSE current identity count mismatch')
  if len(m.get('requests') or [])!=3:errors.append('SSE must have exactly 3 official component requests')
  if m.get('errors'):errors.append(f'SSE source errors: {m["errors"]}')
  if sha(sse_d)!=m.get('data_sha256'):errors.append('SSE data hash mismatch')
  n,rs=audit_file(sse_d,universe,frozen,nxt,seen,errors);allrows+=rs
  if n!=m.get('rows'):errors.append('SSE row count mismatch')
 sz_selected=0;sz_requests=0
 for shard in range(a.shards):
  mp=root/'szse'/f'forward_szse_actions_shard{shard:02d}.manifest.json';dp=root/'szse'/f'forward_szse_actions_shard{shard:02d}.csv.gz'
  if not mp.exists() or not dp.exists():errors.append(f'missing SZSE shard {shard}');continue
  m=load(mp)
  if m.get('shard')!=shard or m.get('shards')!=a.shards:errors.append(f'SZSE shard identity mismatch {shard}')
  if m.get('frozen_coverage_end')!=frozen.isoformat() or m.get('next_session')!=nxt.isoformat():errors.append(f'SZSE boundary mismatch {shard}')
  if m.get('errors'):errors.append(f'SZSE source errors shard {shard}: {m["errors"][:3]}')
  selected=int(m.get('selected_identities') or 0);reqs=m.get('requests') or [];sz_selected+=selected;sz_requests+=len(reqs)
  if len(reqs)!=selected*2:errors.append(f'SZSE request coverage mismatch shard {shard}: {len(reqs)} != {selected*2}')
  for req in reqs:
   if len(str(req.get('sha256') or ''))!=64:errors.append(f'SZSE missing request sha shard {shard}')
  if sha(dp)!=m.get('data_sha256'):errors.append(f'SZSE data hash mismatch {shard}')
  n,rs=audit_file(dp,universe,frozen,nxt,seen,errors);allrows+=rs
  if n!=m.get('rows'):errors.append(f'SZSE row count mismatch {shard}')
 sz_current=sum(1 for x in universe if x[0]=='SZSE')
 if sz_selected!=sz_current:errors.append(f'SZSE current identity coverage {sz_selected}!={sz_current}')
 allrows.sort(key=lambda r:(r['ex_date'],r['exchange'],r['code'],r['action_component']))
 merged=root/'forward_corporate_actions.csv.gz';merged.parent.mkdir(parents=True,exist_ok=True)
 with gzip.open(merged,'wt',encoding='utf-8',newline='',compresslevel=9) as f:
  w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(allrows)
 current_session=load(sse_m).get('current_session') if sse_m.exists() else None
 current_rows=sum(1 for r in allrows if r['ex_date']<=str(current_session or ''))
 next_rows=sum(1 for r in allrows if r['ex_date']==nxt.isoformat())
 report={'gate':'FORWARD_CORPORATE_ACTIONS','pass':not errors,'frozen_coverage_end':frozen.isoformat(),'current_session':current_session,'next_session':nxt.isoformat(),'current_universe':len(universe),'szse_identities_queried':sz_selected,'szse_requests':sz_requests,'action_rows':len(allrows),'actions_through_current_session':current_rows,'known_next_session_actions':next_rows,'merged_sha256':sha(merged),'errors':errors,'authoritative':False}
 out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':raise SystemExit(main())
