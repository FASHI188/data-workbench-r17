#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_AUDITS = {
    "S3G0_POINT_IN_TIME_FEATURE_CONTRACT": "stage3_contract_audit.json",
    "S3G1E_PERIODIC_FILING_LEDGER": "stage3_periodic_filing_ledger_audit.json",
    "S3G1G_REPORT_VERSION_SELECTION": "stage3_financial_report_versions_audit.json",
    "S3G1H_PDF_PARSER_PROBE": "financial_pdf_parser_probe.json",
    "S3G1I_POPULATION_PDF_PROBE": "stage3_financial_pdf_population_probe.json",
    "S3G1J_FINANCIAL_RAW_VALUES": "stage3_financial_raw_audit.json",
    "S3G2_ANNOUNCEMENT_LEDGER": "stage3_announcement_ledger_audit.json",
    "S3G3A_INDUSTRY_SOURCE_PROBE": "capco_industry_history_probe.json",
    "S3G3B_INDUSTRY_LEDGER": "stage3_industry_classification_audit.json",
    "S3G4A_FORECAST_PARSER_PROBE": "earnings_forecast_parser_probe.json",
    "S3G4_EARNINGS_SURPRISE": "stage3_earnings_surprise_audit.json",
}


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def one(root: Path, name: str) -> Path:
    xs=list(root.rglob(name))
    if len(xs)!=1:raise ValueError(f'expected one {name}, got {len(xs)} under {root}')
    return xs[0]


def canonical(obj: object) -> bytes:
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')


def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument('--lock',required=True);ap.add_argument('--evidence',required=True);ap.add_argument('--digests',required=True);ap.add_argument('--stage2-manifest',required=True);ap.add_argument('--universe-policy',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    lock=json.loads(Path(a.lock).read_text(encoding='utf-8'));stage2=json.loads(Path(a.stage2_manifest).read_text(encoding='utf-8'));policy=json.loads(Path(a.universe_policy).read_text(encoding='utf-8'));digests=json.loads(Path(a.digests).read_text(encoding='utf-8'));root=Path(a.evidence);out=Path(a.out);out.mkdir(parents=True,exist_ok=True);errors=[];audits={}
    if stage2.get('version')!='V3.2.25-stage2-final-freeze' or stage2.get('stage2_dataset_fingerprint')!='f17f7ab63f4532dda635eb7366e7df7bf5497a5ce814410105312bccb53125bb' or stage2.get('all_hard_gates_pass') is not True:errors.append('Stage2 dependency is not exact V3.2.25 PASS')
    gates=lock.get('required_gates') or {}
    if set(gates)!=set(EXPECTED_AUDITS):errors.append(f'final lock gate set mismatch {sorted(gates)}')
    for gate,spec in gates.items():
        if not spec.get('run_id'):errors.append(f'{gate} run_id not locked');continue
        if spec.get('artifact') not in digests:errors.append(f'{gate} artifact digest missing for {spec.get("artifact")}')
        try:
            p=one(root,EXPECTED_AUDITS[gate]);r=json.loads(p.read_text(encoding='utf-8'));audits[gate]=r
            if r.get('pass') is not True or r.get('errors'):errors.append(f'{gate} not clean PASS: {r.get("errors")}')
        except Exception as exc:errors.append(f'{gate} audit unavailable: {exc}')
    # Hard cross-family semantics.
    s3g0=audits.get('S3G0_POINT_IN_TIME_FEATURE_CONTRACT',{});s3g1e=audits.get('S3G1E_PERIODIC_FILING_LEDGER',{});s3g1g=audits.get('S3G1G_REPORT_VERSION_SELECTION',{});s3g1j=audits.get('S3G1J_FINANCIAL_RAW_VALUES',{});s3g2=audits.get('S3G2_ANNOUNCEMENT_LEDGER',{});s3g3=audits.get('S3G3B_INDUSTRY_LEDGER',{});s3g4=audits.get('S3G4_EARNINGS_SURPRISE',{})
    if s3g0.get('stage2_dataset_fingerprint')!=stage2.get('stage2_dataset_fingerprint'):errors.append('S3G0 Stage2 fingerprint mismatch')
    if int(s3g1e.get('security_identity_count',-1))!=3402 or int(s3g1e.get('g3_trading_days',-1))!=2808:errors.append('S3G1E universe/trading-day mismatch')
    if int(s3g1g.get('unresolved_period_groups',-1))!=0:errors.append('S3G1G unresolved A-share report periods nonzero')
    if s3g1j.get('historical_current_f10_used_as_truth') is not False:errors.append('S3G1J current F10 historical truth prohibition failed')
    if int(s3g1j.get('unresolved_tie_count',-1))!=0 or int(s3g1j.get('document_error_count',-1))!=0:errors.append('S3G1J unresolved document/tie errors')
    if s3g2.get('scalar_magnitude_from_title_allowed') is not False:errors.append('S3G2 title-derived scalar prohibition failed')
    if s3g3.get('current_industry_backfill_used') is not False:errors.append('S3G3 current-industry backfill prohibition failed')
    if s3g4.get('analyst_consensus_used') is not False:errors.append('S3G4 analyst-consensus prohibition failed')
    # User trading universe policy is itself frozen evidence.
    sr=policy.get('scope_rule') or {};pr=sr.get('price_rule') or {};excluded=set(sr.get('exclude_boards') or [])
    if set(sr.get('include_boards') or [])!={'SSE_MAIN','SZSE_MAIN'}:errors.append('trading universe includes non-main-board scope')
    if pr.get('operator')!='<' or float(pr.get('threshold_cny',-1))!=70.0 or pr.get('exact_70_is_excluded') is not True:errors.append('strict <70 CNY policy mismatch')
    if not {'STAR','CHINEXT','BSE','NEEQ'}.issubset(excluded):errors.append('required excluded boards missing')
    if (policy.get('anti_lookahead') or {}).get('never_filter_history_using_current_price') is not True:errors.append('price-filter anti-lookahead rule missing')
    dataset_shas={
        'periodic_filing_ledger':s3g1e.get('ledger_sha256'),
        'financial_raw_values':s3g1j.get('financial_values_sha256'),
        'financial_documents':s3g1j.get('financial_documents_sha256'),
        'announcement_ledger':s3g2.get('ledger_sha256'),
        'industry_ledger':s3g3.get('ledger_sha256'),
        'earnings_surprise':s3g4.get('surprise_ledger_sha256'),
    }
    if any(not v for v in dataset_shas.values()):errors.append(f'final Stage3 dataset SHAs incomplete: {dataset_shas}')
    basis={
        'stage2_version':stage2.get('version'),'stage2_fingerprint':stage2.get('stage2_dataset_fingerprint'),
        'stage3_lock_version':lock.get('version'),'gate_artifact_digests':{k:digests.get(v.get('artifact')) for k,v in sorted(gates.items())},
        'dataset_shas':dataset_shas,'trading_universe_policy_sha256':sha_file(Path(a.universe_policy)),
        'scope':'SSE_MAIN_A + SZSE_MAIN_A; tradable candidate price strictly below CNY 70 point-in-time',
    }
    fp=sha_bytes(canonical(basis))
    report={'gate':'STAGE3_FINAL_FREEZE','pass':not errors,'version':'V3.3.5-stage3-final-freeze','stage2_fingerprint':stage2.get('stage2_dataset_fingerprint'),'stage3_dataset_fingerprint':fp,'fingerprint_basis':basis,'errors':errors}
    (out/'stage3_final_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'version':report['version'],'status':'PASS' if not errors else 'FAIL','all_hard_gates_pass':not errors,'stage4_model_training_allowed':not errors,'stage2_dependency':{'version':stage2.get('version'),'fingerprint':stage2.get('stage2_dataset_fingerprint')},'stage3_dataset_fingerprint':fp,'fingerprint_algorithm':'SHA-256 over canonical JSON fingerprint_basis','fingerprint_basis':basis,'trading_universe':{'boards':['SSE_MAIN','SZSE_MAIN'],'price':'<70 CNY point-in-time','excluded':['STAR','CHINEXT','BSE','NEEQ']},'errors':errors}
    mp=out/'manifest.json';mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');(out/'SHA256SUMS.txt').write_text(f"{sha_file(mp)}  manifest.json\n{fp}  canonical:stage3-fingerprint-basis\n",encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2
if __name__=='__main__':raise SystemExit(main())
