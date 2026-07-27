#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--out',required=True);args=ap.parse_args();root=Path(args.root);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
 ms=sorted(root.glob('g4_manifest_shard*.json')); errors=[]
 if len(ms)!=16:errors.append(f'expected 16 shard manifests, got {len(ms)}')
 total={'securities':0,'rows':0,'tradable':0,'suspended':0,'risk_warning':0}; zeros=[]; unknown=[]; source_codes=set(); source_rows=0; source_hash_missing=0
 for mp in ms:
  m=json.loads(mp.read_text(encoding='utf-8')); df=root/m['data_file']
  if not df.exists():errors.append(f'missing {df.name}');continue
  if sha(df)!=m['data_sha256']:errors.append(f'data sha mismatch {df.name}')
  for k in total:total[k]+=m['counts'][k]
  zeros+=m['zero_source_securities'];unknown+=m['unclassified_special_days']
  for s in m['source_manifest']:
   source_codes.add((s['exchange'],s['code']));source_rows+=s['rows'];source_hash_missing+=not bool(s['sha256'])
 if source_rows!=total['rows']:errors.append(f'source rows {source_rows} != normalized {total["rows"]}')
 if source_hash_missing:errors.append(f'{source_hash_missing} source hashes missing')
 # Full row audit.
 seen=set(); state_rows=0; r601268=[]; bad_limits=[]
 for df in sorted(root.glob('g4_state_shard*.csv.gz')):
  with gzip.open(df,'rt',encoding='utf-8',newline='') as f:
   for r in csv.DictReader(f):
    k=(r['exchange'],r['code'],r['trade_date']);state_rows+=1
    if k in seen:errors.append(f'duplicate {k}');break
    seen.add(k)
    if r['tradable']=='0' and r['limit_rule']!='SUSPENDED':bad_limits.append(k)
    if r['limit_rule']=='UNCLASSIFIED_SPECIAL_NO_LIMIT':unknown.append({'exchange':r['exchange'],'code':r['code'],'date':r['trade_date'],'pctChg':r['pct_chg']})
    if r['exchange']=='SSE' and r['code']=='601268':r601268.append(r)
 if state_rows!=total['rows']:errors.append(f'scanned rows {state_rows} != manifest rows {total["rows"]}')
 if bad_limits:errors.append(f'suspended rows with non-suspended rule: {bad_limits[:20]}')
 if zeros:errors.append(f'active lifecycle securities absent from BaoStock: {zeros[:20]} count={len(zeros)}')
 if unknown:errors.append(f'unclassified special no-limit days: {unknown[:20]} count={len(unknown)}')
 if not r601268:errors.append('601268 missing from G4 state')
 elif any(r['tradable']!='0' for r in r601268):errors.append('601268 expected suspended throughout G4-covered 2015 interval')
 report={'gate':'G4','pass':not errors,'coverage_start':'2015-01-01','coverage_end':'2026-07-24','counts':total,'source_security_count':len(source_codes),'state_rows':state_rows,'zero_source_securities':zeros,'unclassified_special_days':unknown[:100],'601268_rows':len(r601268),'601268_all_suspended':bool(r601268) and all(r['tradable']=='0' for r in r601268),'errors':errors}
 (out/'g4_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 (out/'g4_manifest.json').write_text(json.dumps({'version':'V3.2.21-g4-daily-security-state','status':'PASS' if not errors else 'FAIL','scope':'SSE_MAIN_A + SZSE_MAIN_A','sources':['BaoStock point-in-time tradestatus/isST/preclose/pctChg','SSE/SZSE exchange trading rules versioned by effective date'],'rule_breaks':{'main_board_registration_first5_no_limit':'2023-04-10','risk_warning_10pct':'2026-07-06'},'audit':report},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
