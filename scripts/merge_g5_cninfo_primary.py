#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,sys
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];START=date(2015,1,1);END=date(2026,7,24)
OUT_FIELDS=['exchange','code','ex_date','record_date','announcement_date','action_type','cash_per_share','bonus_per_share','transfer_per_share','rights_per_share','rights_price','rights_listing_date','source_count','source_evidence']
def D(v):
 try:return Decimal(str(v or '0'))
 except InvalidOperation:return Decimal('0')
def life():
 out={}
 with (ROOT/'data/security_lifecycle/security_intervals.csv').open(encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):
   a=date.fromisoformat(r['listed_from']);b=date.fromisoformat(r['listed_to_exclusive']) if r['listed_to_exclusive'] else None
   if a<=END and (b is None or b>START):out[(r['exchange'],r['code'])]=(a,b)
 return out
def unique(vals,label,key,errors):
 xs=sorted({D(v) for v in vals if D(v)!=0})
 if len(xs)>1:errors.append(f'{key} conflicting {label}: {xs}')
 return xs[-1] if xs else Decimal(0)
def read_gz(p):
 with gzip.open(p,'rt',encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def merge_components(rows,errors):
 groups={}
 for r in rows:groups.setdefault((r['exchange'],r['code'],r['ex_date']),[]).append(r)
 merged={}
 for k,rs in sorted(groups.items()):
  cash=unique([r['cash_per_share'] for r in rs],'cash',k,errors);bonus=unique([r['bonus_per_share'] for r in rs],'bonus',k,errors);transfer=unique([r['transfer_per_share'] for r in rs],'transfer',k,errors);rights=unique([r['rights_per_share'] for r in rs],'rights',k,errors);rp=unique([r['rights_price'] for r in rs],'rights_price',k,errors)
  kinds=[]
  if cash>0:kinds.append('CASH_DIVIDEND')
  if bonus>0:kinds.append('BONUS_SHARE')
  if transfer>0:kinds.append('CAPITAL_TRANSFER')
  if rights>0:kinds.append('RIGHTS_ISSUE')
  if not kinds:errors.append(f'zero-economic action {k}');continue
  records=sorted({r['record_date'] for r in rs if r['record_date']});anns=sorted({r['announcement_date'] for r in rs if r['announcement_date']});lists=sorted({r['rights_listing_date'] for r in rs if r['rights_listing_date']})
  evidence=[{'component':r['action_component'],'source_system':r['source_system'],'source_id':r['source_id'],'source_url':r['source_url'],'source_sha256':r['source_sha256']} for r in rs]
  merged[k]={'exchange':k[0],'code':k[1],'ex_date':k[2],'record_date':records[0] if records else '','announcement_date':anns[0] if anns else '','action_type':'+'.join(kinds),'cash_per_share':str(cash),'bonus_per_share':str(bonus),'transfer_per_share':str(transfer),'rights_per_share':str(rights),'rights_price':str(rp),'rights_listing_date':lists[-1] if lists else '','source_count':len(evidence),'source_evidence':json.dumps(evidence,ensure_ascii=False,sort_keys=True)}
 return merged
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();root=Path(a.root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True);errors=[];universe=life()
 cms=sorted(root.glob('g5_cninfo_actions_shard*.manifest.json'))
 if len(cms)!=8:errors.append(f'expected 8 CNINFO manifests, got {len(cms)}')
 primary=[];selected=0;source_hashes=[];requests=0
 for mp in cms:
  m=json.loads(mp.read_text(encoding='utf-8'));selected+=int(m.get('expected_selected_securities',0));requests+=len(m.get('requests') or [])
  if m.get('errors'):errors.append(f'{mp.name} source errors: {m["errors"][:10]}')
  df=root/m['data_file'];actual=hashlib.sha256(df.read_bytes()).hexdigest();source_hashes.append((df.name,actual))
  if actual!=m.get('data_sha256'):errors.append(f'{df.name} hash mismatch')
  primary+=read_gz(df)
 if selected!=len(universe):errors.append(f'CNINFO selected universe {selected} != lifecycle {len(universe)}')
 for r in primary:
  k=(r['exchange'],r['code']);interval=universe.get(k)
  if not interval:errors.append(f'out-of-universe CNINFO row {k}');continue
  d=date.fromisoformat(r['ex_date']);x,y=interval
  if not (START<=d<=END and x<=d and (y is None or d<y)):errors.append(f'CNINFO action outside lifecycle {(k,r["ex_date"])}')
 pm=merge_components(primary,errors)
 # Independent SSE native control where the current exchange endpoints retain history.
 control_files=sorted(root.glob('g5_sse_official_actions.csv.gz'));control_rows=[]
 if len(control_files)!=1:errors.append(f'expected one SSE native control file, got {len(control_files)}')
 else:control_rows=read_gz(control_files[0]);source_hashes.append((control_files[0].name,hashlib.sha256(control_files[0].read_bytes()).hexdigest()))
 checked=0;control_missing=[];control_conflicts=[]
 for r in control_rows:
  k=('SSE',r['code'],r['ex_date']);p=pm.get(k)
  if p is None:control_missing.append((k,r['action_component']));continue
  comp=r['action_component'];ok=True
  if comp=='DIVIDEND':ok=abs(D(p['cash_per_share'])-D(r['cash_per_share']))<=Decimal('0.000001')
  elif comp=='BONUS':ok=abs(D(p['bonus_per_share'])-D(r['bonus_per_share']))<=Decimal('0.000001') and abs(D(p['transfer_per_share'])-D(r['transfer_per_share']))<=Decimal('0.000001')
  elif comp=='RIGHTS':ok=abs(D(p['rights_per_share'])-D(r['rights_per_share']))<=Decimal('0.000001') and abs(D(p['rights_price'])-D(r['rights_price']))<=Decimal('0.0001')
  if ok:checked+=1
  else:control_conflicts.append({'key':k,'component':comp,'primary':p,'control':r})
 if control_missing:errors.append(f'SSE native controls missing in CNINFO: {control_missing[:20]} count={len(control_missing)}')
 if control_conflicts:errors.append(f'SSE native parameter conflicts: {control_conflicts[:10]} count={len(control_conflicts)}')
 rows=list(pm.values());rows.sort(key=lambda r:(r['ex_date'],r['exchange'],r['code']))
 p=out/'g5_official_actions.csv.gz'
 with gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9) as f:w=csv.DictWriter(f,fieldnames=OUT_FIELDS);w.writeheader();w.writerows(rows)
 types={}
 for r in rows:types[r['action_type']]=types.get(r['action_type'],0)+1
 digest=hashlib.sha256(p.read_bytes()).hexdigest();finger=hashlib.sha256(('\n'.join(f'{n}:{h}' for n,h in sorted(source_hashes))+'\n'+digest).encode()).hexdigest()
 report={'stage':'G5_OFFICIAL_ACTION_LEDGER','pass':not errors,'coverage_start':START.isoformat(),'coverage_end':END.isoformat(),'lifecycle_security_count':len(universe),'cninfo_component_rows':len(primary),'official_action_dates':len(rows),'action_type_counts':types,'cninfo_source_requests':requests,'sse_native_control_rows':len(control_rows),'sse_native_controls_matched':checked,'sse_native_control_missing':len(control_missing),'sse_native_control_conflicts':len(control_conflicts),'dataset_sha256':digest,'dataset_fingerprint':finger,'errors':errors}
 (out/'g5_official_action_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
