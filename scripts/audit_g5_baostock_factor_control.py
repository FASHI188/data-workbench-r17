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
 changes={};rebases=[];factor_ranges={};factor_rows=0
 for k,rs in by.items():
  rs.sort(key=lambda r:r['effective_date']);factor_rows+=len(rs);factor_ranges[k]=(date.fromisoformat(rs[0]['effective_date']),date.fromisoformat(rs[-1]['effective_date'])) if rs else None;prev=None
  for r in rs:
   nf=D(r['fore_adjust_factor']);nb=D(r['back_adjust_factor'])
   if nf<=0 or nb<=0:continue
   if prev is None:prev=(nf,nb);continue
   pf,pb=prev;prev=(nf,nb);rf=nf/pf;rb=nb/pb;cf=abs(rf-1);cb=abs(rb-1)
   if cf<=Decimal('0.000001') and cb<=Decimal('0.000001'):continue
   gap=abs(rf-rb)/max(abs(rf),abs(rb),Decimal('1e-18'))
   rec={'exchange':k[0],'code':k[1],'date':r['effective_date'],'fore_ratio':str(rf),'back_ratio':str(rb),'ratio_gap':str(gap),'observed_multiplier':str((rf+rb)/Decimal(2))}
   if cf<=Decimal('0.000001') or cb<=Decimal('0.000001') or gap>Decimal('0.005'):
    rebases.append(rec);continue
   changes.setdefault(k,[]).append(rec)
 matched=[];missing=[];mismatch=[];not_covered=[];tiny_unobserved=[];used_changes=set()
 for k,ors in official.items():
  rng=factor_ranges.get(k)
  for o in ors:
   od=date.fromisoformat(o['ex_date']);theory=D(o['back_adjust_multiplier']);impact=abs(theory-1)
   if rng is None or od<=rng[0] or od>rng[1]:
    not_covered.append({'exchange':k[0],'code':k[1],'official_ex_date':o['ex_date'],'action_type':o['action_type'],'reason':'outside comparable BaoStock factor-change range'});continue
   cand=[]
   for idx,c in enumerate(changes.get(k,[])):
    dd=abs((date.fromisoformat(c['date'])-od).days)
    if dd<=10:cand.append((dd,idx,c))
   if not cand:
    rec={'exchange':k[0],'code':k[1],'official_ex_date':o['ex_date'],'action_type':o['action_type'],'official_back_multiplier':str(theory)}
    if impact<=Decimal('0.0005'):tiny_unobserved.append(rec)
    else:missing.append(rec)
    continue
   cand.sort(key=lambda x:(x[0],abs(D(x[2]['observed_multiplier'])-theory)));dd,idx,c=cand[0];used_changes.add((k,idx));obs=D(c['observed_multiplier']);rel=abs(obs-theory)/max(abs(theory),Decimal('1e-18'))
   rec={**c,'official_ex_date':o['ex_date'],'official_action_type':o['action_type'],'official_back_multiplier':str(theory),'date_distance_days':dd,'relative_error':str(rel)}
   if rel>Decimal('0.01'):mismatch.append(rec)
   else:matched.append(rec)
 supplier_only=[]
 for k,cs in changes.items():
  for idx,c in enumerate(cs):
   if (k,idx) not in used_changes:supplier_only.append(c)
 # Official ledger is authoritative; independent factor evidence may be absent, but where both sources overlap materially they must agree.
 if mismatch:errors.append(f'official/BaoStock factor ratio mismatches >1%: {mismatch[:20]} count={len(mismatch)}')
 # Missing factor changes are hard errors only for materially nontrivial official events inside BaoStock's comparable range.
 if missing:errors.append(f'material official actions lack comparable BaoStock factor change: {missing[:30]} count={len(missing)}')
 report={'stage':'G5_BAOSTOCK_INDEPENDENT_CONTROL','pass':not errors,'factor_security_count':factor_security_count,'factor_rows_scanned':factor_rows,'official_actions_in_chain':sum(len(x) for x in official.values()),'official_actions_matched':len(matched),'official_actions_material_missing':len(missing),'official_actions_tiny_unobserved':len(tiny_unobserved),'official_actions_not_covered_by_factor_range':len(not_covered),'factor_ratio_mismatches':len(mismatch),'supplier_only_economic_factor_changes_logged':len(supplier_only),'methodology_rebases_logged':len(rebases),'sample_matches':matched[:50],'sample_material_missing':missing[:50],'sample_supplier_only_changes':supplier_only[:50],'sample_methodology_rebases':rebases[:50],'errors':errors}
 (out/'g5_baostock_control.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
