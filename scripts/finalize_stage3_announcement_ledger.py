#!/usr/bin/env python3
from __future__ import annotations
import argparse,bisect,csv,gzip,hashlib,io,json
from collections import defaultdict,Counter
from datetime import date,datetime
from pathlib import Path
from zoneinfo import ZoneInfo
TZ=ZoneInfo('Asia/Shanghai');EXPECTED=3402
FIELDS=['exchange','source_code','effective_code','source_instrument_codes','org_id','announcement_id','announcement_title','event_categories','source_published_at','publication_precision','effective_session','available_at','usable_in_stage2','availability_reason','source_url','query_response_sha256']
def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def readgz(p):
 with gzip.open(p,'rt',encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):yield r
def write_deterministic_csv_gz(p:Path,fields,rows):
 # Canonical Stage3 output must be byte-reproducible across clean reruns.
 # Suppress filename and wall-clock mtime from the gzip header while preserving
 # the existing CSV encoding/newline/compression semantics.
 with p.open('wb') as raw:
  with gzip.GzipFile(filename='',mode='wb',fileobj=raw,compresslevel=9,mtime=0) as gz:
   with io.TextIOWrapper(gz,encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def load_intervals(p):
 out={}
 with Path(p).open(encoding='utf-8',newline='') as f:
  for r in csv.DictReader(f):out[(r['exchange'],r['code'])]=(date.fromisoformat(r['listed_from']),date.fromisoformat(r['listed_to_exclusive']) if r.get('listed_to_exclusive') else None)
 return out
def active(iv,d):return bool(iv and d>=iv[0] and (iv[1] is None or d<iv[1]))
def remap(ex,code,d,ivs,ts):
 if active(ivs.get((ex,code)),d):return code
 for t in ts:
  if t['exchange']==ex and t['old_code']==code and d>=date.fromisoformat(t['effective_date']) and active(ivs.get((ex,t['new_code'])),d):return t['new_code']
 return None
def trading_days(root):
 ds=set()
 for p in sorted(Path(root).rglob('szse_*.csv.gz')):
  with gzip.open(p,'rt',encoding='utf-8',newline='') as f:
   rd=csv.DictReader(f)
   if not rd.fieldnames or 'trade_date' not in rd.fieldnames:continue
   for r in rd:
    if r.get('trade_date'):ds.add(date.fromisoformat(r['trade_date']))
 return sorted(ds)
def nextday(d,days):
 i=bisect.bisect_right(days,d);return days[i] if i<len(days) else None
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--g2-intervals',required=True);ap.add_argument('--g3-root',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();root=Path(a.root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True);errors=[]
 mps=sorted(root.rglob('announcement_ledger_shard*.manifest.json'));dps=sorted(root.rglob('announcement_ledger_shard*.csv.gz'))
 if len(mps)!=16:errors.append(f'expected 16 manifests got {len(mps)}')
 if len(dps)!=16:errors.append(f'expected 16 data files got {len(dps)}')
 selected=0;stockshas=set();mm={};cat=Counter();srcrows=0;instrument_rows=0
 for p in mps:
  m=json.loads(p.read_text(encoding='utf-8'));selected+=int(m.get('security_identities',0));srcrows+=int(m.get('rows',0));stockshas.add(m.get('stock_map_sha256'));mm[int(m['shard'])]=m;cat.update({k:int(v) for k,v in (m.get('category_totals') or {}).items()});instrument_rows+=int(m.get('same_issuer_non_equity_instrument_rows') or 0)
  if m.get('errors'):errors.append(f"shard {m['shard']} errors {m['errors'][:10]}")
 if selected!=EXPECTED:errors.append(f'security identities {selected} != {EXPECTED}')
 if len(stockshas)!=1:errors.append(f'stock map changed {stockshas}')
 raw=[]
 for p in dps:
  sh=int(p.stem.split('shard')[-1].split('.')[0]);m=mm.get(sh)
  if m and sha(p)!=m.get('data_sha256'):errors.append(f'data hash mismatch shard {sh}')
  raw.extend(readgz(p))
 if len(raw)!=srcrows:errors.append(f'raw rows {len(raw)} != manifests {srcrows}')
 # Collapse category-overlap of the same official announcement. The A-share
 # identity remains r['code']; non-equity source instruments are retained only
 # as provenance and never become tradeable equity identities.
 groups=defaultdict(list)
 for r in raw:groups[(r['exchange'],r['code'],r['announcement_id'])].append(r)
 ivs=load_intervals(a.g2_intervals);ts=json.loads((Path(__file__).resolve().parents[1]/'config/security_code_transitions.json').read_text(encoding='utf-8'));days=trading_days(a.g3_root)
 if len(days)!=2808:errors.append(f'G3 trading days {len(days)} != 2808')
 output=[];missing_pub=[];missing_url=[];remaps=[];unusable=[];cat_final=Counter();instrument_announcements=[]
 for key,rs in groups.items():
  r=rs[0];cats=sorted({x['event_category'] for x in rs});cat_final.update(cats);pub=r.get('source_published_date') or ''
  if not pub:missing_pub.append(key);eff=None
  else:eff=nextday(date.fromisoformat(pub),days)
  code2=remap(r['exchange'],r['code'],eff,ivs,ts) if eff else None;usable=bool(code2);reason='DATE_ONLY_NEXT_G3_TRADING_SESSION' if usable else ('NO_LATER_G3_SESSION_WITHIN_STAGE2' if pub and eff is None else 'NO_ACTIVE_SECURITY_IDENTITY_ON_NEXT_SESSION')
  if code2 and code2!=r['code']:remaps.append([r['exchange'],r['code'],code2,r['announcement_id'],pub,eff.isoformat()])
  if not usable:unusable.append([r['exchange'],r['code'],r['announcement_id'],pub,eff.isoformat() if eff else None])
  if not r.get('source_url'):missing_url.append(key)
  shas=sorted({x['query_response_sha256'] for x in rs});urls=sorted({x['source_url'] for x in rs if x['source_url']});titles=sorted({x['announcement_title'] for x in rs})
  instruments=sorted({x.get('source_instrument_code') for x in rs if x.get('source_instrument_code') and x.get('source_instrument_code')!=x.get('code')})
  if instruments:instrument_announcements.append([r['exchange'],r['code'],r['announcement_id'],instruments])
  if len(urls)>1:errors.append(f'multiple source URLs for announcement {key}: {urls}')
  output.append({'exchange':r['exchange'],'source_code':r['code'],'effective_code':code2 or '','source_instrument_codes':json.dumps(instruments,ensure_ascii=False),'org_id':r['org_id'],'announcement_id':r['announcement_id'],'announcement_title':titles[-1] if titles else '','event_categories':json.dumps(cats,ensure_ascii=False),'source_published_at':pub,'publication_precision':'DATE_ONLY','effective_session':eff.isoformat() if eff else '','available_at':datetime.combine(eff,datetime.min.time(),tzinfo=TZ).isoformat() if usable else '','usable_in_stage2':'1' if usable else '0','availability_reason':reason,'source_url':urls[0] if urls else '','query_response_sha256':json.dumps(shas,ensure_ascii=False)})
 if missing_pub:errors.append(f'missing publication date {missing_pub[:20]} count={len(missing_pub)}')
 if missing_url:errors.append(f'missing source URL {missing_url[:20]} count={len(missing_url)}')
 output.sort(key=lambda r:(r['source_published_at'],r['exchange'],r['source_code'],r['announcement_id']))
 p=out/'stage3_announcement_ledger.csv.gz'
 write_deterministic_csv_gz(p,FIELDS,output)
 report={'gate':'S3G2_POINT_IN_TIME_ANNOUNCEMENT_LEDGER','pass':not errors,'security_identity_count':selected,'g3_trading_days':len(days),'raw_category_rows':len(raw),'unique_announcements':len(output),'source_category_totals':dict(cat),'final_category_memberships':dict(cat_final),'code_time_remaps':len(remaps),'code_time_remap_samples':remaps[:100],'same_issuer_non_equity_instrument_rows':instrument_rows,'same_issuer_non_equity_instrument_announcements':len(instrument_announcements),'same_issuer_non_equity_instrument_samples':instrument_announcements[:100],'unusable_count':len(unusable),'unusable_samples':unusable[:100],'ledger_sha256':sha(p),'gzip_header_mtime':0,'gzip_embedded_filename':'','date_only_policy':'first strictly later G3 trading session','scalar_magnitude_from_title_allowed':False,'errors':errors}
 (out/'stage3_announcement_ledger_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':raise SystemExit(main())
