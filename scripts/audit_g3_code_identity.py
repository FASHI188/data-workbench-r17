#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,json,sys
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    g3=Path(a.root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True);errors=[]
    transitions=json.loads((ROOT/'config/security_code_transitions.json').read_text(encoding='utf-8'))
    result=[]
    for t in transitions:
        if t['exchange']!='SZSE':
            errors.append(f"unsupported transition exchange in G3 identity audit: {t}");continue
        old=t['old_code'];new=t['new_code'];eff=date.fromisoformat(t['effective_date']);old_dates=[];new_dates=[]
        for p in sorted((g3/'szse').glob('szse_*.csv.gz')):
            with gzip.open(p,'rt',encoding='utf-8',newline='') as f:
                for r in csv.DictReader(f):
                    if r['code']==old:old_dates.append(date.fromisoformat(r['trade_date']))
                    elif r['code']==new:new_dates.append(date.fromisoformat(r['trade_date']))
        if not old_dates:errors.append(f'predecessor has zero official G3 bars: {old}')
        if not new_dates:errors.append(f'successor has zero official G3 bars: {new}')
        if old_dates and max(old_dates)>=eff:errors.append(f'predecessor bar survives transition {old}: {max(old_dates)} >= {eff}')
        if new_dates and min(new_dates)<eff:errors.append(f'successor bar predates transition {new}: {min(new_dates)} < {eff}')
        if new_dates and min(new_dates)!=eff:errors.append(f'successor first official bar is not transition effective date {new}: {min(new_dates)} != {eff}')
        result.append({'exchange':t['exchange'],'old_code':old,'new_code':new,'effective_date':t['effective_date'],'old_bar_count':len(old_dates),'old_first':min(old_dates).isoformat() if old_dates else None,'old_last':max(old_dates).isoformat() if old_dates else None,'new_bar_count':len(new_dates),'new_first':min(new_dates).isoformat() if new_dates else None,'new_last':max(new_dates).isoformat() if new_dates else None})
    report={'gate':'G3_CODE_TIME_IDENTITY','pass':not errors,'transitions':result,'errors':errors}
    (out/'g3_code_identity_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2

if __name__=='__main__':sys.exit(main())
