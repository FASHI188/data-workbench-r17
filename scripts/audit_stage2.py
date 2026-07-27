#!/usr/bin/env python3
"""Fail-closed Stage 2B hard-gate audit."""
from __future__ import annotations
import csv,json,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];CONFIG=ROOT/'config/stage2_hard_gates.json';MASTER_DIR=ROOT/'data/current_master'
def load_json(p:Path):return json.loads(p.read_text(encoding='utf-8'))

def audit_g1():
 errors=[];manifest_path=MASTER_DIR/'manifest.json';combined_path=MASTER_DIR/'cn_main_a.csv';reconciliation_path=MASTER_DIR/'reconciliation.json'
 if not manifest_path.exists():return False,['missing data/current_master/manifest.json']
 if not combined_path.exists():return False,['missing data/current_master/cn_main_a.csv']
 if not reconciliation_path.exists():return False,['missing independent data/current_master/reconciliation.json']
 manifest=load_json(manifest_path)
 if manifest.get('hard_gate_status')!='PASS_CANDIDATE':errors.append('current-master manifest is not PASS_CANDIDATE')
 rec=load_json(reconciliation_path)
 if rec.get('status')!='RECONCILED' or rec.get('g1_reconciled') is not True:errors.append('independent exchange-owned master reconciliation did not pass')
 for x in ('sse','szse'):
  s=rec.get(x,{})
  if s.get('set_equal') is not True:errors.append(f'{x.upper()} primary/control code sets differ')
  if s.get('primary_count')!=s.get('control_count'):errors.append(f'{x.upper()} primary/control counts differ')
  if not s.get('control_sha256'):errors.append(f'{x.upper()} control SHA-256 missing')
 rows=list(csv.DictReader(combined_path.open(encoding='utf-8')));seen=set()
 if not rows:return False,['current master has zero rows']
 for r in rows:
  k=(r.get('exchange',''),r.get('code',''))
  if k in seen:errors.append(f'duplicate security: {k[0]}:{k[1]}')
  seen.add(k)
  if r.get('exchange') not in {'SSE','SZSE'}:errors.append(f'invalid exchange: {r.get("exchange")}')
  if r.get('board')!='MAIN' or r.get('security_type')!='A_SHARE':errors.append(f'out-of-scope row: {k[0]}:{k[1]}')
  if r.get('exchange')=='SSE' and r.get('code','').startswith(('688','689')):errors.append(f'STAR contamination: {r.get("code")}')
  if r.get('exchange')=='SZSE' and r.get('code','').startswith(('300','301')):errors.append(f'ChiNext contamination: {r.get("code")}')
  if r.get('board_basis')=='DERIVED_CODE_PREFIX':errors.append(f'weak SZSE board evidence: {r.get("code")}')
 if sum(r.get('exchange')=='SSE' for r in rows)<1500:errors.append('implausibly small SSE main-A universe')
 if sum(r.get('exchange')=='SZSE' for r in rows)<1400:errors.append('implausibly small SZSE main-A universe')
 return not errors,errors

def audit_g2():
 script=ROOT/'scripts/audit_security_history.py'
 if not script.exists():return False,['missing scripts/audit_security_history.py'],{}
 p=subprocess.run([sys.executable,str(script)],cwd=ROOT,text=True,capture_output=True,check=False)
 try:r=json.loads(p.stdout)
 except json.JSONDecodeError:return False,[f'G2 audit invalid JSON; stderr={p.stderr.strip()[:1000]}'],{}
 e=list(r.get('errors') or [])
 if p.returncode!=0 and not e:e.append(f'G2 audit exited {p.returncode}: {p.stderr.strip()[:1000]}')
 return p.returncode==0 and r.get('pass') is True and not e,e,r

def audit_saved(gid,path,extra=None):
 if not path.exists():return False,[f'missing {path.relative_to(ROOT)}'],{}
 try:r=load_json(path)
 except Exception as exc:return False,[f'{gid} audit invalid JSON: {exc}'],{}
 e=list(r.get('errors') or [])
 if r.get('gate')!=gid:e.append(f'{gid} gate id mismatch')
 if r.get('pass') is not True:e.append(f'{gid} pass is not true')
 if extra:
  for msg,pred in extra:
   if not pred(r):e.append(msg)
 return not e,e,r

def main():
 cfg=load_json(CONFIG);results={}
 ok,e=audit_g1();results['G1']={'pass':ok,'errors':e}
 ok,e,r=audit_g2();results['G2']={'pass':ok,'errors':e,'details':r}
 ok,e,r=audit_saved('G3',ROOT/'data/ohlcv/g3_audit.json',[
  ('G3 total_rows unexpectedly small',lambda x:int(x.get('total_rows',0))>=8_000_000),
  ('G3 trading_days unexpectedly small',lambda x:int(x.get('trading_days',0))>=2800),
  ('G3 dataset fingerprint missing',lambda x:bool(x.get('dataset_fingerprint'))),
 ]);results['G3']={'pass':ok,'errors':e,'details':r}
 ok,e,r=audit_saved('G4',ROOT/'data/security_state/g4_audit.json',[
  ('G4 state row count unexpectedly small',lambda x:int(x.get('state_rows',0))>=8_000_000),
  ('G4 failed to explain 601268 suspension',lambda x:x.get('601268_all_suspended') is True),
 ]);results['G4']={'pass':ok,'errors':e,'details':r}
 ok,e,r=audit_saved('G5',ROOT/'data/corporate_actions/g5_audit.json',[
  ('G5 factor event count is zero',lambda x:int(x.get('factor_events',0))>0),
  ('G5 unmatched factor events remain',lambda x:int(x.get('unmatched_factor_event_count',-1))==0),
  ('G5 query errors remain',lambda x:int(x.get('query_error_count',-1))==0),
  ('G5 dataset fingerprint missing',lambda x:bool(x.get('dataset_fingerprint'))),
 ]);results['G5']={'pass':ok,'errors':e,'details':r}
 gate_cfg={x['id']:x['status'] for x in cfg.get('hard_gates',[])}
 for gid,v in results.items():
  if v['pass'] and gate_cfg.get(gid)!='PASS':v['pass']=False;v['errors'].append(f'{gid} evidence passes but config status is {gate_cfg.get(gid)!r}, not PASS')
 all_pass=all(v['pass'] for v in results.values());report={'stage':'2B','all_hard_gates_pass':all_pass,'alpha_training_allowed':all_pass,'results':results}
 print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if all_pass else 2
if __name__=='__main__':sys.exit(main())
