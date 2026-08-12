#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,io,json
from collections import Counter
from pathlib import Path

FIELDS=['announcement_id','exchange','source_code','effective_code','issuer_org_id','report_family','economic_date','tie_resolution','tie_candidate_count','candidate_tier2_max','residual_class','retention_action','retention_reason']
P0_ORDINARY={
 '1202799494':'DIAGNOSTIC_ONLY_ROLE_BINDING_MISSING',
 '1204077386':'DIAGNOSTIC_ONLY_ROLE_LOCAL_PERIOD_MISSING',
 '1205543437':'DIAGNOSTIC_ONLY_ROLE_LOCAL_PERIOD_MISSING',
 '1209806910':'DIAGNOSTIC_ONLY_ROLE_BINDING_MISSING',
}
P0_BANK={'1219834247':'BANK_SPECIFIC_DO_NOT_PROMOTE_ORDINARY_PATH'}
RECOVERED={'1223347318','1223407043'}

def sha_file(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def write_det_gzip_csv(path:Path, rows:list[dict]):
 raw=io.BytesIO()
 with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0,compresslevel=9) as gz:
  txt=io.TextIOWrapper(gz,encoding='utf-8',newline='',write_through=True)
  w=csv.DictWriter(txt,fieldnames=FIELDS,lineterminator='\n');w.writeheader();w.writerows(rows);txt.flush()
 path.write_bytes(raw.getvalue())

def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument('--documents',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 total=passed=0; rows=[]; tie=Counter(); classes=Counter(); p0_seen={}; recovered_seen={}
 with gzip.open(a.documents,'rt',encoding='utf-8',newline='') as f:
  r=csv.DictReader(f)
  for d in r:
   total+=1
   aid=d['announcement_id']
   if d['document_status']=='PASS':
    passed+=1
    if aid in RECOVERED: recovered_seen[aid]=True
    continue
   tr=d['tie_resolution']; tc=int(d['tie_candidate_count'] or 0); tie[tr]+=1
   try: ce=json.loads(d['candidate_evidence_json'] or '[]')
   except Exception: ce=[]
   t2=max([int(x.get('tier2_found') or 0) for x in ce] or [0])
   if tr=='TIE_SOURCE_INCOMPLETE':
    if tc==1: cls=f'SINGLE_CANONICAL_SOURCE_INCOMPLETE_TIER2_{t2}'
    else: cls=f'MULTI_CANDIDATE_SOURCE_INCOMPLETE_{tc}_CANDIDATES'
   elif tr=='CANONICAL_PDF_ISSUER_MISMATCH': cls='CANONICAL_PDF_ISSUER_MISMATCH'
   elif tr=='TIE_VALUE_CONFLICT': cls='MULTI_CANDIDATE_VALUE_CONFLICT'
   else: cls=f'UNEXPECTED_{tr or "EMPTY"}'
   classes[cls]+=1
   special=P0_ORDINARY.get(aid) or P0_BANK.get(aid)
   if special: p0_seen[aid]=special
   reason=special or cls
   rows.append({
    'announcement_id':aid,'exchange':d['exchange'],'source_code':d['source_code'],'effective_code':d['effective_code'],'issuer_org_id':d['issuer_org_id'],'report_family':d['report_family'],'economic_date':d['economic_date'],'tie_resolution':tr,'tie_candidate_count':tc,'candidate_tier2_max':t2,'residual_class':cls,
    'retention_action':'RETAIN_FAIL_CLOSED_AS_MISSING_NO_VALUE_CONSTRUCTION',
    'retention_reason':reason,
   })
 errors=[]
 exp_tie={'TIE_SOURCE_INCOMPLETE':1265,'CANONICAL_PDF_ISSUER_MISMATCH':83,'TIE_VALUE_CONFLICT':14}
 exp_classes={
  'SINGLE_CANONICAL_SOURCE_INCOMPLETE_TIER2_0':550,
  'SINGLE_CANONICAL_SOURCE_INCOMPLETE_TIER2_1':421,
  'SINGLE_CANONICAL_SOURCE_INCOMPLETE_TIER2_2':131,
  'SINGLE_CANONICAL_SOURCE_INCOMPLETE_TIER2_3':76,
  'MULTI_CANDIDATE_SOURCE_INCOMPLETE_2_CANDIDATES':85,
  'MULTI_CANDIDATE_SOURCE_INCOMPLETE_3_CANDIDATES':2,
  'CANONICAL_PDF_ISSUER_MISMATCH':83,
  'MULTI_CANDIDATE_VALUE_CONFLICT':14,
 }
 if total!=121354: errors.append(f'document total {total} != 121354')
 if passed!=119992: errors.append(f'PASS total {passed} != 119992')
 if len(rows)!=1362: errors.append(f'residual total {len(rows)} != 1362')
 if dict(tie)!=exp_tie: errors.append(f'tie taxonomy {dict(tie)} != {exp_tie}')
 if dict(classes)!=exp_classes: errors.append(f'class taxonomy {dict(classes)} != {exp_classes}')
 if set(p0_seen)!=set(P0_ORDINARY)|set(P0_BANK): errors.append(f'P0 survivor mismatch {p0_seen}')
 if set(recovered_seen)!=RECOVERED: errors.append(f'recovered V17.30 targets not PASS {recovered_seen}')
 rows.sort(key=lambda x:(x['announcement_id'],x['residual_class']))
 ledger=out/'stage3_s3g1j_v17_30_residual_retention.csv.gz';write_det_gzip_csv(ledger,rows)
 report={
  'gate':'S3G1J_V17_30_RESIDUAL_RETENTION_CLOSURE','pass':not errors,'source_generation':'V17.30','source_full_final_run_id':31518370789,'source_full_final_artifact_id':9112098872,
  'document_count':total,'pass_document_count':passed,'residual_document_count':len(rows),'unresolved_tie_count':1279,'tie_taxonomy':dict(tie),'retention_class_counts':dict(classes),
  'ordinary_p0_formally_retained':P0_ORDINARY,'bank_specific_formally_retained':P0_BANK,'v17_30_recovered_targets':sorted(RECOVERED),
  'retention_policy':'Every residual remains missing/fail-closed. No numeric value may be constructed, inferred, imputed, OCR-derived, fuzzy-matched, issuer-relaxed, PIT-relaxed, or tolerance-relaxed from a retained row.',
  'downstream_contract':{'retained_rows_usable_as_numeric_truth':False,'retained_rows_must_be_excluded_from_numeric_feature_values':True,'missingness_may_be_preserved_as_missing':True,'E_equals_A_minus_L_inference_allowed':False,'OCR_allowed':False,'fuzzy_alias_allowed':False,'issuer_gate_relaxation_allowed':False,'PIT_relaxation_allowed':False,'accounting_tolerance_relaxation_allowed':False},
  'raw_data_verdict':'FAIL_CLOSED_WITH_FORMALLY_RETAINED_RESIDUALS','residual_retention_final_gate_pass':not errors,'ledger_sha256':sha_file(ledger),'errors':errors,
 }
 (out/'stage3_s3g1j_v17_30_residual_retention_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if not errors else 2
if __name__=='__main__': raise SystemExit(main())
