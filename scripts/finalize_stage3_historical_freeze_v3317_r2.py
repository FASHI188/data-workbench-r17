#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def canonical(x: object) -> bytes:
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dump(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')


def main() -> int:
    ap = argparse.ArgumentParser()
    for name in ['authority','lock','project','stage2_manifest','universe_policy','s3g1j_full','s3g1j_retention','s3g4_final']:
        ap.add_argument('--' + name.replace('_','-'), required=True, dest=name)
    ap.add_argument('--governance-pr', required=True, type=int)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    source_policy_path = Path(a.universe_policy)
    policy = json.loads(source_policy_path.read_text(encoding='utf-8'))
    errors = []
    if policy.get('version') != 'V1-user-trading-universe-policy-2026-07-27': errors.append('policy version drift')
    if policy.get('status') != 'ACTIVE': errors.append('policy not ACTIVE')
    if set(policy.get('allowed_boards') or []) != {'SSE_MAIN_A','SZSE_MAIN_A'}: errors.append('allowed boards drift')
    if set(policy.get('excluded_boards') or []) != {'SSE_STAR','SZSE_CHINEXT','BSE','NEEQ'}: errors.append('excluded boards drift')
    price = policy.get('price_rule') or {}
    if float(price.get('maximum_exclusive', -1)) != 70.0: errors.append('maximum exclusive price drift')
    if price.get('price_equal_70_is_excluded') is not True: errors.append('exact 70 exclusion drift')
    if price.get('forbid_current_price_backfill_into_history') is not True: errors.append('current-price history backfill prohibition drift')
    hard = policy.get('hard_rules') or {}
    for key in ['exclude_price_ge_70_cny','exclude_neeq','exclude_bse','exclude_chinext','exclude_star_market','do_not_delete_raw_history_because_of_current_price','do_not_use_future_price_to_define_historical_eligibility']:
        if hard.get(key) is not True: errors.append(f'hard policy drift {key}')
    if errors:
        print(json.dumps({'pass':False,'errors':errors}, ensure_ascii=False, indent=2))
        return 2

    compat = dict(policy)
    compat['scope_rule'] = {
        'include_boards': ['SSE_MAIN','SZSE_MAIN'],
        'exclude_boards': ['STAR','CHINEXT','BSE','NEEQ'],
        'price_rule': {'operator':'<','threshold_cny':70.0,'exact_70_is_excluded':True},
    }
    compat['anti_lookahead'] = {'never_filter_history_using_current_price': True}

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    compat_path = out / '_universe_policy_schema_compat.json'
    dump(compat_path, compat)
    cmd = [
        sys.executable, 'scripts/finalize_stage3_historical_freeze_v3317.py',
        '--authority', a.authority, '--lock', a.lock, '--project', a.project,
        '--stage2-manifest', a.stage2_manifest, '--universe-policy', str(compat_path),
        '--s3g1j-full', a.s3g1j_full, '--s3g1j-retention', a.s3g1j_retention,
        '--s3g4-final', a.s3g4_final, '--governance-pr', str(a.governance_pr), '--out', a.out,
    ]
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        return rc

    actual_policy_sha = sha_file(source_policy_path)
    audit_path = out / 'stage3_final_audit.json'
    manifest_path = out / 'manifest.json'
    authority_path = out / 'stage3_authority_map.json'
    lock_path = out / 'stage3_final_lock.json'
    project_path = out / 'project_status.json'
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    basis = audit['fingerprint_basis']
    basis['trading_universe_policy_sha256'] = actual_policy_sha
    fingerprint = hashlib.sha256(canonical(basis)).hexdigest()
    audit['fingerprint_basis'] = basis
    audit['stage3_dataset_fingerprint'] = fingerprint
    manifest['fingerprint_basis'] = basis
    manifest['stage3_dataset_fingerprint'] = fingerprint
    dump(audit_path, audit); dump(manifest_path, manifest)

    authority = json.loads(authority_path.read_text(encoding='utf-8'))
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    project = json.loads(project_path.read_text(encoding='utf-8'))
    authority['final_freeze']['stage3_dataset_fingerprint'] = fingerprint
    lock['stage3_final_freeze']['stage3_dataset_fingerprint'] = fingerprint
    project['stage3']['historical_final_freeze']['stage3_dataset_fingerprint'] = fingerprint
    project['reproducibility']['stage3_final_fingerprint'] = fingerprint
    dump(authority_path, authority); dump(lock_path, lock); dump(project_path, project)
    compat_path.unlink()
    (out / 'SHA256SUMS.txt').write_text(
        f"{sha_file(manifest_path)}  manifest.json\n{sha_file(audit_path)}  stage3_final_audit.json\n{fingerprint}  canonical:stage3-fingerprint-basis\n",
        encoding='utf-8',
    )
    hashes = {p.name: sha_file(p) for p in sorted(out.iterdir()) if p.is_file() and p.name != 'output_sha256.json'}
    dump(out / 'output_sha256.json', hashes)
    print(json.dumps({'pass':True,'stage3_dataset_fingerprint':fingerprint,'authoritative_universe_policy_sha256':actual_policy_sha,'hashes':hashes}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
