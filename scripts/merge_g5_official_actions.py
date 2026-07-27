#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,sys
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];START=date(2015,1,1);END=date(2026,7,24)
OUT_FIELDS=['exchange','code','ex_date','record_date','announcement_date','action_type','cash_per_share','bonus_per_share','transfer_per_share','rights_per_share','rights_price','rights_listing_date','source_count','source_evidence']
def d(v):
 try:return Decimal(str(v or '0'))
 except InvalidOperation:return Decimal('0')
def lifecycle():
 out={}
 with (ROOT/'data/security_lifecycle/security_intervals.csv').open(encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):
   a=date.fromisoformat(r['listed_from']);b=date.fromisoformat(r['listed_to_exclusive']) if r['listed_to_exclusive'] else None
   if a<=END and (b is None or b>START):out[(r['exchange'],r['code'])]=(a,b)
 return out
def choose_unique(vals,label,key,errors):
 nz=sorted({d(v) for v in vals if d(v)!=0})
 if len(nz)>1:errors.append(f'{key} conflicting {label}: {nz}')
 return nz[-1] if nz else Decimal(0)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--out',required=True);args=ap.parse_args();root=Path(args.root);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
 life=lifecycle();errors=[];components=[];manifest_files=sorted(root.glob('*.manifest.json'))
 sse_ms=[p for p in manifest_files if p.name.startswith('g5_sse_')];sz_ms=[p for p in manifest_files if p.name.startswith('g5_szse_')]
 if len(sse_ms)!=1:errors.append(f'expected 1 SSE manifest, got {len(sse_ms)}')
 if len(sz_ms)!=4:errors.append(f'expected 4 SZSE manifests, got {len(sz_ms)}')
 reqs=0;source_hashes=[];selected_sz=0
 for mp in manifest_files:
  m=json.loads(mp.read_text(encoding='utf-8'));reqs+=len(m.get('requests') or []);selected_sz+=int(m.get('expected_selected_securities',0));
  if m.get('errors'):errors.append(f'{mp.name} source errors: {m["errors"][:10]}')
  df=root/m['data_file']
  if not df.exists():errors.append(f'missing {df.name}');continue
  actual=hashlib.sha256(df.read_bytes()).hexdigest();source_hashes.append((df.name,actual))
  if actual!=m.get('data_sha256'):errors.append(f'{df.name} hash mismatch')
  with gzip.open(df,'rt',encoding='utf-8',newline='') as f:components.extend(csv.DictReader(f))
 expected_sz=len([1 for (ex,c) in life if ex=='SZSE'])
 if selected_sz!=expected_sz:errors.append(f'SZSE selected universe {selected_sz} != lifecycle {expected_sz}')
 groups={}
 for r in components:
  k=(r['exchange'],r['code'],r['ex_date']);interval=life.get((r['exchange'],r['code']))
  if interval is None:errors.append(f'out-of-universe action {k}');continue
  day=date.fromisoformat(r['ex_date']);a,b=interval
  if not (START<=day<=END and a<=day and (b is None or day<b)):errors.append(f'action outside lifecycle {k}');continue
  groups.setdefault(k,[]).append(r)
 merged=[];type_counts={}
 for k,rs in sorted(groups.items()):
  cash=choose_unique([r['cash_per_share'] for r in rs],'cash',k,errors);bonus=choose_unique([r['bonus_per_share'] for r in rs],'bonus',k,errors);transfer=choose_unique([r['transfer_per_share'] for r in rs],'transfer',k,errors);rights=choose_unique([r['rights_per_share'] for r in rs],'rights',k,errors);rprice=choose_unique([r['rights_price'] for r in rs],'rights_price',k,errors)
  kinds=[]
  if cash>0:kinds.append('CASH_DIVIDEND')
  if bonus>0:kinds.append('BONUS_SHARE')
  if transfer>0:kinds.append('CAPITAL_TRANSFER')
  if rights>0:kinds.append('RIGHTS_ISSUE')
  if not kinds:errors.append(f'zero-economic action {k}');continue
  at='+'.join(kinds);type_counts[at]=type_counts.get(at,0)+1
  records=sorted({r['record_date'] for r in rs if r['record_date']});anns=sorted({r['announcement_date'] for r in rs if r['announcement_date']});listings=sorted({r['rights_listing_date'] for r in rs if r['rights_listing_date']})
  evidence=[{'component':r['action_component'],'source_system':r['source_system'],'source_id':r['source_id'],'source_url':r['source_url'],'source_sha256':r['source_sha256']} for r in rs]
  merged.append({'exchange':k[0],'code':k[1],'ex_date':k[2],'record_date':records[0] if records else '','announcement_date':anns[0] if anns else '','action_type':at,'cash_per_share':str(cash),'bonus_per_share':str(bonus),'transfer_per_share':str(transfer),'rights_per_share':str(rights),'rights_price':str(rprice),'rights_listing_date':listings[-1] if listings else '','source_count':len(evidence),'source_evidence':json.dumps(evidence,ensure_ascii=False,sort_keys=True)})
 p=out/'g5_official_actions.csv.gz'
 with gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9) as f:w=csv.DictWriter(f,fieldnames=OUT_FIELDS);w.writeheader();w.writerows(merged)
 fingerprint=hashlib.sha256(('\n'.join(f'{n}:{h}' for n,h in sorted(source_hashes))+'\n'+hashlib.sha256(p.read_bytes()).hexdigest()).encode()).hexdigest()
 report={'stage':'G5_OFFICIAL_ACTION_LEDGER','pass':not errors,'coverage_start':START.isoformat(),'coverage_end':END.isoformat(),'lifecycle_security_count':len(life),'component_rows':len(components),'official_action_dates':len(merged),'action_type_counts':type_counts,'source_requests':reqs,'dataset_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'dataset_fingerprint':fingerprint,'errors':errors}
 (out/'g5_official_action_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
