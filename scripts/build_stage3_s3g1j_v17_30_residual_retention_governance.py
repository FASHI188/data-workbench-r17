#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path

EXECUTION_PR=129
EXECUTION_HEAD='bf32938fea81b6133592f7f3ba2456897e65bd1d'
RUN_ID=31555404674
ARTIFACT_ID=9125809076
ARTIFACT_NAME='stage3-s3g1j-v17-30-residual-retention-closure'
ARTIFACT_DIGEST='sha256:d0921e3069abb695de54de4d3ecec5a5394e831a820757d1b2e2fda02861722a'
LEDGER_SHA='706b5dd219e94f786674b549859dd4695b42a02bcceb42fae8f91d358eeb83ef'
AUDIT_SHA='9eac8264d20e44ac7c1e972935064797b7ee778d9bce8bed6b198da715381ca9'
OUTPUT_SHA='cd4d3937e121519cf2b0e567ba4c60f8d658257435f1b0696cb6b89d2bf56cb7'


def load(p:str)->dict:return json.loads(Path(p).read_text(encoding='utf-8'))
def dump(p:Path,x:dict):p.write_text(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()

def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument('--authority',required=True);ap.add_argument('--lock',required=True);ap.add_argument('--project',required=True);ap.add_argument('--retention-audit',required=True);ap.add_argument('--governance-pr',required=True,type=int);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 au=load(a.authority);lock=load(a.lock);project=load(a.project);audit=load(a.retention_audit);errors=[]
 if audit.get('pass') is not True or audit.get('residual_retention_final_gate_pass') is not True:errors.append('retention audit not PASS')
 if audit.get('residual_document_count')!=1362 or audit.get('unresolved_tie_count')!=1279:errors.append('retention counts drift')
 if audit.get('tie_taxonomy')!={'TIE_SOURCE_INCOMPLETE':1265,'CANONICAL_PDF_ISSUER_MISMATCH':83,'TIE_VALUE_CONFLICT':14}:errors.append('retention tie taxonomy drift')
 if audit.get('ledger_sha256')!=LEDGER_SHA:errors.append('retention ledger SHA drift')
 d=audit.get('downstream_contract') or {}
 for k in ['retained_rows_usable_as_numeric_truth','E_equals_A_minus_L_inference_allowed','OCR_allowed','fuzzy_alias_allowed','issuer_gate_relaxation_allowed','PIT_relaxation_allowed','accounting_tolerance_relaxation_allowed']:
  if d.get(k) is not False:errors.append(f'forbidden retention permission {k}')
 if d.get('retained_rows_must_be_excluded_from_numeric_feature_values') is not True:errors.append('retained rows not excluded from numeric features')
 if errors:raise SystemExit('; '.join(errors))
 manifest={
  'schema_version':1,'gate':'S3G1J_V17_30_RESIDUAL_RETENTION_GOVERNANCE','status':'MACHINE_ACCEPTED_RETENTION_EVIDENCE_REGISTERED','governance_pr':a.governance_pr,
  'execution_pr':{'number':EXECUTION_PR,'head_sha':EXECUTION_HEAD,'closed_without_merge_required':True},
  'accepted_run':{'run_id':RUN_ID,'artifact_id':ARTIFACT_ID,'artifact_name':ARTIFACT_NAME,'artifact_digest':ARTIFACT_DIGEST,'ledger_sha256':LEDGER_SHA,'audit_sha256':AUDIT_SHA,'output_sha256_txt_sha256':OUTPUT_SHA},
  'source_full_basis':{'generation':'V17.30','run_id':31518370789,'artifact_id':9112098872,'document_count':121354,'numeric_observation_count':1051826,'document_error_count':1362,'unresolved_tie_count':1279,'raw_data_verdict':'FAIL_CLOSED'},
  'retention_result':{'retained_document_count':1362,'retained_unresolved_tie_count':1279,'tie_taxonomy':audit['tie_taxonomy'],'retention_class_counts':audit['retention_class_counts'],'ordinary_p0_formally_retained':audit['ordinary_p0_formally_retained'],'bank_specific_formally_retained':audit['bank_specific_formally_retained'],'raw_errors_removed':False,'raw_ties_removed':False,'retained_rows_usable_as_numeric_truth':False,'retained_rows_must_be_excluded_from_numeric_feature_values':True,'missingness_preserved':True},
  'hard_boundaries':{'OCR_allowed':False,'fuzzy_alias_allowed':False,'E_equals_A_minus_L_inference_allowed':False,'issuer_gate_relaxation_allowed':False,'PIT_relaxation_allowed':False,'accounting_tolerance_relaxation_allowed':False,'stage4_unlocked':False,'alpha_training_allowed':False,'live_signal_allowed':False,'main_changed':False},
  'interpretation':'S3G1J final gate closes by formal fail-closed retention, not by claiming raw errors/ties disappeared. The 1362 residual documents remain missing and are forbidden as numeric truth.'
 }
 g=(au['authoritative_components']['S3G1J_FINANCIAL_RAW_VALUES'])
 g.update({'residual_retention_evidence_manifest':'governance/stage3_s3g1j_v17_30_residual_retention.json','residual_retention_execution_pr':EXECUTION_PR,'residual_retention_execution_head_sha':EXECUTION_HEAD,'residual_retention_run_id':RUN_ID,'residual_retention_artifact_id':ARTIFACT_ID,'residual_retention_artifact_digest':ARTIFACT_DIGEST,'residual_retention_ledger_sha256':LEDGER_SHA,'residual_retention_gate_pass':True,'retained_document_error_count':1362,'retained_unresolved_tie_count':1279,'raw_data_verdict':'FAIL_CLOSED','data_verdict':'FAIL_CLOSED_WITH_FORMALLY_RETAINED_RESIDUALS','status':'FORMAL_RUNTIME_V17_30_FULL_BASIS_V17_30_RESIDUALS_FORMALLY_RETAINED','final_gate':True,'final_requirement':'S3G4 and Stage3 historical final freeze remain pending. Stage4/Alpha/live stay locked.'})
 if EXECUTION_PR not in au.get('non_merge_evidence_prs',[]):au.setdefault('non_merge_evidence_prs',[]).append(EXECUTION_PR)
 au['current_s3g1j_execution_pr']=EXECUTION_PR;au['current_s3g1j_governance_pr']=a.governance_pr
 lg=lock['required_gates']['S3G1J_FINANCIAL_RAW_VALUES']
 lg.update({'residual_retention_evidence':'governance/stage3_s3g1j_v17_30_residual_retention.json','residual_retention_execution_pr':EXECUTION_PR,'residual_retention_run_id':RUN_ID,'residual_retention_artifact_id':ARTIFACT_ID,'residual_retention_artifact_digest':ARTIFACT_DIGEST,'residual_retention_ledger_sha256':LEDGER_SHA,'raw_data_verdict':'FAIL_CLOSED','data_verdict':'FAIL_CLOSED_WITH_FORMALLY_RETAINED_RESIDUALS','retained_document_error_count':1362,'retained_unresolved_tie_count':1279,'residual_retention_gate_pass':True,'final_gate_pass':True})
 lock['remaining_unlocked_gates']=['S3G4_EARNINGS_SURPRISE'];lock['interpretation']='V17.30 remains the formal and latest accepted raw full basis at 1,051,826 numeric / 1,362 raw document errors / 1,279 raw unresolved ties. Those residuals are now formally retained as missing/fail-closed and forbidden as numeric truth, so S3G1J final gate is closed. Stage3 remains NOT_READY pending S3G4 and final historical freeze.'
 st=project['stage3'];pg=st['s3g1j']
 st['completed_final_gates_on_clean_integration']=list(dict.fromkeys(st.get('completed_final_gates_on_clean_integration',[])+['S3G1J_FINANCIAL_RAW_VALUES']))
 st['pending_final_gates']=['S3G4_EARNINGS_SURPRISE']
 pg.update({'status':'RUNTIME_V17_30_FULL_BASIS_V17_30_RESIDUALS_FORMALLY_RETAINED','runtime_status':'RUNTIME_AND_FULL_BASIS_ACCEPTED_RESIDUALS_FORMALLY_RETAINED','residual_retention_evidence':'governance/stage3_s3g1j_v17_30_residual_retention.json','residual_retention_execution_pr':EXECUTION_PR,'residual_retention_run_id':RUN_ID,'residual_retention_artifact_id':ARTIFACT_ID,'residual_retention_artifact_digest':ARTIFACT_DIGEST,'residual_retention_ledger_sha256':LEDGER_SHA,'raw_data_verdict':'FAIL_CLOSED','data_verdict':'FAIL_CLOSED_WITH_FORMALLY_RETAINED_RESIDUALS','retained_document_error_count':1362,'retained_unresolved_tie_count':1279,'residual_retention_gate_pass':True,'final_gate_pass':True})
 st['reason']='S3G1J is now final-gate PASS by formal fail-closed retention of all 1,362 residual documents / 1,279 unresolved ties as missing and non-numeric. S3G4 and Stage3 historical final freeze remain pending; freshness is stale, so Stage4/Alpha/live remain locked.'
 rep=project.get('reproducibility') or {};rep['s3g1j_residual_retention_reproducible']=True;rep['s3g1j_residual_retention_run']=RUN_ID;rep['s3g1j_residual_retention_gate_pass']=True;rep['overall_pass']=False;rep['reason']='S3G1J runtime/full basis and formal residual retention are reproducible. S3G4 and final Stage3 freeze remain pending; current freshness remains stale.';project['reproducibility']=rep
 paths={'stage3_s3g1j_v17_30_residual_retention.json':manifest,'stage3_authority_map.json':au,'stage3_final_lock.json':lock,'project_status.json':project}
 hashes={}
 for name,obj in paths.items():p=out/name;dump(p,obj);hashes[name]=sha(p)
 (out/'output_sha256.json').write_text(json.dumps(hashes,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
 print(json.dumps({'pass':True,'governance_pr':a.governance_pr,'hashes':hashes},indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
