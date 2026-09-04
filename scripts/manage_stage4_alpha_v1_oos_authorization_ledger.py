#!/usr/bin/env python3
from __future__ import annotations

import argparse, base64, hashlib, json, os, sys, urllib.error, urllib.parse, urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEDGER_CONTRACT_FP='81840cb1ba16e9c14238117e66adb92fc3493b1824c1c6a78ec61d63f74de8bd'
AUTH_FP='d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d'
EXEC_FP='224d9144d1989f021c29bb17ce13a6d2644b2d8992d604738b4e596a6907d177'
LEDGER_ID='STAGE4_ALPHA_V1_OOS_AUTHORIZATION_LEDGER_V1'

def canonical_hash(obj:Any)->str:
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def sha256_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def utcnow()->str: return datetime.now(timezone.utc).isoformat()

def load_contract(path:Path)->dict[str,Any]:
    c=json.loads(path.read_text(encoding='utf-8'))
    if c.get('fingerprint')!=LEDGER_CONTRACT_FP or canonical_hash(c['fingerprint_basis'])!=LEDGER_CONTRACT_FP: raise ValueError('ledger contract fingerprint mismatch')
    if c.get('status')!='FROZEN_PRE_ACCESS_DURABLE_SINGLE_USE_LEDGER_V1_NO_OOS_ACCESS': raise ValueError('unexpected ledger contract status')
    b=c['fingerprint_basis']
    if b['ledger_id']!=LEDGER_ID or b['oos_authorization_fingerprint']!=AUTH_FP or b['oos_execution_contract_fingerprint']!=EXEC_FP: raise ValueError('ledger contract authority mismatch')
    sm=b['state_machine']; cas=b['cas_semantics']; fin=b['consumption_finalization']
    required=[sm.get('reservation_is_not_authorization_consumption') is True,sm.get('reserved_or_consumed_blocks_new_reservation') is True,sm.get('automatic_release_from_reserved_forbidden') is True,sm.get('reserved_recovery_requires_separate_governance_acknowledgement_and_independent_zero_access_proof') is True,cas.get('existing_blob_sha_required_for_every_mutation') is True,cas.get('concurrent_stale_writer_must_fail_closed') is True,cas.get('force_update_forbidden') is True,fin.get('finalize_step_runs_after_execution_attempt_even_on_failure') is True,fin.get('missing_marker_after_reservation')=='LEAVE_RESERVED_FAIL_CLOSED_NO_AUTORELEASE']
    if not all(required): raise ValueError('ledger fail-closed semantics drift')
    return c

def validate_ledger(ledger:dict[str,Any],contract:dict[str,Any])->None:
    b=contract['fingerprint_basis']
    if ledger.get('schema_version')!=1 or ledger.get('ledger_id')!=LEDGER_ID: raise ValueError('ledger identity mismatch')
    if ledger.get('ledger_contract_fingerprint')!=LEDGER_CONTRACT_FP or ledger.get('authorization_fingerprint')!=AUTH_FP or ledger.get('execution_contract_fingerprint')!=EXEC_FP: raise ValueError('ledger authority fingerprint mismatch')
    if ledger.get('ledger_branch')!=b['ledger_branch'] or ledger.get('ledger_path')!=b['ledger_path']: raise ValueError('ledger location mismatch')
    if ledger.get('status') not in {'UNCONSUMED','RESERVED','CONSUMED'}: raise ValueError('invalid ledger status')
    if not isinstance(ledger.get('history'),list): raise ValueError('ledger history missing')

def reserve_state(ledger:dict[str,Any],run_id:int,execution_head:str,now:str)->dict[str,Any]:
    if ledger.get('status')!='UNCONSUMED': raise ValueError(f"single-use authorization unavailable: ledger status={ledger.get('status')}")
    x=deepcopy(ledger); x['status']='RESERVED'; x['reservation']={'run_id':run_id,'execution_head':execution_head,'authorization_fingerprint':AUTH_FP,'reserved_at_utc':now}; x['consumption']=None; x['history'].append({'transition':'UNCONSUMED_TO_RESERVED','run_id':run_id,'execution_head':execution_head,'at_utc':now}); return x

def finalize_state(ledger:dict[str,Any],marker:dict[str,Any],run_id:int,execution_head:str,marker_sha:str,now:str)->dict[str,Any]:
    if ledger.get('status')!='RESERVED': raise ValueError(f"ledger not RESERVED: {ledger.get('status')}")
    r=ledger.get('reservation') or {}
    if int(r.get('run_id',-1))!=run_id or r.get('execution_head')!=execution_head: raise ValueError('reservation owned by different run/head')
    if marker.get('status')!='CONSUMED' or marker.get('authorization_fingerprint')!=AUTH_FP or marker.get('execution_contract_fingerprint')!=EXEC_FP: raise ValueError('consumption marker authority mismatch')
    if marker.get('execution_head')!=execution_head or marker.get('consumption_event')!='FIRST_OOS_PREDICTION_COMPUTATION': raise ValueError('consumption marker event/head mismatch')
    if marker.get('oos_label_read_before_consumption') is not False or marker.get('lockbox_accessed') is not False or marker.get('fit_executed') is not False: raise ValueError('consumption marker hard-boundary mismatch')
    x=deepcopy(ledger); x['status']='CONSUMED'; x['consumption']={'run_id':run_id,'execution_head':execution_head,'authorization_fingerprint':AUTH_FP,'consumption_event':marker['consumption_event'],'consumed_at_utc':marker.get('consumed_at_utc'),'marker_sha256':marker_sha,'finalized_at_utc':now}; x['history'].append({'transition':'RESERVED_TO_CONSUMED','run_id':run_id,'execution_head':execution_head,'at_utc':now,'marker_sha256':marker_sha}); return x

def synthetic()->int:
    ledger={'schema_version':1,'ledger_id':LEDGER_ID,'ledger_contract_fingerprint':LEDGER_CONTRACT_FP,'authorization_fingerprint':AUTH_FP,'execution_contract_fingerprint':EXEC_FP,'ledger_branch':'b','ledger_path':'p','status':'UNCONSUMED','reservation':None,'consumption':None,'history':[]}
    r=reserve_state(ledger,101,'a'*40,'2026-01-01T00:00:00+00:00'); assert r['status']=='RESERVED' and ledger['status']=='UNCONSUMED'
    try: reserve_state(r,102,'b'*40,'2026-01-01T00:00:01+00:00'); raise AssertionError('second reservation unexpectedly allowed')
    except ValueError: pass
    marker={'status':'CONSUMED','authorization_fingerprint':AUTH_FP,'execution_contract_fingerprint':EXEC_FP,'execution_head':'a'*40,'consumption_event':'FIRST_OOS_PREDICTION_COMPUTATION','consumed_at_utc':'2026-01-01T00:01:00+00:00','oos_label_read_before_consumption':False,'lockbox_accessed':False,'fit_executed':False}
    c=finalize_state(r,marker,101,'a'*40,'f'*64,'2026-01-01T00:02:00+00:00'); assert c['status']=='CONSUMED'
    try: reserve_state(c,103,'c'*40,'2026-01-01T00:03:00+00:00'); raise AssertionError('reservation after consumption unexpectedly allowed')
    except ValueError: pass
    print(json.dumps({'ledger_synthetic_self_test':'PASS','cas_required':True,'automatic_release':False,'second_reservation_blocked':True,'consumed_terminal':True})); return 0

def api(repo:str,token:str,method:str,path:str,payload:dict[str,Any]|None=None)->dict[str,Any]:
    url='https://api.github.com/repos/'+repo+'/'+path; data=None if payload is None else json.dumps(payload,separators=(',',':')).encode()
    req=urllib.request.Request(url,data=data,method=method,headers={'Accept':'application/vnd.github+json','Authorization':'Bearer '+token,'X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json','User-Agent':'stage4-oos-ledger-v1'})
    try:
        with urllib.request.urlopen(req,timeout=30) as resp:
            body=resp.read(); return {} if not body else json.loads(body.decode())
    except urllib.error.HTTPError as e:
        body=e.read().decode(errors='replace'); raise RuntimeError(f'GitHub API {method} {path} failed status={e.code} body={body[:1000]}') from e

def fetch_remote(contract:dict[str,Any],repo:str,token:str)->tuple[dict[str,Any],str]:
    b=contract['fingerprint_basis']; branch=urllib.parse.quote(b['ledger_branch'],safe=''); path=urllib.parse.quote(b['ledger_path'],safe='/'); obj=api(repo,token,'GET',f'contents/{path}?ref={branch}'); raw=base64.b64decode(obj['content']).decode('utf-8'); ledger=json.loads(raw); validate_ledger(ledger,contract); return ledger,obj['sha']

def put_remote(contract:dict[str,Any],repo:str,token:str,ledger:dict[str,Any],existing_sha:str,message:str)->dict[str,Any]:
    b=contract['fingerprint_basis']; path=urllib.parse.quote(b['ledger_path'],safe='/'); content=base64.b64encode((json.dumps(ledger,ensure_ascii=False,indent=2)+'\n').encode()).decode(); return api(repo,token,'PUT',f'contents/{path}',{'message':message,'content':content,'sha':existing_sha,'branch':b['ledger_branch']})

def runtime_context()->tuple[str,str,int]:
    token=os.environ.get('GH_TOKEN',''); repo=os.environ.get('GITHUB_REPOSITORY',''); rid=os.environ.get('GITHUB_RUN_ID','')
    if not token or not repo or not rid.isdigit(): raise ValueError('missing GH_TOKEN/GITHUB_REPOSITORY/GITHUB_RUN_ID')
    return repo,token,int(rid)

def main()->int:
    if '--synthetic-self-test' in sys.argv: return synthetic()
    ap=argparse.ArgumentParser(); ap.add_argument('--contract',required=True); ap.add_argument('--mode',required=True,choices=['reserve','verify-reserved','finalize','verify-consumed']); ap.add_argument('--execution-head',required=True); ap.add_argument('--consumption-marker'); a=ap.parse_args()
    if len(a.execution_head)!=40 or any(c not in '0123456789abcdef' for c in a.execution_head): raise ValueError('invalid exact execution head')
    contract=load_contract(Path(a.contract)); repo,token,run_id=runtime_context(); ledger,blob_sha=fetch_remote(contract,repo,token); now=utcnow()
    if a.mode=='reserve':
        nxt=reserve_state(ledger,run_id,a.execution_head,now); res=put_remote(contract,repo,token,nxt,blob_sha,f'stage4: reserve single-use OOS authorization for run {run_id}'); print(json.dumps({'status':'RESERVED','run_id':run_id,'execution_head':a.execution_head,'previous_blob_sha':blob_sha,'new_blob_sha':res.get('content',{}).get('sha'),'commit_sha':res.get('commit',{}).get('sha'),'authorization_consumed':False},indent=2)); return 0
    if a.mode=='verify-reserved':
        if ledger.get('status')!='RESERVED': raise ValueError('ledger not reserved')
        r=ledger.get('reservation') or {}
        if int(r.get('run_id',-1))!=run_id or r.get('execution_head')!=a.execution_head: raise ValueError('ledger reservation not owned by current run/head')
        print(json.dumps({'status':'RESERVED_VERIFIED','run_id':run_id,'execution_head':a.execution_head,'authorization_consumed':False})); return 0
    if a.mode=='finalize':
        p=Path(a.consumption_marker or '')
        if not p.is_file(): raise RuntimeError('consumption marker missing after reservation; ledger intentionally remains RESERVED fail-closed and requires separate governance recovery')
        marker=json.loads(p.read_text(encoding='utf-8')); msh=sha256_file(p); nxt=finalize_state(ledger,marker,run_id,a.execution_head,msh,now); res=put_remote(contract,repo,token,nxt,blob_sha,f'stage4: consume single-use OOS authorization for run {run_id}'); print(json.dumps({'status':'CONSUMED','run_id':run_id,'execution_head':a.execution_head,'marker_sha256':msh,'previous_blob_sha':blob_sha,'new_blob_sha':res.get('content',{}).get('sha'),'commit_sha':res.get('commit',{}).get('sha')},indent=2)); return 0
    if ledger.get('status')!='CONSUMED': raise ValueError('ledger not consumed')
    x=ledger.get('consumption') or {}
    if int(x.get('run_id',-1))!=run_id or x.get('execution_head')!=a.execution_head or x.get('consumption_event')!='FIRST_OOS_PREDICTION_COMPUTATION': raise ValueError('ledger consumption not bound to current run/head')
    print(json.dumps({'status':'CONSUMED_VERIFIED','run_id':run_id,'execution_head':a.execution_head,'marker_sha256':x.get('marker_sha256')})); return 0

if __name__=='__main__': raise SystemExit(main())
