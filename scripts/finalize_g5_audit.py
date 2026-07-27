#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path

def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--official-audit',required=True);ap.add_argument('--adjustment-audit',required=True);ap.add_argument('--control-audit',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 off=load(a.official_audit);adj=load(a.adjustment_audit);ctl=load(a.control_audit);errors=[]
 for name,r in [('official',off),('adjustment',adj),('control',ctl)]:
  if r.get('pass') is not True:errors.append(f'{name} sub-audit failed: {r.get("errors")}')
 if int(off.get('official_action_dates',-1))!=int(adj.get('official_action_count',-2)):errors.append('official action count != adjustment input count')
 if int(adj.get('official_action_count',-1))!=int(adj.get('adjustment_event_count',-2)):errors.append('not every official action produced an adjustment event')
 if int(ctl.get('official_actions_material_missing',-1))!=0:errors.append('material official actions lack independent BaoStock factor support')
 if int(ctl.get('factor_ratio_mismatches',-1))!=0:errors.append('independent factor-ratio mismatches remain')
 if off.get('sse_native_control_missing',-1)!=0 or off.get('sse_native_control_conflicts',-1)!=0:errors.append('SSE native official control did not reconcile')
 if not off.get('dataset_fingerprint') or not adj.get('adjustment_chain_sha256'):errors.append('G5 fingerprints incomplete')
 canonical='\n'.join([str(off.get('dataset_fingerprint','')),str(adj.get('adjustment_chain_sha256','')),hashlib.sha256(json.dumps(ctl,ensure_ascii=False,sort_keys=True).encode()).hexdigest()]).encode();fp=hashlib.sha256(canonical).hexdigest()
 report={'gate':'G5','pass':not errors,'coverage_start':'2015-01-01','coverage_end':'2026-07-24','official_action_events':int(off.get('official_action_dates',0)),'adjustment_events':int(adj.get('adjustment_event_count',0)),'cninfo_source_requests':int(off.get('cninfo_source_requests',0)),'sse_native_controls_matched':int(off.get('sse_native_controls_matched',0)),'official_actions_factor_matched':int(ctl.get('official_actions_matched',0)),'official_actions_factor_material_missing':int(ctl.get('official_actions_material_missing',0)),'official_actions_factor_not_covered':int(ctl.get('official_actions_not_covered_by_factor_range',0)),'supplier_only_factor_changes_logged':int(ctl.get('supplier_only_economic_factor_changes_logged',0)),'methodology_rebases_logged':int(ctl.get('methodology_rebases_logged',0)),'factor_ratio_mismatches':int(ctl.get('factor_ratio_mismatches',0)),'g3_dataset_fingerprint':adj.get('g3_dataset_fingerprint'),'dataset_fingerprint':fp,'errors':errors}
 (out/'g5_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 (out/'g5_manifest.json').write_text(json.dumps({'version':'V3.2.22-g5-official-corporate-action-adjustment-chain','status':'PASS' if not errors else 'FAIL','scope':'SSE_MAIN_A + SZSE_MAIN_A','event_date_authority':'CNINFO structured WebAPI; SSE native exchange API as independent control where retained','price_adjustment_method':'official ex-right reference-price formula applied to G3 unadjusted closes','independent_numeric_control':'BaoStock validates official-event factor impact where comparable; supplier-only jumps/rebases are logged but not allowed to redefine official dates','audit':report},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
