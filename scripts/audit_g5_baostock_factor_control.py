#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,json,sys
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TINY=Decimal('0.000001');MISMATCH=Decimal('0.01');REBASE_GAP=Decimal('0.005');TINY_UNOBSERVED=Decimal('0.0005')
def D(v):
 try:return Decimal(str(v or '0'))
 except InvalidOperation:return Decimal('0')
def transitions():
 p=ROOT/'config/security_code_transitions.json';return json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
def remap_factor_identity(r):
 for t in transitions():
  if r['exchange']==t['exchange'] and r['code']==t['new_code'] and r['effective_date']<t['effective_date']:
   r['code']=t['old_code'];return True
 return False
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--factor-root',required=True);ap.add_argument('--chain',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();root=Path(a.factor_root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 factor_files=sorted(root.rglob('g5_events_shard*.csv.gz'));manifest_files=sorted(root.rglob('g5_manifest_shard*.json'));errors=[]
 if len(factor_files)!=16:errors.append(f'expected 16 BaoStock factor files, got {len(factor_files)}')
 if len(manifest_files)!=16:errors.append(f'expected 16 BaoStock factor manifests, got {len(manifest_files)}')
 qerrors=[];factor_security_count=0
 for p in manifest_files:
  m=json.loads(p.read_text(encoding='utf-8'));qerrors+=m.get('query_errors') or [];factor_security_count+=int(m.get('securities',0))
 if qerrors:errors.append(f'BaoStock control query errors: {qerrors[:20]} count={len(qerrors)}')
 official={}
 with gzip.open(a.chain,'rt',encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):official.setdefault((r['exchange'],r['code']),[]).append(r)
 for rs in official.values():rs.sort(key=lambda r:r['ex_date'])
 by={};identity_remaps=0
 for p in factor_files:
  with gzip.open(p,'rt',encoding='utf-8',newline='') as f:
   for r in csv.DictReader(f):
    if '2015-01-01'<=r['effective_date']<='2026-07-24':
     identity_remaps+=int(remap_factor_identity(r));by.setdefault((r['exchange'],r['code']),[]).append(r)
 changes={};rebases=[];factor_ranges={};factor_rows=0
 for k,rs in by.items():
  rs.sort(key=lambda r:r['effective_date']);factor_rows+=len(rs);factor_ranges[k]=(date.fromisoformat(rs[0]['effective_date']),date.fromisoformat(rs[-1]['effective_date'])) if rs else None;prev=None
  for r in rs:
   nf=D(r['fore_adjust_factor']);nb=D(r['back_adjust_factor'])
   if nf<=0 or nb<=0:continue
   if prev is None:prev=(nf,nb);continue
   pf,pb=prev;prev=(nf,nb);rf=nf/pf;rb=nb/pb;cf=abs(rf-1);cb=abs(rb-1);gap=abs(rf-rb)/max(abs(rf),abs(rb),Decimal('1e-18'))
   rec={'exchange':k[0],'code':k[1],'date':r['effective_date'],'fore_ratio':str(rf),'back_ratio':str(rb),'ratio_gap':str(gap),'observed_multiplier':str(rb)}
   if gap>REBASE_GAP or (cf>TINY and cb<=TINY):rebases.append(rec)
   if cb>TINY:changes.setdefault(k,[]).append(rec)
 matched=[];unobserved=[];mismatch=[];not_covered=[];tiny_unobserved=[];used_changes=set()
 for k,ors in official.items():
  rng=factor_ranges.get(k)
  for o in ors:
   od=date.fromisoformat(o['ex_date']);theory=D(o['back_adjust_multiplier']);impact=abs(theory-1)
   if rng is None or od<=rng[0] or od>rng[1]:not_covered.append({'exchange':k[0],'code':k[1],'official_ex_date':o['ex_date'],'action_type':o['action_type'],'reason':'outside comparable BaoStock back-factor range'});continue
   cand=[]
   for idx,c in enumerate(changes.get(k,[])):
    if (k,idx) in used_changes:continue
    dd=abs((date.fromisoformat(c['date'])-od).days)
    if dd<=10:cand.append((dd,abs(D(c['observed_multiplier'])-theory),idx,c))
   if not cand:
    rec={'exchange':k[0],'code':k[1],'official_ex_date':o['ex_date'],'action_type':o['action_type'],'official_back_multiplier':str(theory),'impact':str(impact),'reason':'no quantized BaoStock back-factor change within +/-10d'}
    if impact<=TINY_UNOBSERVED:tiny_unobserved.append(rec)
    else:unobserved.append(rec)
    continue
   cand.sort(key=lambda x:(x[0],x[1]));dd,_,idx,c=cand[0];used_changes.add((k,idx));obs=D(c['observed_multiplier']);rel=abs(obs-theory)/max(abs(theory),Decimal('1e-18'));rec={**c,'official_ex_date':o['ex_date'],'official_action_type':o['action_type'],'official_back_multiplier':str(theory),'date_distance_days':dd,'relative_error':str(rel)}
   if rel>MISMATCH:mismatch.append(rec)
   else:matched.append(rec)
 supplier_only=[]
 for k,cs in changes.items():
  for idx,c in enumerate(cs):
   if (k,idx) not in used_changes:supplier_only.append(c)
 if mismatch:errors.append(f'official/BaoStock back-factor ratio mismatches >1%: {mismatch[:20]} count={len(mismatch)}')
 report={'stage':'G5_BAOSTOCK_SECONDARY_BACK_FACTOR_CONTROL','pass':not errors,'control_role':'SECONDARY_NUMERIC_CONTRADICTION_CHECK_NOT_EVENT_AUTHORITY','factor_security_count':factor_security_count,'factor_rows_scanned':factor_rows,'code_time_factor_rows_remapped':identity_remaps,'official_actions_in_chain':sum(len(x) for x in official.values()),'official_actions_matched':len(matched),'official_actions_material_missing':len(unobserved),'official_actions_secondary_unobserved':len(unobserved),'official_actions_tiny_unobserved':len(tiny_unobserved),'official_actions_not_covered_by_factor_range':len(not_covered),'factor_ratio_mismatches':len(mismatch),'supplier_only_economic_factor_changes_logged':len(supplier_only),'methodology_rebases_logged':len(rebases),'sample_matches':matched[:50],'sample_material_missing':unobserved[:50],'sample_secondary_unobserved':unobserved[:50],'sample_supplier_only_changes':supplier_only[:50],'sample_methodology_rebases':rebases[:50],'audit_policy':'Use BaoStock back_adjust_factor ratio as the secondary observable because the project chain is a back-adjustment chain. Fore-adjust-factor rebases are logged but do not suppress a valid back-factor observation. Comparable back-factor contradictions above 1% fail closed. Absence of a quantized secondary factor change is logged as coverage/unobserved evidence and cannot overrule a primary official corporate-action record.','errors':errors}
 (out/'g5_baostock_control.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
