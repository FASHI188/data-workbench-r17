#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,sys
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; START=date(2015,1,1); END=date(2026,7,24); DELIST_REFORM=date(2020,12,31)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def expected_lifecycle_codes():
 out=set()
 with (ROOT/'data/security_lifecycle/security_intervals.csv').open(encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):
   a=date.fromisoformat(r['listed_from']);b=date.fromisoformat(r['listed_to_exclusive']) if r['listed_to_exclusive'] else None
   if a<=END and (b is None or b>START):out.add((r['exchange'],r['code']))
 return out

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--out',required=True);args=ap.parse_args();root=Path(args.root);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
 ms=sorted(root.glob('g4_manifest_shard*.json'));errors=[];expected=expected_lifecycle_codes()
 if len(ms)!=16:errors.append(f'expected 16 shard manifests, got {len(ms)}')
 total={'securities':0,'rows':0,'tradable':0,'suspended':0,'risk_warning':0};zeros=[];unknown=[];source_codes=set();source_rows=0;source_hash_missing=0;data_hashes=[];delisting_first_days=[];delisting_periods=[]
 for mp in ms:
  m=json.loads(mp.read_text(encoding='utf-8'));df=root/m['data_file']
  if not df.exists():errors.append(f'missing {df.name}');continue
  actual=sha(df);data_hashes.append((df.name,actual))
  if actual!=m['data_sha256']:errors.append(f'data sha mismatch {df.name}')
  for k in total:total[k]+=m['counts'][k]
  zeros+=m['zero_source_securities'];unknown+=m['unclassified_special_days'];delisting_first_days+=m.get('delisting_first_days') or [];delisting_periods+=m.get('delisting_periods') or []
  for s in m['source_manifest']:
   source_codes.add((s['exchange'],s['code']));source_rows+=s['rows'];source_hash_missing+=not bool(s['sha256'])
 if source_codes!=expected:
  errors.append(f'G4 security universe mismatch expected={len(expected)} actual={len(source_codes)} only_expected={sorted(expected-source_codes)[:20]} only_actual={sorted(source_codes-expected)[:20]}')
 if total['securities']!=len(expected):errors.append(f'manifest securities {total["securities"]} != expected lifecycle securities {len(expected)}')
 if source_rows!=total['rows']:errors.append(f'source rows {source_rows} != normalized {total["rows"]}')
 if source_hash_missing:errors.append(f'{source_hash_missing} source hashes missing')
 regime_counts={};period_by_code={}
 for p in delisting_periods:
  k=(p['exchange'],p['code']);period_by_code[k]=p;regime_counts[p['regime']]=regime_counts.get(p['regime'],0)+1;n=int(p['trade_days']);fd=date.fromisoformat(p['first_date'])
  if p['regime']=='OLD_30DAY_ALL_10PCT':
   if n>30:errors.append(f'old delisting period >30 trade days: {p}')
   if fd>=DELIST_REFORM and n<=15:errors.append(f'post-reform <=15-day period misclassified old: {p}')
  elif p['regime']=='NEW_15DAY_FIRST_NO_LIMIT':
   if n>15:errors.append(f'new delisting period >15 trade days: {p}')
   if fd<DELIST_REFORM:errors.append(f'pre-reform period misclassified new: {p}')
  else:errors.append(f'unknown delisting regime: {p}')
 seen=set();state_rows=0;r601268=[];bad_limits=[];row_codes=set();special_no_limit=[];delist_rule_rows={}
 for df in sorted(root.glob('g4_state_shard*.csv.gz')):
  with gzip.open(df,'rt',encoding='utf-8',newline='') as f:
   for r in csv.DictReader(f):
    k=(r['exchange'],r['code'],r['trade_date']);state_rows+=1;row_codes.add((r['exchange'],r['code']))
    if k in seen:errors.append(f'duplicate {k}');break
    seen.add(k)
    if r['tradable']=='0' and r['limit_rule']!='SUSPENDED':bad_limits.append(k)
    if r['limit_rule']=='UNCLASSIFIED_SPECIAL_NO_LIMIT':unknown.append({'exchange':r['exchange'],'code':r['code'],'date':r['trade_date'],'pctChg':r['pct_chg']})
    if 'NO_LIMIT' in r['limit_rule'] or r['limit_rule']=='IPO_FIRST_DAY_2014_RULE':special_no_limit.append({'exchange':r['exchange'],'code':r['code'],'date':r['trade_date'],'rule':r['limit_rule']})
    if r['limit_rule'].startswith('DELISTING_'):delist_rule_rows.setdefault((r['exchange'],r['code']),[]).append(r)
    if r['exchange']=='SSE' and r['code']=='601268':r601268.append(r)
 if state_rows!=total['rows']:errors.append(f'scanned rows {state_rows} != manifest rows {total["rows"]}')
 if row_codes!=(expected-set(tuple(z.split(':')) for z in zeros)):errors.append(f'row-level security set mismatch row_codes={len(row_codes)} expected_nonzero={len(expected)-len(zeros)}')
 if bad_limits:errors.append(f'suspended rows with non-suspended rule: {bad_limits[:20]}')
 if zeros:errors.append(f'active lifecycle securities absent from BaoStock: {zeros[:20]} count={len(zeros)}')
 if unknown:errors.append(f'unclassified special no-limit days: {unknown[:20]} count={len(unknown)}')
 for k,p in period_by_code.items():
  rs=delist_rule_rows.get(k,[]);trade_dates={r['trade_date'] for r in rs};expected_dates=set()
  # Every detected final trading-block row must be explicitly classified as a delisting rule row.
  first=p['first_date'];last=p['last_date']
  if not rs:errors.append(f'detected delisting period has no classified rows: {k} {p}');continue
  if p['regime']=='OLD_30DAY_ALL_10PCT':
   if any(r['limit_rule']!='DELISTING_CONSOLIDATION_10PCT' for r in rs):errors.append(f'old-regime delisting contains non-10pct row: {k}')
  else:
   first_rows=[r for r in rs if r['trade_date']==first]
   if len(first_rows)!=1 or first_rows[0]['limit_rule']!='DELISTING_15DAY_FIRST_DAY_NO_LIMIT':errors.append(f'new-regime first day not no-limit: {k} {p}')
   if any(r['trade_date']!=first and r['limit_rule']!='DELISTING_CONSOLIDATION_10PCT' for r in rs):errors.append(f'new-regime later day not 10pct: {k}')
 if not r601268:errors.append('601268 missing from G4 state')
 elif any(r['tradable']!='0' for r in r601268):errors.append('601268 expected suspended throughout G4-covered 2015 interval')
 canonical='\n'.join(f'{n}:{h}' for n,h in sorted(data_hashes)).encode();fingerprint=hashlib.sha256(canonical).hexdigest()
 report={'gate':'G4','pass':not errors,'coverage_start':'2015-01-01','coverage_end':'2026-07-24','expected_security_count':len(expected),'counts':total,'source_security_count':len(source_codes),'row_security_count':len(row_codes),'state_rows':state_rows,'zero_source_securities':zeros,'unclassified_special_days':unknown[:100],'detected_special_no_limit_days':len(special_no_limit),'detected_delisting_periods':len(delisting_periods),'delisting_regime_counts':regime_counts,'601268_rows':len(r601268),'601268_all_suspended':bool(r601268) and all(r['tradable']=='0' for r in r601268),'dataset_fingerprint':fingerprint,'errors':errors}
 (out/'g4_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 (out/'g4_manifest.json').write_text(json.dumps({'version':'V3.2.21-g4-daily-security-state','status':'PASS' if not errors else 'FAIL','scope':'SSE_MAIN_A + SZSE_MAIN_A','sources':['BaoStock point-in-time tradestatus/isST/preclose/pctChg','SSE/SZSE exchange rules versioned by historical regime'],'rule_breaks':{'delisting_reform_published':'2020-12-31; old-rule transitional issuers identified by 30-day final block','main_board_registration_first5_no_limit':'2023-04-10','risk_warning_10pct':'2026-07-06'},'audit':report},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
