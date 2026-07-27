#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from pathlib import Path
from stage3_trading_universe import eligible_mainboard_under_70,assert_point_in_time_price
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=json.loads((ROOT/'config/trading_universe_policy.json').read_text(encoding='utf-8'));errors=[];s=p.get('scope_rule') or {};pr=s.get('price_rule') or {}
 if set(s.get('include_boards') or [])!={'SSE_MAIN','SZSE_MAIN'}:errors.append('include boards mismatch')
 if not {'STAR','CHINEXT','BSE','NEEQ'}.issubset(set(s.get('exclude_boards') or [])):errors.append('required excluded boards missing')
 if pr.get('operator')!='<' or float(pr.get('threshold_cny',-1))!=70.0 or pr.get('exact_70_is_excluded') is not True:errors.append('strict <70 policy mismatch')
 cases=[('SSE_MAIN','69.99',True),('SZSE_MAIN','69.999',True),('SSE_MAIN','70',False),('SZSE_MAIN','70.01',False),('STAR','1',False),('CHINEXT','1',False),('BSE','1',False),('NEEQ','1',False)]
 for b,x,e in cases:
  if eligible_mainboard_under_70(b,x)!=e:errors.append(f'eligibility regression {b} {x}')
 try:assert_point_in_time_price('2026-07-27T14:59:59+08:00','2026-07-27T15:00:00+08:00')
 except Exception as exc:errors.append(f'valid PIT price rejected {exc}')
 try:assert_point_in_time_price('2026-07-27T15:00:01+08:00','2026-07-27T15:00:00+08:00');errors.append('future price was accepted')
 except ValueError:pass
 r={'gate':'S3GU_TRADING_UNIVERSE_POLICY','pass':not errors,'boards':['SSE_MAIN','SZSE_MAIN'],'strict_price_rule':'<70 CNY','exact_70_excluded':True,'excluded_boards':['STAR','CHINEXT','BSE','NEEQ'],'historical_price_source':'G3_UNADJUSTED_CLOSE_POINT_IN_TIME','errors':errors}
 out=ROOT/'data/stage3_universe';out.mkdir(parents=True,exist_ok=True);(out/'stage3_trading_universe_audit.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':sys.exit(main())
