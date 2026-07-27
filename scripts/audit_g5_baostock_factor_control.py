#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,json,sys
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path

def D(v):
 try:return Decimal(str(v or '0'))
 except InvalidOperation:return Decimal('0')
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
 by={}
 for p in factor_files:
  with gzip.open(p,'rt',encoding='utf-8',newline='') as f:
   for r in csv.DictReader(f):
    if '2015-01-01'<=r['effective_date']<='2026-07-24':by.setdefault((r['exchange'],r['code']),[]).append(r)
 economic=[];rebases=[];matched=[];unresolved=[];ratio_mismatch=[]
 for k,rs in by.items():
  rs.sort(key=lambda r:r['effective_date']);prev=None
  for r in rs:
   nf=D(r['fore_adjust_factor']);nb=D(r['back_adjust_factor'])
   if nf<=0 or nb<=0:continue
   if prev is None:prev=(nf,nb);continue
   pf,pb=prev;prev=(nf,nb)
   rf=nf/pf;rb=nb/pb;cf=abs(rf-1);cb=abs(rb-1)
   if cf<=Decimal('0.000001') and cb<=Decimal('0.000001'):continue
   # A genuine corporate-action factor change should move fore/back factors by the same ratio.
   ratio_gap=abs(rf-rb)/max(abs(rf),abs(rb),Decimal('1e-18'))
   if cf<=Decimal('0.000001') or cb<=Decimal('0.000001') or ratio_gap>Decimal('0.005'):
    rebases.append({'exchange':k[0],'code':k[1],'date':r['effective_date'],'fore_ratio':str(rf),'back_ratio':str(rb),'ratio_gap':str(ratio_gap)});continue
   e={'exchange':k[0],'code':k[1],'date':r['effective_date'],'fore_ratio':str(rf),'back_ratio':str(rb),'ratio_gap':str(ratio_gap)};economic.append(e)
   cand=[];fd=date.fromisoformat(r['effective_date'])
   for o in official.get(k,[]):
    dd=abs((date.fromisoformat(o['ex_date'])-fd).days)
    if dd<=10:cand.append((dd,o))
   if not cand:unresolved.append(e);continue
   cand.sort(key=lambda x:(x[0],x[1]['ex_date']));o=cand[0][1];theory=D(o['back_adjust_multiplier']);observed=(rf+rb)/Decimal(2);rel=abs(observed-theory)/max(abs(theory),Decimal('1e-18'))
   rec={**e,'official_ex_date':o['ex_date'],'official_action_type':o['action_type'],'official_back_multiplier':str(theory),'observed_multiplier':str(observed),'relative_error':str(rel)}
   if rel>Decimal('0.01'):ratio_mismatch.append(rec)
   else:matched.append(rec)
 if unresolved:errors.append(f'unresolved economic factor changes: {unresolved[:30]} count={len(unresolved)}')
 if ratio_mismatch:errors.append(f'factor ratio mismatches >1%: {ratio_mismatch[:20]} count={len(ratio_mismatch)}')
 report={'stage':'G5_BAOSTOCK_INDEPENDENT_CONTROL','pass':not errors,'factor_security_count':factor_security_count,'factor_rows_scanned':sum(len(x) for x in by.values()),'economic_factor_changes':len(economic),'matched_economic_changes':len(matched),'methodology_rebases_ignored':len(rebases),'unresolved_economic_changes':len(unresolved),'ratio_mismatches':len(ratio_mismatch),'sample_methodology_rebases':rebases[:50],'sample_matches':matched[:50],'errors':errors}
 (out/'g5_baostock_control.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
