#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

VERSION='V3.3.17-stage3-historical-final-freeze'
STAGE2_FP='f17f7ab63f4532dda635eb7366e7df7bf5497a5ce814410105312bccb53125bb'
EXPECTED_GATES={
 'S3G0_POINT_IN_TIME_FEATURE_CONTRACT','S3G1E_PERIODIC_FILING_LEDGER','S3G1G_REPORT_VERSION_SELECTION','S3G1I_POPULATION_PDF_PROBE',
 'S3G1J_FINANCIAL_RAW_VALUES','S3G2_ANNOUNCEMENT_LEDGER','S3G3A_INDUSTRY_SOURCE_PROBE','S3G3B_INDUSTRY_LEDGER','S3G4A_FORECAST_PARSER_PROBE','S3G4_EARNINGS_SURPRISE','S3GU_TRADING_UNIVERSE_POLICY'
}


def load(p:str)->dict:return json.loads(Path(p).read_text(encoding='utf-8'))
def sha_file(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def canonical(x:object)->bytes:return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
def dump(p:Path,x:dict)->None:p.write_text(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')


def main()->int:
 ap=argparse.ArgumentParser()
 for name in ['authority','lock','project','stage2_manifest','universe_policy','s3g1j_full','s3g1j_retention','s3g4_final']:
  ap.add_argument('--'+name.replace('_','-'),required=True,dest=name)
 ap.add_argument('--governance-pr',required=True,type=int);ap.add_argument('--out',required=True)
 a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 authority=load(a.authority);lock=load(a.lock);project=load(a.project);stage2=load(a.stage2_manifest);policy=load(a.universe_policy);full=load(a.s3g1j_full);ret=load(a.s3g1j_retention);s3g4=load(a.s3g4_final);errors=[]
 def req(ok,msg):
  if not ok:errors.append(msg)

 req(stage2.get('version')=='V3.2.25-stage2-final-freeze','Stage2 version drift')
 req(stage2.get('stage2_dataset_fingerprint')==STAGE2_FP,'Stage2 fingerprint drift')
 req(stage2.get('all_hard_gates_pass') is True,'Stage2 not PASS')
 req(authority.get('schema_version')==9 and authority.get('status')=='ALL_COMPONENT_GATES_PASS_FINAL_FREEZE_PENDING','authority prefreeze state drift')
 req(authority.get('project_unlock')=={'stage4_unlocked':False,'alpha_training_allowed':False,'live_signal_allowed':False},'authority downstream unlock drift')
 comps=authority.get('authoritative_components') or {}
 req(set(comps)==EXPECTED_GATES,'authority component gate set drift')
 for gate in EXPECTED_GATES:req((comps.get(gate) or {}).get('final_gate') is True,f'{gate} final_gate not true')

 g1j=comps.get('S3G1J_FINANCIAL_RAW_VALUES') or {}
 req(g1j.get('formal_runtime_generation')=='V17.30','S3G1J runtime drift')
 req(g1j.get('accepted_run_id')==31518370789 and g1j.get('accepted_artifact_id')==9112098872,'S3G1J accepted basis identity drift')
 req(g1j.get('document_count')==121354 and g1j.get('numeric_observation_count')==1051826,'S3G1J basis count drift')
 req(g1j.get('document_error_count')==1362 and g1j.get('unresolved_tie_count')==1279,'S3G1J raw residual facts drift')
 req(g1j.get('raw_data_verdict')=='FAIL_CLOSED','S3G1J raw verdict drift')
 req(g1j.get('residual_retention_gate_pass') is True and g1j.get('residual_retention_run_id')==31555404674,'S3G1J retention authority drift')
 req(g1j.get('retained_document_error_count')==1362 and g1j.get('retained_unresolved_tie_count')==1279,'S3G1J retained residual count drift')
 req(full.get('accepted_run',{}).get('run_id')==31518370789,'S3G1J full evidence run drift')
 req(full.get('full_basis_result',{}).get('document_error_count')==1362 and full.get('full_basis_result',{}).get('unresolved_tie_count')==1279,'S3G1J full raw facts drift')
 req(full.get('full_basis_result',{}).get('final_data_verdict')=='FAIL_CLOSED','S3G1J full raw verdict drift')
 req(ret.get('accepted_run',{}).get('run_id')==31555404674,'S3G1J retention run drift')
 req(ret.get('retention_result',{}).get('retained_document_count')==1362 and ret.get('retention_result',{}).get('retained_unresolved_tie_count')==1279,'retention count drift')
 req(ret.get('retention_result',{}).get('raw_errors_removed') is False and ret.get('retention_result',{}).get('raw_ties_removed') is False,'retention falsely removes raw errors')
 req(ret.get('retention_result',{}).get('retained_rows_usable_as_numeric_truth') is False,'retained rows became numeric truth')
 req(ret.get('retention_result',{}).get('retained_rows_must_be_excluded_from_numeric_feature_values') is True,'retained rows not excluded')

 g4=comps.get('S3G4_EARNINGS_SURPRISE') or {}
 req(g4.get('accepted_run_id')==31557811596 and g4.get('accepted_artifact_id')==9126607328,'S3G4 accepted identity drift')
 req(g4.get('forecast_population')==51732 and g4.get('source_pdf_fetch_completeness')==1.0,'S3G4 source completeness drift')
 req(g4.get('surprise_observations')==29139 and g4.get('actual_pit_exclusion_count')==4,'S3G4 result count drift')
 req(g4.get('identity_match_mode')=='EXACT_ISSUER_ORG_ID_AND_ECONOMIC_DATE' and g4.get('expectation_is_strictly_prior') is True,'S3G4 PIT/identity drift')
 req(g4.get('analyst_consensus_used') is False,'S3G4 analyst consensus drift')
 req(s3g4.get('gate')=='S3G4_EARNINGS_SURPRISE_FINAL_GOVERNANCE','S3G4 governance gate drift')
 req(s3g4.get('acceptance_execution',{}).get('run_id')==31557811596,'S3G4 governance run drift')
 req(s3g4.get('final_result',{}).get('surprise_observations')==29139,'S3G4 governance result drift')

 req(lock.get('version')=='V3.3.16-stage3-component-gates-complete' and lock.get('status')=='NOT_READY','lock prefreeze state drift')
 req(lock.get('remaining_unlocked_gates')==[],'lock remaining component gate drift')
 req(set(lock.get('required_gates',{}))==EXPECTED_GATES|{'S3G1H_PDF_PARSER_PROBE'},'lock gate set drift')
 req(project.get('stage3',{}).get('status')=='NOT_READY','project prefreeze Stage3 drift')
 req(project.get('stage3',{}).get('pending_final_gates')==[],'project pending component gates nonempty')
 req(project.get('stage4_unlocked') is False and project.get('alpha_training_allowed') is False and project.get('live_signal_allowed') is False,'project downstream unlocked')
 freshness=project.get('freshness') or {}
 req(freshness.get('status')=='STALE','freshness must remain truthful STALE')

 scope=policy.get('scope_rule') or {};price=scope.get('price_rule') or {};excluded=set(scope.get('exclude_boards') or [])
 req(set(scope.get('include_boards') or [])=={'SSE_MAIN','SZSE_MAIN'},'universe include boards drift')
 req(price.get('operator')=='<' and float(price.get('threshold_cny',-1))==70.0 and price.get('exact_70_is_excluded') is True,'price policy drift')
 req({'STAR','CHINEXT','BSE','NEEQ'}.issubset(excluded),'excluded board policy drift')
 req((policy.get('anti_lookahead') or {}).get('never_filter_history_using_current_price') is True,'price PIT anti-lookahead drift')
 if errors:
  print(json.dumps({'pass':False,'errors':errors},ensure_ascii=False,indent=2));return 2

 semantic={
  'stage2':{'version':'V3.2.25-stage2-final-freeze','fingerprint':STAGE2_FP},
  'stage3_components':{
   'S3G0':{'run_id':comps['S3G0_POINT_IN_TIME_FEATURE_CONTRACT']['run_id']},
   'S3G1E':{'run_id':comps['S3G1E_PERIODIC_FILING_LEDGER']['run_id']},
   'S3G1G':{'run_id':comps['S3G1G_REPORT_VERSION_SELECTION']['run_id']},
   'S3G1I':{'run_id':comps['S3G1I_POPULATION_PDF_PROBE']['run_id'],'artifact_digest':comps['S3G1I_POPULATION_PDF_PROBE']['artifact_digest']},
   'S3G1J':{'runtime_generation':'V17.30','accepted_run_id':31518370789,'accepted_artifact_digest':g1j['accepted_artifact_digest'],'numeric_observation_count':1051826,'raw_document_error_count':1362,'raw_unresolved_tie_count':1279,'raw_data_verdict':'FAIL_CLOSED','existing_numeric_semantic_sha256':g1j['existing_numeric_semantic_sha256'],'target_numeric_semantic_sha256':g1j['target_numeric_semantic_sha256'],'residual_retention_run_id':31555404674,'residual_retention_artifact_digest':g1j['residual_retention_artifact_digest'],'residual_retention_ledger_sha256':g1j['residual_retention_ledger_sha256'],'retained_rows_numeric_truth':False},
   'S3G2':{'run_id':comps['S3G2_ANNOUNCEMENT_LEDGER']['deterministic_final_run_id'],'ledger_sha256':comps['S3G2_ANNOUNCEMENT_LEDGER']['ledger_sha256']},
   'S3G3A':{'run_id':comps['S3G3A_INDUSTRY_SOURCE_PROBE']['run_id'],'artifact_digest':comps['S3G3A_INDUSTRY_SOURCE_PROBE']['artifact_digest']},
   'S3G3B':{'run_id':comps['S3G3B_INDUSTRY_LEDGER']['run_id'],'ledger_sha256':comps['S3G3B_INDUSTRY_LEDGER']['ledger_sha256']},
   'S3G4A':{'run_id':comps['S3G4A_FORECAST_PARSER_PROBE']['run_id'],'artifact_digest':comps['S3G4A_FORECAST_PARSER_PROBE']['artifact_digest']},
   'S3G4':{'accepted_run_id':31557811596,'accepted_artifact_digest':g4['accepted_artifact_digest'],'forecast_parse_ledger_sha256':g4['forecast_parse_ledger_sha256'],'surprise_ledger_sha256':g4['surprise_ledger_sha256'],'forecast_population':51732,'surprise_observations':29139,'actual_pit_exclusion_count':4,'expectation_is_strictly_prior':True,'analyst_consensus_used':False},
   'S3GU':{'run_id':comps['S3GU_TRADING_UNIVERSE_POLICY']['run_id'],'artifact_digest':comps['S3GU_TRADING_UNIVERSE_POLICY']['artifact_digest']},
  },
  'trading_universe_policy_sha256':sha_file(Path(a.universe_policy)),
  'scope':'SSE_MAIN_A + SZSE_MAIN_A; candidate price strictly < CNY 70 point-in-time; STAR/CHINEXT/BSE/NEEQ excluded',
  'freshness_at_freeze':{'status':'STALE','current_master_as_of':freshness.get('current_master_as_of'),'policy':freshness.get('policy')},
  'downstream_at_freeze':{'stage4_unlocked':False,'alpha_training_allowed':False,'live_signal_allowed':False,'user_hold_before_stage4':True},
 }
 fingerprint=hashlib.sha256(canonical(semantic)).hexdigest()
 audit={
  'gate':'STAGE3_HISTORICAL_FINAL_FREEZE','pass':True,'version':VERSION,'stage2_fingerprint':STAGE2_FP,'stage3_dataset_fingerprint':fingerprint,
  'all_component_gates_pass':True,'historical_reproducibility_pass':True,'freshness_status':'STALE','freshness_pass_for_stage4':False,
  'stage4_unlocked':False,'alpha_training_allowed':False,'live_signal_allowed':False,'user_hold_before_stage4':True,
  's3g1j_raw_residuals_preserved':{'document_errors':1362,'unresolved_ties':1279,'raw_data_verdict':'FAIL_CLOSED','retention_gate_pass':True},
  's3g4_final':{'surprise_observations':29139,'forecast_population':51732,'actual_pit_exclusions':4,'strict_prior':True,'analyst_consensus_used':False},
  'fingerprint_basis':semantic,'errors':[]
 }
 manifest={
  'version':VERSION,'status':'PASS_FROZEN_HISTORICAL','all_stage3_component_gates_pass':True,'historical_reproducibility_pass':True,
  'stage2_dependency':{'version':'V3.2.25-stage2-final-freeze','fingerprint':STAGE2_FP},'stage3_dataset_fingerprint':fingerprint,
  'fingerprint_algorithm':'SHA-256 over canonical JSON fingerprint_basis','fingerprint_basis':semantic,
  'freshness':{'status':'STALE','eligible_for_stage4':False,'current_master_as_of':freshness.get('current_master_as_of'),'policy':freshness.get('policy')},
  'downstream':{'stage4_model_training_allowed':False,'stage4_unlocked':False,'alpha_training_allowed':False,'live_signal_allowed':False,'user_hold_before_stage4':True},
  'trading_universe':{'boards':['SSE_MAIN','SZSE_MAIN'],'price':'<70 CNY point-in-time','excluded':['STAR','CHINEXT','BSE','NEEQ']},
  's3g1j_retained_raw_residuals':{'document_error_count':1362,'unresolved_tie_count':1279,'raw_data_verdict':'FAIL_CLOSED','retained_as_missing':True,'usable_as_numeric_truth':False},
  's3g4':{'forecast_population':51732,'surprise_observations':29139,'actual_pit_exclusion_count':4,'expectation_is_strictly_prior':True,'analyst_consensus_used':False},
  'errors':[]
 }
 dump(out/'stage3_final_audit.json',audit);dump(out/'manifest.json',manifest)
 (out/'SHA256SUMS.txt').write_text(f"{sha_file(out/'manifest.json')}  manifest.json\n{sha_file(out/'stage3_final_audit.json')}  stage3_final_audit.json\n{fingerprint}  canonical:stage3-fingerprint-basis\n",encoding='utf-8')

 # Produce central final-state projection.
 authority['schema_version']=10;authority['status']='STAGE3_HISTORICAL_FINAL_FREEZE_PASS';authority['final_freeze']={'governance_pr':a.governance_pr,'version':VERSION,'manifest':'data/stage3_final/manifest.json','audit':'data/stage3_final/stage3_final_audit.json','stage3_dataset_fingerprint':fingerprint,'all_component_gates_pass':True,'historical_reproducibility_pass':True,'freshness_status':'STALE','stage4_unlocked':False,'user_hold_before_stage4':True};authority['project_unlock']={'stage4_unlocked':False,'alpha_training_allowed':False,'live_signal_allowed':False};authority['authoritative_components']['S3G1J_FINANCIAL_RAW_VALUES']['final_requirement']='Stage3 historical freeze complete; raw retained residual semantics remain in force.';authority['authoritative_components']['S3G4_EARNINGS_SURPRISE']['final_requirement']='Stage3 historical freeze complete; Stage4 remains locked by stale freshness and explicit user hold.'
 lock['version']=VERSION;lock['status']='PASS_FROZEN_HISTORICAL';lock['remaining_unlocked_gates']=[];lock['stage3_final_freeze']={'governance_pr':a.governance_pr,'manifest':'data/stage3_final/manifest.json','audit':'data/stage3_final/stage3_final_audit.json','stage3_dataset_fingerprint':fingerprint,'all_component_gates_pass':True,'historical_reproducibility_pass':True,'freshness_status':'STALE','stage4_unlocked':False,'alpha_training_allowed':False,'live_signal_allowed':False,'user_hold_before_stage4':True};lock['interpretation']='Stage3 historical semantic snapshot is fully frozen and reproducible. Raw S3G1J residuals remain formally retained as missing; S3G4 is accepted. Freshness is STALE, and user explicitly requested stopping before Stage4, so Stage4/Alpha/live remain locked.'
 stage3=project['stage3'];stage3['status']='PASS_FROZEN_HISTORICAL';stage3['final_manifest_present_on_integration']=True;stage3['final_manifest_present_on_main']=False;stage3['pending_final_gates']=[];stage3['historical_final_freeze']={'governance_pr':a.governance_pr,'version':VERSION,'manifest':'data/stage3_final/manifest.json','audit':'data/stage3_final/stage3_final_audit.json','stage3_dataset_fingerprint':fingerprint,'all_component_gates_pass':True,'historical_reproducibility_pass':True};stage3['reason']='Stage3 historical snapshot is complete and reproducibly frozen. S3G1J raw residuals remain explicitly retained fail-closed; S3G4 is final-gate PASS. Current freshness remains STALE and the user requested an explicit stop before Stage4.'
 project['freshness']['reason']='Stage3 historical freeze is complete, but the current frozen market/lifecycle/corporate-action master is older than the hard stale threshold. Freshness therefore remains STALE and blocks Stage4.'
 project['reproducibility']['status']='PASS_STAGE3_HISTORICAL_FREEZE';project['reproducibility']['overall_pass']=True;project['reproducibility']['stage3_final_fingerprint']=fingerprint;project['reproducibility']['reason']='Stage3 historical semantic fingerprint is reproducible across all accepted component evidence. This does not override stale freshness or unlock Stage4.'
 project['unlock_requirements']['stage3_final_pass']=True;project['unlock_requirements']['freshness_pass']=False;project['unlock_requirements']['reproducibility_pass']=True
 project['stage4_unlocked']=False;project['alpha_training_allowed']=False;project['live_signal_allowed']=False;project['user_hold_before_stage4']=True
 central={'stage3_authority_map.json':authority,'stage3_final_lock.json':lock,'project_status.json':project}
 for name,obj in central.items():dump(out/name,obj)
 hashes={p.name:sha_file(p) for p in sorted(out.iterdir()) if p.is_file()};dump(out/'output_sha256.json',hashes)
 print(json.dumps({'pass':True,'version':VERSION,'stage3_dataset_fingerprint':fingerprint,'hashes':hashes},ensure_ascii=False,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
