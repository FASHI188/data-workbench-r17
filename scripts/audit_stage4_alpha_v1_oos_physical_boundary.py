#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    ).hexdigest()


def q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def one_row(con, sql: str) -> dict[str, Any]:
    cur = con.execute(sql)
    cols = [x[0] for x in cur.description]
    return dict(zip(cols, cur.fetchone()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--contract', required=True)
    ap.add_argument('--source-cv-authorization', required=True)
    ap.add_argument('--source-verification', required=True)
    ap.add_argument('--package-dir', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    import duckdb

    checks: dict[str, bool] = {}
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = '') -> None:
        checks[name] = bool(condition)
        if not condition:
            failures.append(name + (f': {detail}' if detail else ''))

    out_path = Path(args.out)
    try:
        contract = json.loads(Path(args.contract).read_text(encoding='utf-8'))
        basis = contract['fingerprint_basis']
        check('contract_fingerprint', canonical_hash(basis) == contract['fingerprint'])
        check('contract_status', contract.get('status') == 'PRE_PREDICTION_PHYSICAL_OOS_BOUNDARY_COMPILER_NON_LABEL_NON_CONSUMING')

        source_auth = json.loads(Path(args.source_cv_authorization).read_text(encoding='utf-8'))
        source_fp = basis['source_cv_authorization_fingerprint']
        check('source_cv_authorization_fingerprint', source_auth.get('fingerprint') == source_fp and canonical_hash(source_auth['fingerprint_basis']) == source_fp)
        expected_features = list(source_auth['fingerprint_basis']['feature_columns'])

        verification = json.loads(Path(args.source_verification).read_text(encoding='utf-8'))
        check('source_verification_status', verification.get('status') == 'VERIFIED')
        check('source_verification_contract_binding', verification.get('boundary_contract_fingerprint') == contract['fingerprint'])
        for key, expected in basis['inputs'].items():
            got = verification.get('artifacts', {}).get(key, {})
            check(f'source_{key}_artifact_id', int(got.get('artifact_id', -1)) == int(expected['artifact_id']))
            check(f'source_{key}_archive_sha', got.get('archive_sha256') == expected['artifact_zip_sha256'])
            check(f'source_{key}_verified', got.get('verified') is True)

        package = Path(args.package_dir)
        outputs = basis['outputs']
        features = package / outputs['features']
        market = package / outputs['market']
        lifecycle = package / outputs['lifecycle']
        manifest_path = package / outputs['manifest']
        hashes_path = package / outputs['hashes']
        for path in [features, market, lifecycle, manifest_path, hashes_path]:
            check(f'exists_{path.name}', path.is_file())

        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        preliminary_hashes = json.loads(hashes_path.read_text(encoding='utf-8'))
        check('manifest_status', manifest.get('status') == 'PHYSICALLY_OOS_ONLY_PRE_PREDICTION_NON_LABEL')
        check('manifest_contract_binding', manifest.get('boundary_contract_fingerprint') == contract['fingerprint'])
        check('manifest_source_cv_binding', manifest.get('source_cv_authorization_fingerprint') == source_fp)
        check('manifest_feature_columns', manifest.get('feature_columns') == expected_features)

        for path in [features, market, lifecycle, manifest_path]:
            check(f'preliminary_hash_{path.name}', preliminary_hashes.get(path.name) == sha256_file(path))

        guards = manifest.get('guards', {})
        for key in [
            'broad_feature_matrix_available_downstream',
            'broad_g3_available_downstream',
            'raw_g5_available_downstream',
            'raw_g2_available_downstream',
            'oos_prediction_executed',
            'oos_label_constructed',
            'oos_label_value_read',
            'model_loaded',
            'authorization_consumed',
            'fit_retrain_tune_reselect_executed',
            'final_lockbox_accessed',
            'business_metrics_computed',
        ]:
            check(f'guard_{key}_false', guards.get(key) is False)
        for key in ['post_oos_feature_rows', 'post_oos_market_rows', 'post_oos_lifecycle_delist_rows']:
            check(f'guard_{key}_zero', int(guards.get(key, -1)) == 0)

        start = basis['scope']['decision_start']
        end = basis['scope']['decision_end']
        con = duckdb.connect()
        con.execute('PRAGMA threads=2')
        con.execute(f'CREATE TEMP VIEW f AS SELECT * FROM read_parquet({q(str(features))})')
        con.execute(f'CREATE TEMP VIEW m AS SELECT * FROM read_parquet({q(str(market))})')
        con.execute(f'CREATE TEMP VIEW l AS SELECT * FROM read_parquet({q(str(lifecycle))})')

        actual_feature_cols = [x[0] for x in con.execute('SELECT * FROM f LIMIT 0').description]
        check('feature_schema_exact', actual_feature_cols == ['trade_date', 'exchange', 'code'] + expected_features, str(actual_feature_cols))

        fstats = one_row(con, f"""
          SELECT count(*)::BIGINT AS row_count,
                 count(DISTINCT (trade_date,exchange,code))::BIGINT AS unique_keys,
                 count(DISTINCT trade_date)::BIGINT AS decision_days,
                 min(trade_date) AS date_min,max(trade_date) AS date_max,
                 count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT AS outside_rows
          FROM f
        """)
        mstats = one_row(con, f"""
          SELECT count(*)::BIGINT AS row_count,
                 count(DISTINCT (trade_date,exchange,code))::BIGINT AS unique_keys,
                 count(DISTINCT trade_date)::BIGINT AS market_days,
                 min(trade_date) AS date_min,max(trade_date) AS date_max,
                 count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT AS outside_rows,
                 count(*) FILTER(WHERE open IS NULL OR close IS NULL OR factor IS NULL)::BIGINT AS null_required_rows
          FROM m
        """)
        lstats = one_row(con, f"""
          SELECT count(*)::BIGINT AS row_count,
                 max(listed_to_exclusive) AS listed_to_max,
                 count(*) FILTER(WHERE listed_to_exclusive IS NOT NULL AND listed_to_exclusive>DATE {q(end)})::BIGINT AS post_oos_delist_rows
          FROM l
        """)
        structural = one_row(con, """
          WITH fd AS (SELECT DISTINCT trade_date FROM f),
               md AS (SELECT DISTINCT trade_date FROM m),
               missing_dates AS (SELECT fd.trade_date FROM fd LEFT JOIN md USING(trade_date) WHERE md.trade_date IS NULL),
               missing_symbols AS (
                 SELECT DISTINCT f.exchange,f.code FROM f
                 LEFT JOIN l ON f.exchange=l.exchange AND f.code=l.code
                 WHERE l.code IS NULL
               )
          SELECT (SELECT count(*) FROM missing_dates)::BIGINT AS feature_dates_missing_market_calendar,
                 (SELECT count(*) FROM missing_symbols)::BIGINT AS feature_symbols_missing_lifecycle
        """)

        for name, stats in [('features', fstats), ('market', mstats)]:
            check(f'{name}_rows_positive', int(stats['row_count']) > 0)
            check(f'{name}_keys_unique', int(stats['row_count']) == int(stats['unique_keys']), str(stats))
            check(f'{name}_min_exact', str(stats['date_min']) == start, str(stats))
            check(f'{name}_max_exact', str(stats['date_max']) == end, str(stats))
            check(f'{name}_outside_zero', int(stats['outside_rows']) == 0, str(stats))
        check('market_required_values_complete', int(mstats['null_required_rows']) == 0, str(mstats))
        check('lifecycle_post_oos_delist_zero', int(lstats['post_oos_delist_rows']) == 0, str(lstats))
        check('feature_dates_on_market_calendar', int(structural['feature_dates_missing_market_calendar']) == 0, str(structural))
        check('feature_symbols_have_lifecycle', int(structural['feature_symbols_missing_lifecycle']) == 0, str(structural))

        check('manifest_features_match', int(manifest['features']['row_count']) == int(fstats['row_count']) and int(manifest['features']['decision_days']) == int(fstats['decision_days']))
        check('manifest_market_match', int(manifest['market']['row_count']) == int(mstats['row_count']) and int(manifest['market']['market_days']) == int(mstats['market_days']))
        check('manifest_lifecycle_match', int(manifest['lifecycle']['row_count']) == int(lstats['row_count']))
        check('manifest_structural_match', manifest['structural_readiness'] == structural)

        result = {
            'schema_version': 1,
            'status': 'PASS' if not failures else 'FAIL',
            'pass': not failures,
            'boundary_contract_fingerprint': contract['fingerprint'],
            'checks': checks,
            'failed_checks': failures,
            'features': fstats,
            'market': mstats,
            'lifecycle': lstats,
            'structural_readiness': structural,
            'post_oos_rows_observed': int(fstats['outside_rows']) + int(mstats['outside_rows']) + int(lstats['post_oos_delist_rows']),
            'oos_prediction_executed': False,
            'oos_label_constructed': False,
            'oos_label_value_read': False,
            'model_loaded': False,
            'authorization_consumed': False,
            'final_lockbox_accessed': False,
        }
    except Exception as exc:
        failures.append(f'exception: {type(exc).__name__}: {exc}')
        result = {
            'schema_version': 1,
            'status': 'FAIL',
            'pass': False,
            'checks': checks,
            'failed_checks': failures,
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result['pass'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
