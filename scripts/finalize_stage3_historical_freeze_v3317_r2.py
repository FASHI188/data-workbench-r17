#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

FINAL_VERSION = 'V3.3.17-stage3-historical-final-freeze'
FINAL_FINGERPRINT = '36bfbe0ae703a923ce2575f111a8c68a64c89177c71eeee2cfd9e1ec47bf535f'


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


def validate_policy(source_policy_path: Path) -> tuple[dict, list[str]]:
    policy = json.loads(source_policy_path.read_text(encoding='utf-8'))
    errors: list[str] = []
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
    return policy, errors


def emit_hashes(out: Path, fingerprint: str) -> None:
    manifest_path = out / 'manifest.json'
    audit_path = out / 'stage3_final_audit.json'
    (out / 'SHA256SUMS.txt').write_text(
        f"{sha_file(manifest_path)}  manifest.json\n{sha_file(audit_path)}  stage3_final_audit.json\n{fingerprint}  canonical:stage3-fingerprint-basis\n",
        encoding='utf-8',
    )
    hashes = {p.name: sha_file(p) for p in sorted(out.iterdir()) if p.is_file() and p.name != 'output_sha256.json'}
    dump(out / 'output_sha256.json', hashes)


def verify_already_frozen(a: argparse.Namespace, policy_path: Path, out: Path) -> int:
    authority = json.loads(Path(a.authority).read_text(encoding='utf-8'))
    lock = json.loads(Path(a.lock).read_text(encoding='utf-8'))
    project = json.loads(Path(a.project).read_text(encoding='utf-8'))
    manifest_src = Path('data/stage3_final/manifest.json')
    audit_src = Path('data/stage3_final/stage3_final_audit.json')
    errors: list[str] = []

    if authority.get('schema_version') != 10 or authority.get('status') != 'STAGE3_HISTORICAL_FINAL_FREEZE_PASS': errors.append('authority final-freeze state drift')
    if lock.get('version') != FINAL_VERSION or lock.get('status') != 'PASS_FROZEN_HISTORICAL': errors.append('lock final-freeze state drift')
    if project.get('stage3', {}).get('status') != 'PASS_FROZEN_HISTORICAL': errors.append('project final-freeze state drift')
    if project.get('stage3', {}).get('pending_final_gates') != []: errors.append('pending component gates not empty')
    if not manifest_src.exists() or not audit_src.exists(): errors.append('committed final manifest/audit missing')
    if errors:
        print(json.dumps({'pass':False,'mode':'ALREADY_FROZEN_VERIFY','errors':errors}, ensure_ascii=False, indent=2))
        return 2

    manifest = json.loads(manifest_src.read_text(encoding='utf-8'))
    audit = json.loads(audit_src.read_text(encoding='utf-8'))
    fp = manifest.get('stage3_dataset_fingerprint')
    if fp != FINAL_FINGERPRINT: errors.append('manifest fingerprint drift')
    if audit.get('stage3_dataset_fingerprint') != fp or audit.get('pass') is not True or audit.get('errors') != []: errors.append('audit/fingerprint drift')
    basis = manifest.get('fingerprint_basis') or {}
    if hashlib.sha256(canonical(basis)).hexdigest() != fp: errors.append('canonical fingerprint recomputation mismatch')
    if basis.get('trading_universe_policy_sha256') != sha_file(policy_path): errors.append('universe policy fingerprint drift')
    if manifest.get('status') != 'PASS_FROZEN_HISTORICAL' or manifest.get('historical_reproducibility_pass') is not True: errors.append('manifest final status drift')
    retained = manifest.get('s3g1j_retained_raw_residuals') or {}
    if retained.get('document_error_count') != 1362 or retained.get('unresolved_tie_count') != 1279 or retained.get('raw_data_verdict') != 'FAIL_CLOSED' or retained.get('usable_as_numeric_truth') is not False: errors.append('S3G1J retained residual semantics drift')
    g4 = manifest.get('s3g4') or {}
    if g4.get('forecast_population') != 51732 or g4.get('surprise_observations') != 29139 or g4.get('actual_pit_exclusion_count') != 4 or g4.get('expectation_is_strictly_prior') is not True or g4.get('analyst_consensus_used') is not False: errors.append('S3G4 frozen facts drift')
    freshness = manifest.get('freshness') or {}
    if freshness.get('status') != 'STALE' or freshness.get('eligible_for_stage4') is not False: errors.append('freshness truth drift')
    downstream = manifest.get('downstream') or {}
    for key in ['stage4_model_training_allowed','stage4_unlocked','alpha_training_allowed','live_signal_allowed']:
        if downstream.get(key) is not False: errors.append(f'downstream unexpectedly unlocked: {key}')
    if downstream.get('user_hold_before_stage4') is not True: errors.append('user hold before Stage4 lost')
    if lock.get('stage3_final_freeze', {}).get('stage3_dataset_fingerprint') != fp: errors.append('lock fingerprint pointer drift')
    if authority.get('final_freeze', {}).get('stage3_dataset_fingerprint') != fp: errors.append('authority fingerprint pointer drift')
    if project.get('stage3', {}).get('historical_final_freeze', {}).get('stage3_dataset_fingerprint') != fp: errors.append('project fingerprint pointer drift')
    if project.get('reproducibility', {}).get('stage3_final_fingerprint') != fp or project.get('reproducibility', {}).get('overall_pass') is not True: errors.append('project reproducibility fingerprint drift')
    if project.get('freshness', {}).get('status') != 'STALE': errors.append('project freshness drift')
    if project.get('stage4_unlocked') is not False or project.get('alpha_training_allowed') is not False or project.get('live_signal_allowed') is not False or project.get('user_hold_before_stage4') is not True: errors.append('project downstream/user-hold drift')

    if errors:
        print(json.dumps({'pass':False,'mode':'ALREADY_FROZEN_VERIFY','errors':errors}, ensure_ascii=False, indent=2))
        return 2

    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest_src, out / 'manifest.json')
    shutil.copyfile(audit_src, out / 'stage3_final_audit.json')
    shutil.copyfile(Path(a.authority), out / 'stage3_authority_map.json')
    shutil.copyfile(Path(a.lock), out / 'stage3_final_lock.json')
    shutil.copyfile(Path(a.project), out / 'project_status.json')
    emit_hashes(out, fp)
    print(json.dumps({'pass':True,'mode':'ALREADY_FROZEN_IDEMPOTENT_VERIFY','stage3_dataset_fingerprint':fp}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    for name in ['authority','lock','project','stage2_manifest','universe_policy','s3g1j_full','s3g1j_retention','s3g4_final']:
        ap.add_argument('--' + name.replace('_','-'), required=True, dest=name)
    ap.add_argument('--governance-pr', required=True, type=int)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    source_policy_path = Path(a.universe_policy)
    policy, errors = validate_policy(source_policy_path)
    if errors:
        print(json.dumps({'pass':False,'errors':errors}, ensure_ascii=False, indent=2))
        return 2

    out = Path(a.out)
    authority_now = json.loads(Path(a.authority).read_text(encoding='utf-8'))
    lock_now = json.loads(Path(a.lock).read_text(encoding='utf-8'))
    project_now = json.loads(Path(a.project).read_text(encoding='utf-8'))
    if (
        authority_now.get('status') == 'STAGE3_HISTORICAL_FINAL_FREEZE_PASS'
        and lock_now.get('status') == 'PASS_FROZEN_HISTORICAL'
        and project_now.get('stage3', {}).get('status') == 'PASS_FROZEN_HISTORICAL'
    ):
        return verify_already_frozen(a, source_policy_path, out)

    compat = dict(policy)
    compat['scope_rule'] = {
        'include_boards': ['SSE_MAIN','SZSE_MAIN'],
        'exclude_boards': ['STAR','CHINEXT','BSE','NEEQ'],
        'price_rule': {'operator':'<','threshold_cny':70.0,'exact_70_is_excluded':True},
    }
    compat['anti_lookahead'] = {'never_filter_history_using_current_price': True}

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
    emit_hashes(out, fingerprint)
    print(json.dumps({'pass':True,'mode':'PREFREEZE_BUILD','stage3_dataset_fingerprint':fingerprint,'authoritative_universe_policy_sha256':actual_policy_sha}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
