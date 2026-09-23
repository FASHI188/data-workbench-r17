#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from stage3_trading_universe import eligible_mainboard_under_70, assert_point_in_time_price

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=json.loads((ROOT/'config/trading_universe_policy.json').read_text(encoding='utf-8'))
    errors=[]
    allowed=set(p.get('allowed_boards') or [])
    excluded=set(p.get('excluded_boards') or [])
    pr=p.get('price_rule') or {}
    hard=p.get('hard_rules') or {}

    if allowed!={'SSE_MAIN_A','SZSE_MAIN_A'}:
        errors.append(f'allowed boards mismatch: {sorted(allowed)}')
    if not {'SSE_STAR','SZSE_CHINEXT','BSE','NEEQ'}.issubset(excluded):
        errors.append(f'required excluded boards missing: {sorted(excluded)}')
    if float(pr.get('maximum_exclusive',-1))!=70.0 or pr.get('price_equal_70_is_excluded') is not True:
        errors.append('strict <70 CNY price contract mismatch')
    if pr.get('backtest_price_source')!='G3 official unadjusted close available at the signal session':
        errors.append('historical price source is not frozen G3 unadjusted close')
    if pr.get('forbid_current_price_backfill_into_history') is not True:
        errors.append('current-price historical backfill prohibition missing')
    required_hard={
        'exclude_price_ge_70_cny','exclude_neeq','exclude_bse','exclude_chinext','exclude_star_market',
        'do_not_delete_raw_history_because_of_current_price','do_not_use_future_price_to_define_historical_eligibility'
    }
    missing=[k for k in sorted(required_hard) if hard.get(k) is not True]
    if missing:
        errors.append(f'hard rules missing: {missing}')

    cases=[
        ('SSE_MAIN_A','69.99',True),('SZSE_MAIN_A','69.999',True),
        ('SSE_MAIN_A','70',False),('SZSE_MAIN_A','70.01',False),
        ('SSE_STAR','1',False),('SZSE_CHINEXT','1',False),('BSE','1',False),('NEEQ','1',False)
    ]
    for board,price,expected in cases:
        if eligible_mainboard_under_70(board,price)!=expected:
            errors.append(f'eligibility regression {board} {price}')
    try:
        assert_point_in_time_price('2026-07-27T14:59:59+08:00','2026-07-27T15:00:00+08:00')
    except Exception as exc:
        errors.append(f'valid PIT price rejected: {exc}')
    try:
        assert_point_in_time_price('2026-07-27T15:00:01+08:00','2026-07-27T15:00:00+08:00')
        errors.append('future price was accepted')
    except ValueError:
        pass

    report={
        'gate':'S3GU_TRADING_UNIVERSE_POLICY',
        'pass':not errors,
        'boards':['SSE_MAIN_A','SZSE_MAIN_A'],
        'strict_price_rule':'<70 CNY',
        'exact_70_excluded':True,
        'excluded_boards':['SSE_STAR','SZSE_CHINEXT','BSE','NEEQ'],
        'historical_price_source':'G3_UNADJUSTED_CLOSE_POINT_IN_TIME',
        'raw_history_retained':True,
        'errors':errors,
    }
    out=ROOT/'data/stage3_universe';out.mkdir(parents=True,exist_ok=True)
    (out/'stage3_trading_universe_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if not errors else 2


if __name__=='__main__':
    sys.exit(main())
