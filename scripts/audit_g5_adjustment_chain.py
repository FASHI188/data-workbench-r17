#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,sys
from decimal import Decimal,InvalidOperation
from pathlib import Path

EXPECTED_SHARDS=16

def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def d(x):
    try:return Decimal(str(x))
    except (InvalidOperation,ValueError):return Decimal('0')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--out',required=True);args=ap.parse_args()
    root=Path(args.root);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    manifests=sorted(root.glob('g5_manifest_shard*.json')); errors=[]
    if len(manifests)!=EXPECTED_SHARDS:errors.append(f'expected {EXPECTED_SHARDS} shard manifests, got {len(manifests)}')
    total_secs=0;total_events=0;unmatched=[];query_errors=[];source_hash_missing=0;source_codes=set();data_hashes=[]
    for mp in manifests:
        m=json.loads(mp.read_text(encoding='utf-8'));total_secs+=int(m.get('securities',0));total_events+=int(m.get('events',0))
        unmatched.extend(m.get('unmatched_factor_events') or []);query_errors.extend(m.get('query_errors') or [])
        df=root/m['data_file']
        if not df.exists():errors.append(f'missing {df.name}');continue
        actual=sha(df);data_hashes.append((df.name,actual))
        if actual!=m.get('data_sha256'):errors.append(f'data sha mismatch {df.name}')
        for s in m.get('source_manifest') or []:
            source_codes.add((s.get('exchange'),s.get('code')))
            if not s.get('sha256'):source_hash_missing+=1
    if query_errors:errors.append(f'query errors: {query_errors[:20]} count={len(query_errors)}')
    if unmatched:errors.append(f'unmatched factor events: {unmatched[:20]} count={len(unmatched)}')
    if source_hash_missing:errors.append(f'missing source hashes: {source_hash_missing}')
    seen=set();rows=0;matched=0;event_types={};bad=[]
    for df in sorted(root.glob('g5_events_shard*.csv.gz')):
        with gzip.open(df,'rt',encoding='utf-8',newline='') as f:
            for r in csv.DictReader(f):
                rows+=1;k=(r['exchange'],r['code'],r['effective_date'])
                if k in seen:errors.append(f'duplicate factor event {k}');break
                seen.add(k)
                if min(d(r['fore_adjust_factor']),d(r['back_adjust_factor']),d(r['adjust_factor']))<=0:bad.append(k)
                et=r['event_type'];event_types[et]=event_types.get(et,0)+1
                if et!='UNMATCHED_FACTOR_EVENT':matched+=1
    if rows!=total_events:errors.append(f'scanned events {rows} != manifest events {total_events}')
    if bad:errors.append(f'nonpositive factors: {bad[:20]} count={len(bad)}')
    canonical='\n'.join(f'{n}:{h}' for n,h in sorted(data_hashes)).encode();fingerprint=hashlib.sha256(canonical).hexdigest()
    report={'gate':'G5','pass':not errors,'coverage_start':'2015-01-01','coverage_end':'2026-07-24','source_security_count':len(source_codes),'securities_scanned':total_secs,'factor_events':rows,'matched_corporate_action_events':matched,'event_types':event_types,'unmatched_factor_event_count':len(unmatched),'query_error_count':len(query_errors),'dataset_fingerprint':fingerprint,'errors':errors}
    (out/'g5_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'version':'V3.2.22-g5-corporate-action-adjustment-chain','status':'PASS' if not errors else 'FAIL','scope':'SSE_MAIN_A + SZSE_MAIN_A','evidence_policy':{'adjustment_factors':'BaoStock query_adjust_factor point-in-time historical factor table','cash_stock_distributions':'BaoStock query_dividend_data exact operate-date match','unmatched_policy':'FAIL_CLOSED; enrich from CNINFO official announcement evidence before PASS'},'audit':report}
    (out/'g5_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
