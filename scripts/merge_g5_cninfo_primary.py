#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,sys
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];START=date(2015,1,1);END=date(2026,7,24)
OUT_FIELDS=['exchange','code','ex_date','record_date','announcement_date','action_type','cash_per_share','bonus_per_share','transfer_per_share','rights_per_share','rights_price','rights_listing_date','source_count','source_evidence']
TOL=Decimal('0.00051')
def D(v):
 try:return Decimal(str(v or '0'))
 except InvalidOperation:return Decimal('0')
def transitions():
 p=ROOT/'config/security_code_transitions.json';return json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
def transition_new_map():return {(t['exchange'],t['new_code']):t for t in transitions()}
def life():
 out={}
 with (ROOT/'data/security_lifecycle/security_intervals.csv').open(encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):
   a=date.fromisoformat(r['listed_from']);b=date.fromisoformat(r['listed_to_exclusive']) if r['listed_to_exclusive'] else None
   if a<=END and (b is None or b>START):out[(r['exchange'],r['code'])]=(a,b)
 return out
def query_universe_keys(universe):
 old={(t['exchange'],t['old_code']) for t in transitions()};return set(universe)-old
def remap_code_time(rows):
 m=transition_new_map();changes=[]
 for r in rows:
  t=m.get((r['exchange'],r['code']))
  if t and r['ex_date']<t['effective_date']:
   changes.append({'exchange':r['exchange'],'source_query_code':r['code'],'effective_code':t['old_code'],'ex_date':r['ex_date']});r['code']=t['old_code']
 return changes
def read_gz(p):
 with gzip.open(p,'rt',encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def dedupe_rows(rows):
 out=[];seen=set()
 for r in rows:
  key=(r.get('source_system'),r.get('source_id'),r.get('source_sha256'),r.get('source_payload'))
  if key in seen:continue
  seen.add(key);out.append(r)
 return out
def sum_field(rows,field):return sum((D(r.get(field)) for r in rows),Decimal(0))
def one_nonzero(rows,field,label,key,errors):
 xs=sorted({D(r.get(field)) for r in rows if D(r.get(field))!=0})
 if len(xs)>1:errors.append(f'{key} conflicting {label}: {xs}')
 return xs[-1] if xs else Decimal(0)
def action_type(cash,bonus,transfer,rights):
 kinds=[]
 if D(cash)>0:kinds.append('CASH_DIVIDEND')
 if D(bonus)>0:kinds.append('BONUS_SHARE')
 if D(transfer)>0:kinds.append('CAPITAL_TRANSFER')
 if D(rights)>0:kinds.append('RIGHTS_ISSUE')
 return '+'.join(kinds)
def evidence_for(rows):
 return [{'component':r['action_component'],'source_system':r['source_system'],'source_id':r['source_id'],'source_url':r['source_url'],'source_sha256':r['source_sha256']} for r in rows]
def merge_evidence(existing,extra):
 try:items=json.loads(existing) if existing else []
 except Exception:items=[]
 seen={(x.get('component'),x.get('source_system'),x.get('source_id'),x.get('source_sha256')) for x in items}
 for x in extra:
  k=(x.get('component'),x.get('source_system'),x.get('source_id'),x.get('source_sha256'))
  if k not in seen:items.append(x);seen.add(k)
 return items
def merge_components(rows,errors):
 groups={}
 for r in rows:groups.setdefault((r['exchange'],r['code'],r['ex_date']),[]).append(r)
 merged={}
 for k,raw in sorted(groups.items()):
  rs=dedupe_rows(raw);div=[r for r in rs if r['action_component']=='DIVIDEND_BONUS_TRANSFER'];rights_rows=[r for r in rs if r['action_component']=='RIGHTS']
  cash=sum_field(div,'cash_per_share');bonus=sum_field(div,'bonus_per_share');transfer=sum_field(div,'transfer_per_share')
  rights=one_nonzero(rights_rows,'rights_per_share','rights_ratio',k,errors);rp=one_nonzero(rights_rows,'rights_price','rights_price',k,errors)
  kind=action_type(cash,bonus,transfer,rights)
  if not kind:errors.append(f'zero-economic action {k}');continue
  records=sorted({r['record_date'] for r in rs if r.get('record_date')});anns=sorted({r['announcement_date'] for r in rs if r.get('announcement_date')});lists=sorted({r['rights_listing_date'] for r in rs if r.get('rights_listing_date')})
  evidence=evidence_for(rs)
  merged[k]={'exchange':k[0],'code':k[1],'ex_date':k[2],'record_date':records[0] if records else '','announcement_date':anns[0] if anns else '','action_type':kind,'cash_per_share':str(cash),'bonus_per_share':str(bonus),'transfer_per_share':str(transfer),'rights_per_share':str(rights),'rights_price':str(rp),'rights_listing_date':lists[-1] if lists else '','source_count':len(evidence),'source_evidence':json.dumps(evidence,ensure_ascii=False,sort_keys=True)}
 return merged
def aggregate_sse_control(rows):
 groups={}
 for r in dedupe_rows(rows):groups.setdefault(('SSE',r['code'],r['ex_date']),[]).append(r)
 out={}
 for k,rs in groups.items():
  div=[r for r in rs if r['action_component']=='DIVIDEND'];bonus_rows=[r for r in rs if r['action_component']=='BONUS'];rights=[r for r in rs if r['action_component']=='RIGHTS']
  out[k]={'cash':sum_field(div,'cash_per_share'),'bonus':sum_field(bonus_rows,'bonus_per_share'),'transfer':sum_field(bonus_rows,'transfer_per_share'),'has_dividend_table':bool(div),'has_bonus_table':bool(bonus_rows),'dividend_rows':div,'bonus_rows':bonus_rows,'rights':one_nonzero(rights,'rights_per_share','SSE control rights_ratio',k,[]),'rights_price':one_nonzero(rights,'rights_price','SSE control rights_price',k,[]),'rights_rows':rights,'nonrights_rows':div+bonus_rows}
 return out
def blank_from_sse(k,rows):
 records=sorted({r.get('record_date','') for r in rows if r.get('record_date')})
 return {'exchange':k[0],'code':k[1],'ex_date':k[2],'record_date':records[0] if records else '','announcement_date':'','action_type':'','cash_per_share':'0','bonus_per_share':'0','transfer_per_share':'0','rights_per_share':'0','rights_price':'0','rights_listing_date':'','source_count':0,'source_evidence':'[]'}
def reconcile_sse_nonrights(pm,controls):
 checked=0;matched=0;fills=[];overrides=[]
 for k,c in sorted(controls.items()):
  if not c['nonrights_rows']:continue
  checked+=1;p=pm.get(k);created=p is None
  if created:p=blank_from_sse(k,c['nonrights_rows']);pm[k]=p
  before={x:D(p[x]) for x in ('cash_per_share','bonus_per_share','transfer_per_share')};changed=False;used=[]
  if c['has_dividend_table']:
   target=c['cash'];old=before['cash_per_share']
   if abs(old-target)>TOL:
    changed=True
    if old!=0:overrides.append({'key':k,'field':'cash_per_share','cninfo':str(old),'sse_native':str(target)})
    else:fills.append({'key':k,'field':'cash_per_share','value':str(target),'reason':'CNINFO_COMPONENT_ABSENT'})
   p['cash_per_share']=str(target);used+=c['dividend_rows']
  if c['has_bonus_table']:
   used+=c['bonus_rows']
   for field,target in [('bonus_per_share',c['bonus']),('transfer_per_share',c['transfer'])]:
    old=before[field]
    if abs(old-target)>TOL:
     changed=True
     if old!=0:overrides.append({'key':k,'field':field,'cninfo':str(old),'sse_native':str(target)})
     else:fills.append({'key':k,'field':field,'value':str(target),'reason':'CNINFO_COMPONENT_ABSENT'})
    p[field]=str(target)
  if created:fills.append({'key':k,'field':'ACTION','value':'SSE_NATIVE','reason':'CNINFO_ACTION_ABSENT'})
  ev=merge_evidence(p.get('source_evidence',''),evidence_for(used));p['source_evidence']=json.dumps(ev,ensure_ascii=False,sort_keys=True);p['source_count']=len(ev)
  if not p.get('record_date'):
   records=sorted({r.get('record_date','') for r in used if r.get('record_date')});p['record_date']=records[0] if records else ''
  p['action_type']=action_type(p['cash_per_share'],p['bonus_per_share'],p['transfer_per_share'],p['rights_per_share'])
  if not changed and not created:matched+=1
 return {'checked':checked,'matched':matched,'fills':fills,'overrides':overrides}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();root=Path(a.root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True);errors=[];universe=life();query_universe=query_universe_keys(universe)
 cms=sorted(root.glob('g5_cninfo_actions_shard*.manifest.json'))
 if len(cms)!=8:errors.append(f'expected 8 CNINFO manifests, got {len(cms)}')
 primary=[];selected=0;source_hashes=[];requests=0
 for mp in cms:
  m=json.loads(mp.read_text(encoding='utf-8'));selected+=int(m.get('expected_selected_securities',0));requests+=len(m.get('requests') or [])
  if m.get('errors'):errors.append(f'{mp.name} source errors: {m["errors"][:10]}')
  df=root/m['data_file'];actual=hashlib.sha256(df.read_bytes()).hexdigest();source_hashes.append((df.name,actual))
  if actual!=m.get('data_sha256'):errors.append(f'{df.name} hash mismatch')
  primary+=read_gz(df)
 if selected!=len(query_universe):errors.append(f'CNINFO query identities {selected} != expected alias-collapsed universe {len(query_universe)}')
 sms=sorted(root.glob('g5_cninfo_rights_supplement_shard*.manifest.json'));supp_selected=0;supp_rows=0
 if sms:
  if len(sms)!=4:errors.append(f'expected 4 SZSE rights supplement manifests, got {len(sms)}')
  for mp in sms:
   m=json.loads(mp.read_text(encoding='utf-8'));supp_selected+=int(m.get('expected_selected_securities',0));requests+=len(m.get('requests') or [])
   if m.get('errors'):errors.append(f'{mp.name} source errors: {m["errors"][:10]}')
   df=root/m['data_file'];actual=hashlib.sha256(df.read_bytes()).hexdigest();source_hashes.append((df.name,actual))
   if actual!=m.get('data_sha256'):errors.append(f'{df.name} hash mismatch')
   rr=read_gz(df);supp_rows+=len(rr);primary+=rr
  expected_sz=sum(1 for ex,c in query_universe if ex=='SZSE')
  if supp_selected!=expected_sz:errors.append(f'SZSE rights supplement query identities {supp_selected} != expected {expected_sz}')
 control_files=sorted(root.glob('g5_sse_official_actions.csv.gz'));control_rows=[]
 if len(control_files)!=1:errors.append(f'expected one SSE native control file, got {len(control_files)}')
 else:
  control_rows=read_gz(control_files[0]);source_hashes.append((control_files[0].name,hashlib.sha256(control_files[0].read_bytes()).hexdigest()));primary += [r for r in control_rows if r['action_component']=='RIGHTS']
 remaps=remap_code_time(primary)
 for r in primary:
  k=(r['exchange'],r['code']);interval=universe.get(k)
  if not interval:errors.append(f'out-of-universe official row {k}');continue
  dd=date.fromisoformat(r['ex_date']);x,y=interval
  if not (START<=dd<=END and x<=dd and (y is None or dd<y)):errors.append(f'official action outside lifecycle {(k,r["ex_date"])}')
 pm=merge_components(primary,errors);controls=aggregate_sse_control(control_rows);recon=reconcile_sse_nonrights(pm,controls)
 unresolved_missing=[];unresolved_conflicts=[]
 for k,c in sorted(controls.items()):
  if not c['nonrights_rows']:continue
  p=pm.get(k)
  if p is None:unresolved_missing.append(k);continue
  if c['has_dividend_table'] and abs(D(p['cash_per_share'])-c['cash'])>TOL:unresolved_conflicts.append((k,'cash'))
  if c['has_bonus_table']:
   if abs(D(p['bonus_per_share'])-c['bonus'])>TOL:unresolved_conflicts.append((k,'bonus'))
   if abs(D(p['transfer_per_share'])-c['transfer'])>TOL:unresolved_conflicts.append((k,'transfer'))
 if unresolved_missing:errors.append(f'unresolved SSE native non-rights events: {unresolved_missing[:20]} count={len(unresolved_missing)}')
 if unresolved_conflicts:errors.append(f'unresolved SSE native component conflicts: {unresolved_conflicts[:20]} count={len(unresolved_conflicts)}')
 rows=list(pm.values());rows.sort(key=lambda r:(r['ex_date'],r['exchange'],r['code']))
 for r in rows:
  if not r['action_type']:errors.append(f'zero-economic merged action {(r["exchange"],r["code"],r["ex_date"])}')
 p=out/'g5_official_actions.csv.gz'
 with gzip.open(p,'wt',encoding='utf-8',newline='',compresslevel=9) as f:w=csv.DictWriter(f,fieldnames=OUT_FIELDS);w.writeheader();w.writerows(rows)
 types={}
 for r in rows:types[r['action_type']]=types.get(r['action_type'],0)+1
 digest=hashlib.sha256(p.read_bytes()).hexdigest();finger=hashlib.sha256(('\n'.join(f'{n}:{h}' for n,h in sorted(source_hashes))+'\n'+digest).encode()).hexdigest()
 report={'stage':'G5_OFFICIAL_ACTION_LEDGER','pass':not errors,'coverage_start':START.isoformat(),'coverage_end':END.isoformat(),'lifecycle_security_count':len(universe),'source_query_identity_count':len(query_universe),'code_time_action_remaps':len(remaps),'code_time_action_remap_samples':remaps[:100],'cninfo_component_rows':sum(1 for r in primary if r.get('source_system')=='CNINFO'),'szse_rights_supplement_rows':supp_rows,'sse_native_rights_primary_rows':sum(r['action_component']=='RIGHTS' for r in control_rows),'official_action_dates':len(rows),'action_type_counts':types,'cninfo_source_requests':requests,'sse_native_control_rows':len(control_rows),'sse_native_controls_checked':recon['checked'],'sse_native_controls_matched':recon['matched'],'sse_native_component_fills':len(recon['fills']),'sse_native_component_overrides':len(recon['overrides']),'sse_native_component_fill_samples':recon['fills'][:100],'sse_native_component_override_samples':recon['overrides'][:100],'sse_native_control_missing':len(unresolved_missing),'sse_native_control_conflicts':len(unresolved_conflicts),'reconciliation_policy':'SSE venue-native component value when that SSE sub-table publishes the component; CNINFO fills components absent from the SSE sub-table; SSE sub-table absence is never interpreted as economic zero; source query aliases are remapped to the security code effective on each ex-date','dataset_sha256':digest,'dataset_fingerprint':finger,'errors':errors}
 (out/'g5_official_action_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
