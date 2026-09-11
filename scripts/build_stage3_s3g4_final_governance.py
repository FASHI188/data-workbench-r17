#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SOURCE_PR=131
SOURCE_HEAD='8422f1ce24a19c80560ee9a626b14a7eb9b2a5be'
SOURCE_RUN=31557145693
ACCEPTANCE_PR=132
ACCEPTANCE_HEAD='fe722f82f599489f4fcf86cefc47afe1c9235b64'
ACCEPTANCE_RUN=31557811596
ARTIFACT_ID=9126607328
ARTIFACT_NAME='stage3-s3g4-earnings-surprise-final-acceptance'
ARTIFACT_DIGEST='sha256:b87e822278f044f8fd6dd5a8cf7bb2e342890b27086951d377d73ed70c7bd4b3'
AUDIT_SHA='f3ab63e8e0fbb122f04bd1f9f2cde8a9c4ea9c66ab5ef1aa5d91eba9936f44c8'
FORECAST_LEDGER_SHA='6912b2297b01c97a91b764e96d4d586982517ec68b20e25a24606cdc67ff74d6'
SURPRISE_LEDGER_SHA='8c12874918139b159235f03e7071a1942f1d0888b4603a16c9858634bf65e072'
EXCLUSIONS=['1207046114','1208263921','1220457006','1221055839']


def load(p:str)->dict:return json.loads(Path(p).read_text(encoding='utf-8'))
def dump(p:Path,x:dict)->None:p.write_text(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--authority',required=True);ap.add_argument('--lock',required=True);ap.add_argument('--project',required=True)
    ap.add_argument('--audit',required=True);ap.add_argument('--governance-pr',required=True,type=int);ap.add_argument('--out',required=True)
    a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    authority=load(a.authority);lock=load(a.lock);project=load(a.project);audit=load(a.audit);errors=[]
    def req(ok,msg):
        if not ok:errors.append(msg)
    req(audit.get('pass') is True and audit.get('errors')==[],'S3G4 audit not PASS')
    req(audit.get('source_shard_run_id')==SOURCE_RUN and audit.get('source_shard_head_sha')==SOURCE_HEAD,'source shard identity drift')
    req(audit.get('shard_count')==64 and audit.get('forecast_population')==51732,'forecast population drift')
    req(audit.get('source_pdf_fetch_completeness')==1.0,'source PDF completeness drift')
    req(audit.get('forecast_parser_status_counts')=={'FOUND':33679,'FOUND_POINT_ESTIMATE':3880,'NOT_FOUND':14173},'parser status taxonomy drift')
    req(audit.get('numeric_forecast_versions')==33688 and audit.get('numeric_forecast_org_count')==3109,'numeric forecast count drift')
    req(audit.get('financial_parent_net_profit_observations_total')==118505,'actual population drift')
    req(audit.get('financial_actuals_excluded_missing_formal_pit_identity')==4,'actual PIT exclusion count drift')
    req(sorted(x['announcement_id'] for x in audit.get('financial_actual_pit_exclusions',[]))==EXCLUSIONS,'actual PIT exclusion identity drift')
    req(audit.get('financial_actual_observations_eligible')==118501,'eligible actual count drift')
    req(audit.get('surprise_observations')==29139,'surprise count drift')
    req(audit.get('actuals_without_prior_numeric_forecast')==89362,'no-prior count drift')
    req(audit.get('forecast_parse_ledger_sha256')==FORECAST_LEDGER_SHA,'forecast ledger SHA drift')
    req(audit.get('surprise_ledger_sha256')==SURPRISE_LEDGER_SHA,'surprise ledger SHA drift')
    req(audit.get('identity_match_mode')=='EXACT_ISSUER_ORG_ID_AND_ECONOMIC_DATE','identity mode drift')
    req(audit.get('expectation_is_strictly_prior') is True,'PIT prior contract drift')
    req(audit.get('expectation_source')=='OFFICIAL_COMPANY_EARNINGS_FORECAST_PDF','expectation source drift')
    req(audit.get('actual_source')=='ORIGINAL_PERIODIC_FILING_PDF','actual source drift')
    req(audit.get('analyst_consensus_used') is False,'analyst consensus used')
    req(audit.get('missing_actual_pit_policy')=='FAIL_CLOSED_EXCLUDE_FROM_S3G4; DO_NOT_INFER_AVAILABLE_AT_OR_EFFECTIVE_CODE','missing PIT policy drift')
    req(audit.get('stage4_unlocked') is False and audit.get('alpha_training_allowed') is False and audit.get('live_signal_allowed') is False,'downstream unlocked in S3G4 audit')
    req(len(audit.get('shard_evidence',[]))==64,'shard evidence cardinality drift')
    if errors: raise SystemExit('; '.join(errors))

    manifest={
      'schema_version':1,'gate':'S3G4_EARNINGS_SURPRISE_FINAL_GOVERNANCE','status':'MACHINE_ACCEPTED_FINAL_EVIDENCE_REGISTERED','governance_pr':a.governance_pr,
      'source_execution':{'pr':SOURCE_PR,'head_sha':SOURCE_HEAD,'run_id':SOURCE_RUN,'closed_without_merge_required':True,'source_run_overall_conclusion':'failure','prepare_success':True,'all_64_shards_success':True,'obsolete_finalizer_failed':True},
      'acceptance_execution':{'pr':ACCEPTANCE_PR,'head_sha':ACCEPTANCE_HEAD,'run_id':ACCEPTANCE_RUN,'closed_without_merge_required':True,'conclusion':'success','artifact_id':ARTIFACT_ID,'artifact_name':ARTIFACT_NAME,'artifact_digest':ARTIFACT_DIGEST,'audit_sha256':AUDIT_SHA,'forecast_parse_ledger_sha256':FORECAST_LEDGER_SHA,'surprise_ledger_sha256':SURPRISE_LEDGER_SHA},
      'final_result':{
        'forecast_population':51732,'source_pdf_fetch_completeness':1.0,'forecast_parser_status_counts':audit['forecast_parser_status_counts'],'numeric_forecast_versions':33688,'numeric_forecast_org_count':3109,
        'financial_parent_net_profit_observations_total':118505,'financial_actuals_excluded_missing_formal_pit_identity':4,'financial_actual_pit_exclusion_ids':EXCLUSIONS,'financial_actual_observations_eligible':118501,
        'surprise_observations':29139,'actuals_without_prior_numeric_forecast':89362,'identity_match_mode':'EXACT_ISSUER_ORG_ID_AND_ECONOMIC_DATE','expectation_is_strictly_prior':True,
        'expectation_source':'OFFICIAL_COMPANY_EARNINGS_FORECAST_PDF','actual_source':'ORIGINAL_PERIODIC_FILING_PDF','analyst_consensus_used':False,
        'missing_actual_pit_policy':'FAIL_CLOSED_EXCLUDE_FROM_S3G4; DO_NOT_INFER_AVAILABLE_AT_OR_EFFECTIVE_CODE','methodology_version':audit['methodology_version'],
      },
      'hard_boundaries':{'OCR_allowed':False,'fuzzy_alias_allowed':False,'title_derived_numeric_values_allowed':False,'E_equals_A_minus_L_inference_allowed':False,'issuer_or_security_identity_relaxation_allowed':False,'PIT_relaxation_allowed':False,'accounting_tolerance_relaxation_allowed':False,'stage4_unlocked':False,'alpha_training_allowed':False,'live_signal_allowed':False,'main_changed':False},
      'interpretation':'S3G4 final component gate is accepted from official company forecast PDFs with exact issuer/economic-date identity and strict prior availability. NOT_FOUND forecasts stay nonnumeric; four actuals missing formal PIT/effective-code identity are fail-closed excluded without inference. Stage3 historical final freeze remains pending and downstream remains locked.'
    }

    authority['schema_version']=9
    g=authority['authoritative_components']['S3G4_EARNINGS_SURPRISE']
    g.clear();g.update({
      'evidence_manifest':'governance/stage3_s3g4_final.json','source_execution_pr':SOURCE_PR,'source_execution_head_sha':SOURCE_HEAD,'source_execution_run_id':SOURCE_RUN,'source_execution_closed_without_merge':True,
      'acceptance_pr':ACCEPTANCE_PR,'acceptance_head_sha':ACCEPTANCE_HEAD,'accepted_run_id':ACCEPTANCE_RUN,'accepted_artifact_id':ARTIFACT_ID,'accepted_artifact':ARTIFACT_NAME,'accepted_artifact_digest':ARTIFACT_DIGEST,
      'audit_sha256':AUDIT_SHA,'forecast_parse_ledger_sha256':FORECAST_LEDGER_SHA,'surprise_ledger_sha256':SURPRISE_LEDGER_SHA,'forecast_population':51732,'source_pdf_fetch_completeness':1.0,
      'numeric_forecast_versions':33688,'financial_actual_observations_eligible':118501,'surprise_observations':29139,'actual_pit_exclusion_count':4,'actual_pit_exclusion_ids':EXCLUSIONS,
      'identity_match_mode':'EXACT_ISSUER_ORG_ID_AND_ECONOMIC_DATE','expectation_is_strictly_prior':True,'analyst_consensus_used':False,'status':'FINAL_GATE_PASS_OFFICIAL_GUIDANCE_EXACT_PIT','final_gate':True,
      'final_requirement':'Stage3 historical semantic freeze remains pending. Stage4/Alpha/live stay locked.'
    })
    for pr in [SOURCE_PR,ACCEPTANCE_PR]:
        if pr not in authority.setdefault('non_merge_evidence_prs',[]):authority['non_merge_evidence_prs'].append(pr)
    authority['current_s3g4_source_pr']=SOURCE_PR;authority['current_s3g4_acceptance_pr']=ACCEPTANCE_PR;authority['current_s3g4_governance_pr']=a.governance_pr
    authority['status']='ALL_COMPONENT_GATES_PASS_FINAL_FREEZE_PENDING'
    authority['project_unlock']={'stage4_unlocked':False,'alpha_training_allowed':False,'live_signal_allowed':False}

    lock['version']='V3.3.16-stage3-component-gates-complete'
    lock['status']='NOT_READY'
    lock['required_gates']['S3G4_EARNINGS_SURPRISE']={
      'evidence':'governance/stage3_s3g4_final.json','source_execution_pr':SOURCE_PR,'source_execution_run_id':SOURCE_RUN,'acceptance_pr':ACCEPTANCE_PR,'run_id':ACCEPTANCE_RUN,
      'head_sha':ACCEPTANCE_HEAD,'artifact_id':ARTIFACT_ID,'artifact':ARTIFACT_NAME,'artifact_digest':ARTIFACT_DIGEST,'audit_sha256':AUDIT_SHA,'forecast_parse_ledger_sha256':FORECAST_LEDGER_SHA,'surprise_ledger_sha256':SURPRISE_LEDGER_SHA,
      'forecast_population':51732,'source_pdf_fetch_completeness':1.0,'financial_actual_observations_eligible':118501,'surprise_observations':29139,'actual_pit_exclusion_count':4,
      'expectation_is_strictly_prior':True,'analyst_consensus_used':False,'final_gate_pass':True
    }
    lock['remaining_unlocked_gates']=[]
    lock['interpretation']='All Stage3 component gates are now machine-accepted. Stage3 remains NOT_READY only until the separate historical semantic final freeze is generated and reproduced. Freshness remains independently stale; Stage4/Alpha/live remain locked.'

    stage3=project['stage3']
    completed=list(stage3.get('completed_final_gates_on_clean_integration',[]))
    if 'S3G4_EARNINGS_SURPRISE' not in completed:completed.append('S3G4_EARNINGS_SURPRISE')
    stage3['completed_final_gates_on_clean_integration']=completed
    stage3['pending_final_gates']=[]
    stage3['status']='NOT_READY'
    stage3['s3g4']={
      'status':'FINAL_GATE_PASS_OFFICIAL_GUIDANCE_EXACT_PIT','evidence':'governance/stage3_s3g4_final.json','source_execution_pr':SOURCE_PR,'source_execution_run_id':SOURCE_RUN,'acceptance_pr':ACCEPTANCE_PR,'accepted_run_id':ACCEPTANCE_RUN,'accepted_head_sha':ACCEPTANCE_HEAD,
      'accepted_artifact_id':ARTIFACT_ID,'accepted_artifact_digest':ARTIFACT_DIGEST,'audit_sha256':AUDIT_SHA,'forecast_parse_ledger_sha256':FORECAST_LEDGER_SHA,'surprise_ledger_sha256':SURPRISE_LEDGER_SHA,
      'forecast_population':51732,'source_pdf_fetch_completeness':1.0,'numeric_forecast_versions':33688,'financial_parent_net_profit_observations_total':118505,'financial_actuals_excluded_missing_formal_pit_identity':4,
      'financial_actual_observations_eligible':118501,'surprise_observations':29139,'actuals_without_prior_numeric_forecast':89362,'identity_match_mode':'EXACT_ISSUER_ORG_ID_AND_ECONOMIC_DATE','expectation_is_strictly_prior':True,'analyst_consensus_used':False,'final_gate_pass':True
    }
    stage3['reason']='All Stage3 component gates are machine-accepted: S3G1J is closed by formal fail-closed residual retention and S3G4 is final-gate PASS from official company guidance with exact PIT. The separate Stage3 historical semantic final freeze is still pending, so Stage3 remains NOT_READY and downstream stays locked.'
    rep=project.get('reproducibility') or {};rep.update({'s3g4_source_64_shards_reproducible':True,'s3g4_acceptance_run':ACCEPTANCE_RUN,'s3g4_final_gate_pass':True,'s3g4_forecast_parse_ledger_sha256':FORECAST_LEDGER_SHA,'s3g4_surprise_ledger_sha256':SURPRISE_LEDGER_SHA,'overall_pass':False,'reason':'All Stage3 component gates are reproducible. Historical semantic final freeze remains pending; freshness remains stale and downstream stays locked.'});project['reproducibility']=rep
    project['stage4_unlocked']=False;project['alpha_training_allowed']=False;project['live_signal_allowed']=False
    project['unlock_requirements']['stage3_final_pass']=False;project['unlock_requirements']['freshness_pass']=False;project['unlock_requirements']['reproducibility_pass']=False

    outputs={'stage3_s3g4_final.json':manifest,'stage3_authority_map.json':authority,'stage3_final_lock.json':lock,'project_status.json':project}
    hashes={}
    for name,obj in outputs.items():
        p=out/name;dump(p,obj);hashes[name]=sha(p)
    (out/'output_sha256.json').write_text(json.dumps(hashes,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
    print(json.dumps({'pass':True,'governance_pr':a.governance_pr,'hashes':hashes},indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
