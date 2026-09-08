#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

RUN_HISTORY_FP='adf770ecb90759489b3c1a97325d06a616443b206bc91472dd05aa209240f628'
AUTH_FP='d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d'
EXEC_FP='224d9144d1989f021c29bb17ce13a6d2644b2d8992d604738b4e596a6907d177'
CORE_GIT_BLOB='19134bc8960b6c9c825ea2708aa1aac14ce914af'
CONTRACT_PATH=Path('governance/stage4_alpha_v1_oos_run_history_reservation_contract.json')
CORE_PATH=Path(__file__).with_name('run_stage4_alpha_v1_oos_validation_core.py')

# Static governance anchors intentionally retained in the public entrypoint.
ECONOMIC_SELECTION_SEMANTICS='ALL_PREDICTED_ROWS_ON_REBALANCE_DATE_BEFORE_ANY_LABEL_VALIDITY_FILTER'
LABEL_CENSORING_SEMANTICS='FAIL_CLOSED_NO_BACKFILL_NO_POST_SELECTION_DROP'
BROAD_SOURCE_GUARD='broad_source_inputs_available_in_execution_runner'


def canonical_hash(obj:Any)->str:
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def load_contract()->dict[str,Any]:
    c=json.loads(CONTRACT_PATH.read_text(encoding='utf-8'))
    if c.get('fingerprint')!=RUN_HISTORY_FP or canonical_hash(c['fingerprint_basis'])!=RUN_HISTORY_FP:
        raise ValueError('run-history reservation contract fingerprint mismatch')
    if c.get('status')!='FROZEN_PRE_ACCESS_RUN_HISTORY_RESERVATION_V1_NO_OOS_ACCESS':
        raise ValueError('unexpected run-history reservation contract status')
    b=c['fingerprint_basis']; r=b['reservation_semantics']; x=b['consumption_semantics']
    if b['oos_authorization_fingerprint']!=AUTH_FP or b['oos_execution_contract_fingerprint']!=EXEC_FP:
        raise ValueError('run-history authority mismatch')
    required=[
      r.get('ledger_source')=='IMMUTABLE_GITHUB_ACTIONS_WORKFLOW_RUN_HISTORY',
      r.get('earliest_non_exempt_dispatch_is_reservation_owner') is True,
      r.get('only_reservation_owner_may_proceed_to_oos_prediction') is True,
      r.get('current_run_attempt_must_equal')==1,
      r.get('current_run_head_sha_must_equal_execution_head') is True,
      r.get('later_dispatches_do_not_displace_owner_and_must_fail_closed') is True,
      r.get('reservation_persists_if_owner_fails_before_prediction') is True,
      r.get('automatic_release_forbidden') is True,
      r.get('recovery_requires_separate_governance_supersession_and_independent_zero_access_proof') is True,
      r.get('github_api_write_forbidden') is True,
      r.get('workflow_contents_write_forbidden') is True,
      x.get('authorization_consumed_at')=='FIRST_OOS_PREDICTION_COMPUTATION',
      x.get('run_history_reservation_is_not_authorization_consumption') is True,
      x.get('future_dispatch_after_owner_exists_must_fail_before_prediction') is True,
    ]
    if not all(required):
        raise ValueError('run-history fail-closed semantics drift')
    return c


def validate_core_blob()->None:
    if not CORE_PATH.is_file():
        raise ValueError('frozen OOS core missing')
    got=subprocess.check_output(['git','hash-object',str(CORE_PATH)],text=True).strip()
    if got!=CORE_GIT_BLOB:
        raise ValueError(f'frozen OOS core blob drift: {got}')


def classify_runs(runs:list[dict[str,Any]],contract:dict[str,Any],current_run_id:int,execution_head:str,current_attempt:int)->dict[str,Any]:
    b=contract['fingerprint_basis']; branch=b['execution_branch']; workflow_id=int(b['workflow_id'])
    relevant=[r for r in runs if r.get('event')=='workflow_dispatch' and r.get('head_branch')==branch and int(r.get('workflow_id',-1))==workflow_id]
    by_id={int(r['id']):r for r in relevant}
    exempt_ids=set()
    for e in b['zero_access_exemptions']:
        rid=int(e['run_id']); rr=by_id.get(rid)
        if rr is None:
            raise ValueError(f'frozen zero-access exemption missing from Actions history: {rid}')
        if rr.get('head_sha')!=e['head_sha'] or e.get('independent_zero_access_proof') is not True or e.get('oos_prediction_computed') is not False or e.get('oos_label_value_read') is not False or e.get('authorization_consumed') is not False:
            raise ValueError(f'zero-access exemption identity/evidence mismatch: {rid}')
        exempt_ids.add(rid)
    non_exempt=[r for r in relevant if int(r['id']) not in exempt_ids]
    non_exempt.sort(key=lambda r:(r.get('created_at') or '',int(r['id'])))
    if not non_exempt:
        raise ValueError('current durable reservation owner absent from Actions history')
    owner=non_exempt[0]
    if int(owner['id'])!=current_run_id:
        raise ValueError(f'single-use authorization already reserved by run {owner["id"]}; current={current_run_id}')
    if current_attempt!=1:
        raise ValueError(f'workflow rerun attempt forbidden for reservation owner: attempt={current_attempt}')
    if owner.get('head_sha')!=execution_head:
        raise ValueError(f'reservation owner head mismatch: history={owner.get("head_sha")} input={execution_head}')
    current=by_id.get(current_run_id)
    if current is None or current.get('head_sha')!=execution_head:
        raise ValueError('current workflow run identity mismatch')
    return {
      'status':'RESERVATION_OWNER_VERIFIED',
      'run_history_contract_fingerprint':RUN_HISTORY_FP,
      'reservation_owner_run_id':current_run_id,
      'reservation_owner_head_sha':execution_head,
      'current_run_attempt':current_attempt,
      'zero_access_exempt_run_ids':sorted(exempt_ids),
      'non_exempt_dispatch_run_ids':[int(r['id']) for r in non_exempt],
      'later_dispatches_observed':[int(r['id']) for r in non_exempt[1:]],
      'authorization_consumed_by_reservation':False,
      'github_api_write_used':False,
    }


def fetch_actions_history(contract:dict[str,Any])->list[dict[str,Any]]:
    b=contract['fingerprint_basis']; repo=b['repository']; workflow_id=int(b['workflow_id']); branch=b['execution_branch']
    headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'stage4-oos-run-history-v1'}
    token=os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token:
        headers['Authorization']='Bearer '+token
    out=[]; page=1
    while True:
        query=urllib.parse.urlencode({'event':'workflow_dispatch','branch':branch,'per_page':100,'page':page})
        url=f'https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/runs?{query}'
        req=urllib.request.Request(url,headers=headers,method='GET')
        with urllib.request.urlopen(req,timeout=30) as resp:
            payload=json.loads(resp.read().decode('utf-8'))
        batch=payload.get('workflow_runs') or []
        out.extend(batch)
        total=int(payload.get('total_count',len(out)))
        if len(out)>=total:
            break
        if not batch or page>=20:
            raise ValueError(f'Actions history pagination incomplete: got={len(out)} total={total}')
        page+=1
    return out


def live_reservation_gate(contract:dict[str,Any])->dict[str,Any]:
    b=contract['fingerprint_basis']
    repo=os.environ.get('GITHUB_REPOSITORY','')
    ref=os.environ.get('GITHUB_REF','')
    run_id=os.environ.get('GITHUB_RUN_ID','')
    attempt=os.environ.get('GITHUB_RUN_ATTEMPT','')
    execution_head=os.environ.get('EXECUTION_HEAD','')
    if repo!=b['repository'] or ref!='refs/heads/'+b['execution_branch']:
        raise ValueError('GitHub repository/ref mismatch for single-use OOS')
    if not run_id.isdigit() or not attempt.isdigit() or len(execution_head)!=40 or any(ch not in '0123456789abcdef' for ch in execution_head):
        raise ValueError('invalid GitHub run/execution-head context')
    rid=int(run_id); att=int(attempt)
    last=None
    for _ in range(8):
        try:
            runs=fetch_actions_history(contract)
            if any(int(r.get('id',-1))==rid for r in runs):
                result=classify_runs(runs,contract,rid,execution_head,att)
                print(json.dumps(result,sort_keys=True))
                return result
            last=ValueError('current run not yet visible in Actions history')
        except Exception as e:
            last=e
        time.sleep(2)
    raise ValueError(f'durable run-history reservation verification failed: {last}')


def synthetic_self_test(contract:dict[str,Any])->None:
    b=contract['fingerprint_basis']; wid=b['workflow_id']; branch=b['execution_branch']
    base=[]
    for e in b['zero_access_exemptions']:
        base.append({'id':e['run_id'],'workflow_id':wid,'event':'workflow_dispatch','head_branch':branch,'head_sha':e['head_sha'],'created_at':'2026-09-04T00:00:00Z'})
    owner={'id':9001,'workflow_id':wid,'event':'workflow_dispatch','head_branch':branch,'head_sha':'a'*40,'created_at':'2026-09-08T00:00:00Z'}
    later={'id':9002,'workflow_id':wid,'event':'workflow_dispatch','head_branch':branch,'head_sha':'b'*40,'created_at':'2026-09-08T00:01:00Z'}
    r=classify_runs(base+[owner],contract,9001,'a'*40,1)
    assert r['reservation_owner_run_id']==9001 and not r['later_dispatches_observed']
    r2=classify_runs(base+[owner,later],contract,9001,'a'*40,1)
    assert r2['later_dispatches_observed']==[9002]
    for args in [(base+[owner,later],9002,'b'*40,1),(base+[owner],9001,'a'*40,2)]:
        try:
            classify_runs(args[0],contract,args[1],args[2],args[3])
            raise AssertionError('fail-closed case unexpectedly allowed')
        except ValueError:
            pass
    print(json.dumps({'run_history_reservation_synthetic_self_test':'PASS','earliest_owner':True,'later_dispatch_blocked':True,'rerun_attempt_blocked':True,'api_write_used':False}))


def main()->int:
    contract=load_contract(); validate_core_blob()
    if '--synthetic-self-test' in sys.argv:
        synthetic_self_test(contract)
    else:
        live_reservation_gate(contract)
    os.execv(sys.executable,[sys.executable,str(CORE_PATH),*sys.argv[1:]])
    return 0


if __name__=='__main__':
    raise SystemExit(main())
