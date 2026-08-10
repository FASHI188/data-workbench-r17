#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from collections import Counter
from pathlib import Path
import compare_stage3_s3g1j_v17_28_full_final as v28

TARGETS={
'1215186538':('c1856e15d16e6ede5f22a7a0c97dcfd540185573725b64861d8015fae1b4b920','2711641','2022-06-30',132),
'1219426855':('3bf864bff6823fea99b258604061b24012b1ed666a0a1a690af76bf54cb5b6b6','4817887','2023-12-31',296),
'1219792633':('2b2147c2d32df99613608371dea115dc09d49377c4ac423ce74d3b155207c5c3','4643170','2023-12-31',219),
'1219840508':('e29963a1bd008369d15d817407cb6ff4ffe1ea7740883d69db702800fcb33532','4502267','2023-12-31',257),
'1219879687':('0843638f31f9343156b7c87474918dd80604788bc8e8f479eca2882c5b95b534','3970627','2023-12-31',224),
'1220087244':('a77b09fb00fb234ab1923ff42d9908786c71ee2154bb22cfce0d0490dbcfaacd','4755545','2023-12-31',295),
'1221006100':('8679311bb2eb42e00d575404456fc5f0fb1a84d0ecab0ae3f6572b7962a1d806','3650480','2024-06-30',204),
}
EXPECTED_EXTRACTOR_METHOD='CNINFO_ORIGINAL_PDF_PYMUPDF_V19_V17_29_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION'
EXPECTED_PARSER_VERSION='V17_29_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION'
EXPECTED_METHODOLOGY='V3.3.13-V17.29'
EXPECTED_SHARD_GATE='S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_29'
read_gz=v28.read_gz; read_audit=v28.read_audit; canon=v28.canonical_document
numtuple=v28.numeric_tuple; semsha=v28.semantic_multiset_sha

def index(rows):
 out={}
 for r in rows:
  aid=r.get('announcement_id','')
  if not aid or aid in out: raise ValueError(f'invalid/duplicate document {aid!r}')
  out[aid]=r
 return out

def compare(prev_docs_rows,cur_docs_rows,prev_values_rows,cur_values_rows,gold_values_rows,prev_audit,cur_audit):
 e=[]; prev=index(prev_docs_rows); cur=index(cur_docs_rows)
 if len(prev)!=121354 or len(cur)!=121354:e.append(f'document count {len(prev)}->{len(cur)}')
 if set(prev)!=set(cur):e.append('document identities changed')
 changed=[aid for aid in sorted(set(prev)&set(cur)) if canon(prev[aid])!=canon(cur[aid])]
 if changed!=sorted(TARGETS):e.append(f'document delta expected={sorted(TARGETS)} actual={changed}')
 for aid,(sha,bytes_,date,pages) in TARGETS.items():
  old,new=prev.get(aid,{}),cur.get(aid,{})
  if old.get('document_status')=='PASS' or old.get('tie_resolution')!='TIE_SOURCE_INCOMPLETE':e.append(f'{aid}: prior not expected fail-closed tie')
  req={'document_status':'PASS','document_error':'','tie_candidate_count':'1','tie_resolution':'SINGLE_CANONICAL','selected_source_sha256':sha,'selected_source_bytes':bytes_,'numeric_observations':'3','tier1_found':'0','tier2_found':'3','economic_date':date}
  for k,w in req.items():
   if new.get(k,'')!=w:e.append(f'{aid}: {k} expected={w!r} actual={new.get(k,"")!r}')
  try:cands=json.loads(new.get('candidate_evidence_json') or '[]')
  except json.JSONDecodeError:cands=[];e.append(f'{aid}: bad candidate_evidence_json')
  exact=[x for x in cands if isinstance(x,dict) and str(x.get('id') or '')==aid and str(x.get('sha256') or '')==sha]
  if len(exact)!=1:e.append(f'{aid}: exact source evidence count={len(exact)}')
  else:
   reqev={'bytes':int(bytes_),'tier1_found':0,'tier2_found':3,'page_count':pages,'parser_version':EXPECTED_PARSER_VERSION,'validation_errors':[]}
   for k,w in reqev.items():
    if exact[0].get(k)!=w:e.append(f'{aid}: evidence {k} expected={w!r} actual={exact[0].get(k)!r}')
 prevc=Counter(numtuple(r) for r in prev_values_rows)
 curex=[r for r in cur_values_rows if r.get('announcement_id','') not in TARGETS]
 curc=Counter(numtuple(r) for r in curex); goldc=Counter(numtuple(r) for r in gold_values_rows)
 if len(prev_values_rows)!=1051799:e.append(f'previous numeric count={len(prev_values_rows)}')
 if len(cur_values_rows)!=1051820:e.append(f'current numeric count={len(cur_values_rows)}')
 if len(gold_values_rows)!=1051820:e.append(f'gold numeric count={len(gold_values_rows)}')
 if len(curex)!=1051799:e.append(f'current existing numeric count={len(curex)}')
 if prevc!=curc:e.append('existing numeric stable-field multiset drift')
 if Counter(numtuple(r) for r in cur_values_rows)!=goldc:e.append('fresh V17.29 stable-field multiset differs from accepted promotion gold')
 for aid in TARGETS:
  if any(r.get('announcement_id','')==aid for r in prev_values_rows):e.append(f'{aid}: prior basis already has numeric rows')
  rows=[r for r in cur_values_rows if r.get('announcement_id','')==aid]
  if len(rows)!=3:e.append(f'{aid}: target numeric row count={len(rows)}')
  if {r.get('concept','') for r in rows}!={'TOTAL_ASSETS','TOTAL_LIABILITIES','TOTAL_EQUITY'}:e.append(f'{aid}: target concept scope invalid')
  for r in rows:
   if r.get('extraction_method')!=EXPECTED_EXTRACTOR_METHOD:e.append(f'{aid}: extraction_method drift')
   if r.get('methodology_version')!=EXPECTED_METHODOLOGY:e.append(f'{aid}: methodology drift')
 prevexp={'runtime_generation':'V17.28','shard_gate':'S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_28','parser_method':'CNINFO_ORIGINAL_PDF_PYMUPDF_V18_V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION','methodology_version':'V3.3.8-V17.28','canonical_version_count':121354,'document_count':121354,'numeric_observation_count':1051799,'document_error_count':1371,'unresolved_tie_count':1288,'pass':False}
 curexp={'runtime_generation':'V17.29','shard_gate':EXPECTED_SHARD_GATE,'parser_method':EXPECTED_EXTRACTOR_METHOD,'methodology_version':EXPECTED_METHODOLOGY,'canonical_version_count':121354,'document_count':121354,'numeric_observation_count':1051820,'document_error_count':1364,'unresolved_tie_count':1281,'authority':'CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256','historical_current_f10_used_as_truth':False,'stage4_alpha_locked':True,'pass':False}
 for label,audit,exp in [('previous',prev_audit,prevexp),('current',cur_audit,curexp)]:
  for k,w in exp.items():
   if audit.get(k)!=w:e.append(f'{label} audit {k} expected={w!r} actual={audit.get(k)!r}')
 pt=Counter(r.get('tie_resolution','') for r in prev_docs_rows);ct=Counter(r.get('tie_resolution','') for r in cur_docs_rows)
 for k,o,n in [('TIE_SOURCE_INCOMPLETE',1274,1267),('TIE_VALUE_CONFLICT',14,14)]:
  if pt[k]!=o or ct[k]!=n:e.append(f'tie taxonomy {k} expected={o}->{n} actual={pt[k]}->{ct[k]}')
 return {'gate':'S3G1J_V17_29_FULL_BASIS_NON_REGRESSION','pass':not e,'execution_verdict':'PASS' if not e else 'FAIL','final_data_verdict':'FAIL_CLOSED','previous_document_count':len(prev_docs_rows),'current_document_count':len(cur_docs_rows),'previous_numeric_count':len(prev_values_rows),'current_numeric_count':len(cur_values_rows),'changed_announcement_ids':changed,'non_target_document_equal_count':len(cur)-len(changed),'existing_numeric_semantic_sha256_previous':semsha(prevc),'existing_numeric_semantic_sha256_current':semsha(curc),'fresh_numeric_semantic_sha256':semsha(Counter(numtuple(r) for r in cur_values_rows)),'promotion_gold_numeric_semantic_sha256':semsha(goldc),'previous_unresolved_ties':prev_audit.get('unresolved_tie_count'),'current_unresolved_ties':cur_audit.get('unresolved_tie_count'),'errors':e,'stage4_alpha_locked':True}

def main():
 ap=argparse.ArgumentParser()
 for flag in ['previous-documents','current-documents','previous-values','current-values','gold-values','previous-audit','current-audit','out']:ap.add_argument('--'+flag,required=True)
 a=ap.parse_args();r=compare(read_gz(Path(a.previous_documents)),read_gz(Path(a.current_documents)),read_gz(Path(a.previous_values)),read_gz(Path(a.current_values)),read_gz(Path(a.gold_values)),read_audit(Path(a.previous_audit)),read_audit(Path(a.current_audit)))
 Path(a.out).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r['pass'] else 2
if __name__=='__main__':raise SystemExit(main())
