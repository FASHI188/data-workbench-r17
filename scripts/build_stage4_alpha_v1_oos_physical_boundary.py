#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
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


def qi(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sql_file_list(paths: list[Path]) -> str:
    return '[' + ','.join(q(str(p)) for p in paths) + ']'


def one_row(con, sql: str) -> dict[str, Any]:
    cur = con.execute(sql)
    cols = [x[0] for x in cur.description]
    return dict(zip(cols, cur.fetchone()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--contract', required=True)
    ap.add_argument('--source-cv-authorization', required=True)
    ap.add_argument('--source-verification', required=True)
    ap.add_argument('--matrix-root', required=True)
    ap.add_argument('--g3-root', required=True)
    ap.add_argument('--g5-root', required=True)
    ap.add_argument('--g2-root', required=True)
    ap.add_argument('--work-dir', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    import duckdb

    contract = json.loads(Path(args.contract).read_text(encoding='utf-8'))
    basis = contract['fingerprint_basis']
    if canonical_hash(basis) != contract['fingerprint']:
        raise ValueError('OOS physical-boundary contract fingerprint mismatch')
    if contract['status'] != 'PRE_PREDICTION_PHYSICAL_OOS_BOUNDARY_COMPILER_NON_LABEL_NON_CONSUMING':
        raise ValueError('unexpected OOS physical-boundary contract status')

    scope = basis['scope']
    for key in [
        'oos_prediction_forbidden',
        'oos_label_construction_forbidden',
        'oos_label_value_read_forbidden',
        'model_load_forbidden',
        'authorization_consumption_forbidden',
        'fit_retrain_tune_reselect_forbidden',
        'final_lockbox_access_forbidden',
        'business_metrics_forbidden',
    ]:
        if scope.get(key) is not True:
            raise ValueError(f'boundary permission not closed: {key}')

    source_auth = json.loads(Path(args.source_cv_authorization).read_text(encoding='utf-8'))
    source_fp = basis['source_cv_authorization_fingerprint']
    if source_auth.get('fingerprint') != source_fp or canonical_hash(source_auth['fingerprint_basis']) != source_fp:
        raise ValueError('source CV authorization fingerprint mismatch')
    feature_columns = list(source_auth['fingerprint_basis']['feature_columns'])
    if not feature_columns:
        raise ValueError('empty frozen feature column list')

    verification = json.loads(Path(args.source_verification).read_text(encoding='utf-8'))
    if verification.get('status') != 'VERIFIED':
        raise ValueError('source archive verification is not VERIFIED')
    if verification.get('boundary_contract_fingerprint') != contract['fingerprint']:
        raise ValueError('source verification not bound to boundary contract')
    for key, expected in basis['inputs'].items():
        got = verification.get('artifacts', {}).get(key, {})
        if int(got.get('artifact_id', -1)) != int(expected['artifact_id']):
            raise ValueError(f'source artifact id mismatch: {key}')
        if got.get('archive_sha256') != expected['artifact_zip_sha256'] or got.get('verified') is not True:
            raise ValueError(f'source archive SHA mismatch: {key}')

    matrix_hits = sorted(Path(args.matrix_root).rglob(basis['inputs']['feature_matrix']['file_name']))
    if len(matrix_hits) != 1:
        raise ValueError(f'expected exactly one feature matrix, got {matrix_hits}')
    matrix = matrix_hits[0]
    if sha256_file(matrix) != basis['inputs']['feature_matrix']['file_sha256']:
        raise ValueError('feature matrix byte SHA mismatch')

    g5_hits = sorted(Path(args.g5_root).rglob(basis['inputs']['stage2_g5']['file_name']))
    g2_hits = sorted(Path(args.g2_root).rglob(basis['inputs']['stage2_g2']['file_name']))
    if len(g5_hits) != 1 or len(g2_hits) != 1:
        raise ValueError(f'expected one G5/G2 authority file, got g5={g5_hits} g2={g2_hits}')
    g5_chain, g2_intervals = g5_hits[0], g2_hits[0]

    rx = re.compile(r'(?:sse|szse)_(20\d\d)(?:_shard\d+)?\.csv\.gz$', re.I)
    g3_files: list[Path] = []
    years: set[int] = set()
    for p in Path(args.g3_root).rglob('*.csv.gz'):
        m = rx.search(p.name)
        if m and int(m.group(1)) in (2023, 2024):
            g3_files.append(p)
            years.add(int(m.group(1)))
    g3_files = sorted(g3_files)
    if not g3_files or years != {2023, 2024}:
        raise ValueError(f'physical G3 source-year selection failed: {sorted(years)}')
    if any(re.search(r'202[5-9]|203\d', p.name) for p in g3_files):
        raise ValueError('post-OOS G3 file selected')

    out = Path(args.out)
    work = Path(args.work_dir)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    tmp = work / 'duckdb-tmp'
    tmp.mkdir(parents=True, exist_ok=True)

    start = scope['decision_start']
    end = scope['decision_end']
    lockbox = scope['final_lockbox_start']
    outputs = basis['outputs']
    features_out = out / outputs['features']
    market_out = out / outputs['market']
    lifecycle_out = out / outputs['lifecycle']

    con = duckdb.connect()
    con.execute('PRAGMA threads=4')
    con.execute("PRAGMA memory_limit='7GB'")
    con.execute(f'PRAGMA temp_directory={q(str(tmp))}')

    feat_sql = ','.join(qi(c) for c in feature_columns)
    con.execute(f"""
      COPY (
        SELECT CAST(trade_date AS DATE) AS trade_date,
               upper(CAST(exchange AS VARCHAR)) AS exchange,
               lpad(CAST(code AS VARCHAR),6,'0') AS code,
               {feat_sql}
        FROM read_parquet({q(str(matrix))})
        WHERE CAST(trade_date AS DATE) BETWEEN DATE {q(start)} AND DATE {q(end)}
        ORDER BY trade_date,exchange,code
      ) TO {q(str(features_out))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    g3_list = sql_file_list(g3_files)
    con.execute(f"""
      CREATE TEMP TABLE market_raw AS
      SELECT upper(CAST(exchange AS VARCHAR)) AS exchange,
             lpad(CAST(code AS VARCHAR),6,'0') AS code,
             CAST(trade_date AS DATE) AS trade_date,
             CAST(open AS DOUBLE) AS open,
             CAST(close AS DOUBLE) AS close
      FROM read_csv({g3_list}, header=true, auto_detect=true, union_by_name=true)
      WHERE CAST(trade_date AS DATE) BETWEEN DATE {q(start)} AND DATE {q(end)}
    """)
    con.execute(f"""
      CREATE TEMP TABLE g5_relevant AS
      SELECT upper(CAST(exchange AS VARCHAR)) AS exchange,
             lpad(CAST(code AS VARCHAR),6,'0') AS code,
             CAST(ex_date AS DATE) AS ex_date,
             CAST(cumulative_back_adjust_multiplier AS DOUBLE) AS factor
      FROM read_csv({q(str(g5_chain))}, header=true, auto_detect=true, compression='gzip')
      WHERE CAST(ex_date AS DATE) < DATE {q(lockbox)}
      ORDER BY exchange,code,ex_date
    """)
    con.execute(f"""
      COPY (
        SELECT m.exchange,m.code,m.trade_date,m.open,m.close,coalesce(g.factor,1.0) AS factor
        FROM (SELECT * FROM market_raw ORDER BY exchange,code,trade_date) m
        ASOF LEFT JOIN g5_relevant g
          ON m.exchange=g.exchange AND m.code=g.code AND m.trade_date>=g.ex_date
        ORDER BY m.trade_date,m.exchange,m.code
      ) TO {q(str(market_out))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    con.execute(f"""
      CREATE TEMP TABLE feature_symbols AS
      SELECT DISTINCT exchange,code FROM read_parquet({q(str(features_out))})
    """)
    con.execute(f"""
      COPY (
        WITH raw AS (
          SELECT upper(CAST(exchange AS VARCHAR)) AS exchange,
                 lpad(CAST(code AS VARCHAR),6,'0') AS code,
                 CAST(listed_from AS DATE) AS listed_from,
                 CASE
                   WHEN listed_to_exclusive IS NULL OR trim(CAST(listed_to_exclusive AS VARCHAR))='' THEN NULL
                   ELSE CAST(listed_to_exclusive AS DATE)
                 END AS listed_to_raw
          FROM read_csv({q(str(g2_intervals))}, header=true, auto_detect=true)
        )
        SELECT r.exchange,r.code,r.listed_from,
               CASE WHEN r.listed_to_raw IS NULL OR r.listed_to_raw > DATE {q(end)} THEN NULL ELSE r.listed_to_raw END AS listed_to_exclusive
        FROM raw r
        JOIN feature_symbols s ON r.exchange=s.exchange AND r.code=s.code
        WHERE r.listed_from <= DATE {q(end)}
          AND (r.listed_to_raw IS NULL OR r.listed_to_raw > DATE {q(start)})
        ORDER BY r.exchange,r.code,r.listed_from
      ) TO {q(str(lifecycle_out))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    con.execute(f'CREATE TEMP VIEW features_p AS SELECT * FROM read_parquet({q(str(features_out))})')
    con.execute(f'CREATE TEMP VIEW market_p AS SELECT * FROM read_parquet({q(str(market_out))})')
    con.execute(f'CREATE TEMP VIEW lifecycle_p AS SELECT * FROM read_parquet({q(str(lifecycle_out))})')

    feature_stats = one_row(con, f"""
      SELECT count(*)::BIGINT AS row_count,
             count(DISTINCT (trade_date,exchange,code))::BIGINT AS unique_keys,
             count(DISTINCT trade_date)::BIGINT AS decision_days,
             min(trade_date) AS date_min,max(trade_date) AS date_max,
             count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT AS outside_rows
      FROM features_p
    """)
    market_stats = one_row(con, f"""
      SELECT count(*)::BIGINT AS row_count,
             count(DISTINCT (trade_date,exchange,code))::BIGINT AS unique_keys,
             count(DISTINCT trade_date)::BIGINT AS market_days,
             min(trade_date) AS date_min,max(trade_date) AS date_max,
             count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT AS outside_rows,
             count(*) FILTER(WHERE open IS NULL OR close IS NULL OR factor IS NULL)::BIGINT AS null_required_rows
      FROM market_p
    """)
    lifecycle_stats = one_row(con, f"""
      SELECT count(*)::BIGINT AS row_count,
             min(listed_from) AS listed_from_min,max(listed_from) AS listed_from_max,
             max(listed_to_exclusive) AS listed_to_max,
             count(*) FILTER(WHERE listed_to_exclusive IS NOT NULL AND listed_to_exclusive>DATE {q(end)})::BIGINT AS post_oos_delist_rows
      FROM lifecycle_p
    """)
    structural = one_row(con, """
      WITH fd AS (SELECT DISTINCT trade_date FROM features_p),
           md AS (SELECT DISTINCT trade_date FROM market_p),
           missing_dates AS (SELECT fd.trade_date FROM fd LEFT JOIN md USING(trade_date) WHERE md.trade_date IS NULL),
           missing_symbols AS (
             SELECT DISTINCT f.exchange,f.code
             FROM features_p f
             LEFT JOIN lifecycle_p l ON f.exchange=l.exchange AND f.code=l.code
             WHERE l.code IS NULL
           )
      SELECT (SELECT count(*) FROM missing_dates)::BIGINT AS feature_dates_missing_market_calendar,
             (SELECT count(*) FROM missing_symbols)::BIGINT AS feature_symbols_missing_lifecycle
    """)

    if int(feature_stats['row_count']) <= 0 or int(feature_stats['row_count']) != int(feature_stats['unique_keys']):
        raise ValueError(f'OOS feature population invalid: {feature_stats}')
    if str(feature_stats['date_min']) != start or str(feature_stats['date_max']) != end or int(feature_stats['outside_rows']) != 0:
        raise ValueError(f'OOS feature date boundary invalid: {feature_stats}')
    if int(market_stats['row_count']) <= 0 or int(market_stats['row_count']) != int(market_stats['unique_keys']):
        raise ValueError(f'OOS market population invalid: {market_stats}')
    if str(market_stats['date_min']) != start or str(market_stats['date_max']) != end or int(market_stats['outside_rows']) != 0:
        raise ValueError(f'OOS market date boundary invalid: {market_stats}')
    if int(market_stats['null_required_rows']) != 0:
        raise ValueError(f'OOS market required values missing: {market_stats}')
    if int(lifecycle_stats['post_oos_delist_rows']) != 0:
        raise ValueError(f'lifecycle output leaks post-OOS delisting information: {lifecycle_stats}')
    if int(structural['feature_dates_missing_market_calendar']) != 0 or int(structural['feature_symbols_missing_lifecycle']) != 0:
        raise ValueError(f'OOS physical bundle structural readiness failed: {structural}')

    data_hashes = {
        outputs['features']: sha256_file(features_out),
        outputs['market']: sha256_file(market_out),
        outputs['lifecycle']: sha256_file(lifecycle_out),
    }
    manifest = {
        'schema_version': 1,
        'status': 'PHYSICALLY_OOS_ONLY_PRE_PREDICTION_NON_LABEL',
        'boundary_contract_fingerprint': contract['fingerprint'],
        'source_cv_authorization_fingerprint': source_fp,
        'decision_start': start,
        'decision_end': end,
        'final_lockbox_start': lockbox,
        'source_artifacts': basis['inputs'],
        'feature_columns': feature_columns,
        'features': feature_stats,
        'market': market_stats,
        'lifecycle': lifecycle_stats,
        'structural_readiness': structural,
        'data_sha256': data_hashes,
        'guards': {
            'broad_feature_matrix_available_downstream': False,
            'broad_g3_available_downstream': False,
            'raw_g5_available_downstream': False,
            'raw_g2_available_downstream': False,
            'post_oos_feature_rows': 0,
            'post_oos_market_rows': 0,
            'post_oos_lifecycle_delist_rows': 0,
            'oos_prediction_executed': False,
            'oos_label_constructed': False,
            'oos_label_value_read': False,
            'model_loaded': False,
            'authorization_consumed': False,
            'fit_retrain_tune_reselect_executed': False,
            'final_lockbox_accessed': False,
            'business_metrics_computed': False,
        },
    }
    manifest_path = out / outputs['manifest']
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    hashes = {**data_hashes, outputs['manifest']: sha256_file(manifest_path)}
    (out / outputs['hashes']).write_text(json.dumps(hashes, sort_keys=True, indent=2) + '\n', encoding='utf-8')

    print(json.dumps({
        'status': manifest['status'],
        'boundary_contract_fingerprint': contract['fingerprint'],
        'feature_rows': int(feature_stats['row_count']),
        'feature_days': int(feature_stats['decision_days']),
        'market_rows': int(market_stats['row_count']),
        'market_days': int(market_stats['market_days']),
        'lifecycle_rows': int(lifecycle_stats['row_count']),
        'post_oos_rows': 0,
        'structural_readiness': structural,
        'authorization_consumed': False,
        'oos_prediction_executed': False,
        'oos_label_constructed': False,
        'final_lockbox_accessed': False,
        'data_sha256': data_hashes,
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
