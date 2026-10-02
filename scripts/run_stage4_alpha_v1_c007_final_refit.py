#!/usr/bin/env python3
from __future__ import annotations

import argparse, gc, hashlib, json, math, os, pickle, time, warnings
from pathlib import Path

EXPECTED_AUTH = '7d5f88013329973c6c446d9210adbb9e60ba04a9fb615098e21318f1ab053295'
SOURCE_CV_AUTH = '2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c'
EXPECTED_SCOPE = 'RESEARCH_ONLY_C007_FINAL_DEVELOPMENT_REFIT_EXACT_AUTHORIZATION_7D5F88013329973C6C446D9210ADBB9E60BA04A9FB615098E21318F1AB053295'


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def qi(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def canonical_hash(x: object) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--matrix', required=True)
    ap.add_argument('--labels', required=True)
    ap.add_argument('--authorization', required=True)
    ap.add_argument('--source-cv-authorization', required=True)
    ap.add_argument('--accepted-state', required=True)
    ap.add_argument('--work-dir', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    import duckdb
    import numpy as np
    import pyarrow as pa
    import scipy
    import sklearn
    from sklearn.ensemble import HistGradientBoostingRegressor

    auth = json.loads(Path(args.authorization).read_text(encoding='utf-8'))
    source = json.loads(Path(args.source_cv_authorization).read_text(encoding='utf-8'))
    state = json.loads(Path(args.accepted_state).read_text(encoding='utf-8'))
    if auth['fingerprint'] != EXPECTED_AUTH or canonical_hash(auth['fingerprint_basis']) != EXPECTED_AUTH:
        raise ValueError('final-refit authorization mismatch')
    if source['fingerprint'] != SOURCE_CV_AUTH or canonical_hash(source['fingerprint_basis']) != SOURCE_CV_AUTH:
        raise ValueError('source development-CV authorization mismatch')
    p = state['permissions']
    if not (p['model_fit_allowed'] is True and p['development_final_refit_allowed'] is True and p['model_fit_scope'] == EXPECTED_SCOPE):
        raise ValueError('accepted state does not authorize exact C007 final refit')
    if p['oos_label_access_allowed'] or p['lockbox_label_access_allowed'] or p['live_signal_allowed'] or p['main_merge_allowed'] or p['authoritative_model_output_allowed']:
        raise ValueError('sealed permission unexpectedly open')

    basis = auth['fingerprint_basis']
    selected = basis['selected_candidate']
    source_c007 = next(c for c in source['fingerprint_basis']['candidate_catalog'] if c['candidate_id'] == 'C007')
    if selected['candidate_id'] != 'C007' or selected['params'] != source_c007['params'] or selected['family'] != source_c007['family']:
        raise ValueError('C007 identity drift')
    if basis['fit_execution']['fit_count_exact'] != 1 or basis['fit_execution']['authorization_single_use'] is not True:
        raise ValueError('fit-count authorization mismatch')

    runtime = {
        'python': os.sys.version.split()[0],
        'numpy': np.__version__,
        'scipy': scipy.__version__,
        'scikit_learn': sklearn.__version__,
        'pyarrow': pa.__version__,
        'duckdb': duckdb.__version__,
        'threads': {k: os.getenv(k) for k in ['OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS']},
    }
    expected_runtime = basis['runtime']
    for k in ['python', 'numpy', 'scipy', 'scikit_learn', 'pyarrow', 'duckdb']:
        if runtime[k] != expected_runtime[k]:
            raise ValueError(f'runtime mismatch {k}: {runtime[k]} != {expected_runtime[k]}')
    if runtime['threads'] != expected_runtime['thread_env']:
        raise ValueError(f'thread runtime mismatch {runtime["threads"]}')

    matrix = Path(args.matrix)
    labels = Path(args.labels)
    if sha256_file(matrix) != basis['authority']['feature_matrix_sha256']:
        raise ValueError('feature matrix hash mismatch')
    if sha256_file(labels) != basis['authority']['development_labels_sha256']:
        raise ValueError('development label hash mismatch')

    work = Path(args.work_dir)
    out = Path(args.out)
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    joined = work / 'joined_development.parquet'

    features = source['fingerprint_basis']['feature_columns']
    roles = source['fingerprint_basis']['feature_roles']
    continuous = list(roles['continuous_clip_train_only'])
    binary = set(roles['binary_missing_indicators'])
    financial = set(roles['financial_signed_log1p'])
    if basis['preprocessing']['contract_source'] != 'INHERIT_EXACT_FEATURE_COLUMNS_AND_ROLES_FROM_AUTHORIZATION_2056EAE94770E9AFA65367999ADF05F57E799C6E6F2E88B501791F02B587706C':
        raise ValueError('preprocessing source mismatch')

    (work / 'duckdb-tmp').mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute('PRAGMA threads=4')
    con.execute("PRAGMA memory_limit='7GB'")
    con.execute(f"PRAGMA temp_directory={q(str(work / 'duckdb-tmp'))}")
    feat_sql = ',\n'.join(f'm.{qi(c)} AS {qi(c)}' for c in features)
    con.execute(f"""
      COPY (
        SELECT CAST(m.trade_date AS DATE) AS trade_date,
               upper(CAST(m.exchange AS VARCHAR)) AS exchange,
               lpad(CAST(m.code AS VARCHAR),6,'0') AS code,
               {feat_sql},
               CAST(l.valid_label_20d AS BOOLEAN) AS valid_label_20d,
               CAST(l.excess_return_20d AS DOUBLE) AS excess_return_20d
        FROM read_parquet({q(str(matrix))}) m
        JOIN read_parquet({q(str(labels))}) l
          ON CAST(m.trade_date AS DATE)=CAST(l.trade_date AS DATE)
         AND upper(CAST(m.exchange AS VARCHAR))=upper(CAST(l.exchange AS VARCHAR))
         AND lpad(CAST(m.code AS VARCHAR),6,'0')=lpad(CAST(l.code AS VARCHAR),6,'0')
        WHERE CAST(m.trade_date AS DATE) BETWEEN DATE '2015-01-05' AND DATE '2022-12-30'
        ORDER BY trade_date,exchange,code
      ) TO {q(str(joined))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    rows, unique_keys, dmin, dmax, fit_rows, fit_dmax = con.execute(
        f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date),count(*) FILTER(WHERE valid_label_20d),max(trade_date) FILTER(WHERE valid_label_20d) FROM read_parquet({q(str(joined))})"
    ).fetchone()
    pop = basis['training_population']
    if not (rows == unique_keys == 5197648 and fit_rows == pop['expected_fit_rows'] == 5103016):
        raise ValueError(f'population mismatch rows={rows} unique={unique_keys} fit_rows={fit_rows}')
    if str(dmin) != pop['feature_date_start'] or str(dmax) != pop['feature_date_end'] or str(fit_dmax) != pop['expected_latest_valid_20d_decision']:
        raise ValueError(f'date mismatch {dmin}..{dmax} fit_max={fit_dmax}')

    bad_binary = 0
    if binary:
        bad_expr = ' + '.join(f"sum(CASE WHEN {qi(c)} IS NULL OR CAST({qi(c)} AS DOUBLE) NOT IN (0.0,1.0) THEN 1 ELSE 0 END)" for c in sorted(binary))
        bad_binary = con.execute(f"SELECT {bad_expr} FROM read_parquet({q(str(joined))}) WHERE valid_label_20d").fetchone()[0]
    if bad_binary != 0:
        raise ValueError(f'binary indicator violations={bad_binary}')

    def xbase(c: str) -> str:
        z = qi(c)
        if c in financial:
            return f"CASE WHEN {z} IS NULL THEN NULL ELSE sign(CAST({z} AS DOUBLE))*ln(1+abs(CAST({z} AS DOUBLE))) END"
        return f"CAST({z} AS DOUBLE)"

    levels = [r[0] for r in con.execute(
        f"SELECT DISTINCT CAST(regime_state AS VARCHAR) FROM read_parquet({q(str(joined))}) WHERE valid_label_20d AND regime_state IS NOT NULL ORDER BY 1"
    ).fetchall()]
    agg = []
    for c in continuous:
        e = xbase(c)
        agg += [
            f"quantile_cont({e},0.001) AS {qi(c+'__q001')}",
            f"quantile_cont({e},0.999) AS {qi(c+'__q999')}",
            f"median({e}) AS {qi(c+'__median')}",
        ]
    vals = con.execute(f"SELECT {','.join(agg)} FROM read_parquet({q(str(joined))}) WHERE valid_label_20d").fetchone()
    stats = {}
    j = 0
    for c in continuous:
        lo, hi, med = vals[j], vals[j + 1], vals[j + 2]
        j += 3
        if med is None:
            raise ValueError(f'all-missing continuous feature {c}')
        stats[c] = {'q001': None if lo is None else float(lo), 'q999': None if hi is None else float(hi), 'median': float(med)}

    def feature_sql() -> tuple[list[str], list[str]]:
        exprs: list[str] = []
        names: list[str] = []
        for c in features:
            if c == 'regime_state':
                for i, lev in enumerate(levels):
                    exprs.append(f"CASE WHEN CAST(regime_state AS VARCHAR)={q(str(lev))} THEN 1.0 ELSE 0.0 END")
                    names.append(f'regime__{i}')
                known = ','.join(q(str(x)) for x in levels)
                exprs.append("CASE WHEN regime_state IS NULL THEN 1.0 ELSE 0.0 END" if not levels else f"CASE WHEN regime_state IS NULL OR CAST(regime_state AS VARCHAR) NOT IN ({known}) THEN 1.0 ELSE 0.0 END")
                names.append('regime__unknown')
            elif c in binary:
                exprs.append(f"CAST({qi(c)} AS DOUBLE)")
                names.append(c)
            elif c in continuous:
                st = stats[c]
                e = xbase(c)
                exprs.append(f"CASE WHEN {e} IS NULL THEN NULL WHEN {e}<{repr(st['q001'])} THEN {repr(st['q001'])} WHEN {e}>{repr(st['q999'])} THEN {repr(st['q999'])} ELSE {e} END")
                names.append(c)
            else:
                raise ValueError(f'unclassified feature {c}')
        return exprs, names

    exprs, names = feature_sql()
    select_features = ', '.join(f"{e} AS {qi(n)}" for e, n in zip(exprs, names))
    fit_table = con.execute(
        f"SELECT {select_features},CAST(excess_return_20d AS DOUBLE) AS excess_return_20d FROM read_parquet({q(str(joined))}) WHERE valid_label_20d ORDER BY trade_date,exchange,code"
    ).fetch_arrow_table()
    if fit_table.num_rows != fit_rows:
        raise ValueError('transformed fit-row mismatch')
    X = np.empty((fit_table.num_rows, len(names)), dtype=np.float32)
    for col_idx, nm in enumerate(names):
        X[:, col_idx] = np.asarray(fit_table.column(nm).combine_chunks().to_numpy(zero_copy_only=False), dtype=np.float32)
    y = np.asarray(fit_table.column('excess_return_20d').combine_chunks().to_numpy(zero_copy_only=False), dtype=np.float32)
    del fit_table
    gc.collect()
    if not np.isfinite(y).all() or np.isinf(X).any():
        raise ValueError('nonfinite final fit data')

    model = HistGradientBoostingRegressor(**selected['params'])
    fit_count = 0
    started = time.monotonic()
    with warnings.catch_warnings(record=True) as ws:
        warnings.simplefilter('always')
        model.fit(X, y)
        fit_count += 1
        warning_text = [f"{w.category.__name__}:{w.message}" for w in ws]
    fit_seconds = time.monotonic() - started
    if fit_count != 1 or int(getattr(model, 'n_iter_', -1)) != int(selected['params']['max_iter']):
        raise ValueError(f'final refit count/iterations mismatch count={fit_count} n_iter={getattr(model, "n_iter_", None)}')
    if int(getattr(model, 'n_features_in_', -1)) != len(names):
        raise ValueError('model feature-count mismatch')

    model_path = out / 'model.pkl'
    with model_path.open('wb') as f:
        pickle.dump(model, f, protocol=5)

    sentinel_table = con.execute(
        f"SELECT trade_date,exchange,code,{select_features} FROM read_parquet({q(str(joined))}) WHERE valid_label_20d ORDER BY trade_date,exchange,code LIMIT 256"
    ).fetch_arrow_table()
    Xs = np.empty((sentinel_table.num_rows, len(names)), dtype=np.float32)
    for col_idx, nm in enumerate(names):
        Xs[:, col_idx] = np.asarray(sentinel_table.column(nm).combine_chunks().to_numpy(zero_copy_only=False), dtype=np.float32)
    keys = [
        [str(sentinel_table.column('trade_date')[i].as_py()), str(sentinel_table.column('exchange')[i].as_py()), str(sentinel_table.column('code')[i].as_py())]
        for i in range(sentinel_table.num_rows)
    ]
    sentinel_pred = np.asarray(model.predict(Xs), dtype=np.float64)
    if sentinel_pred.shape[0] != 256 or not np.isfinite(sentinel_pred).all():
        raise ValueError('invalid sentinel predictions')
    sentinel_keys_sha = canonical_hash(keys)
    sentinel_pred_sha = canonical_hash([round(float(x), 12) for x in sentinel_pred])
    sentinel_feature_sha = hashlib.sha256(np.ascontiguousarray(Xs).tobytes()).hexdigest()
    del sentinel_table, Xs, X, y
    gc.collect()

    preprocess = {
        'schema_version': 1,
        'gate': 'STAGE4_ALPHA_V1_C007_FINAL_DEVELOPMENT_REFIT_PREPROCESSOR',
        'authorization_fingerprint': EXPECTED_AUTH,
        'source_cv_authorization_fingerprint': SOURCE_CV_AUTH,
        'fit_population': 'DEVELOPMENT_ONLY_VALID_LABEL_20D',
        'prepared_rows': int(rows),
        'fit_rows': int(fit_rows),
        'feature_date_min': str(dmin),
        'feature_date_max': str(dmax),
        'fit_date_max': str(fit_dmax),
        'feature_columns': features,
        'model_input_feature_names': names,
        'model_input_feature_count': len(names),
        'regime_levels': levels,
        'continuous_stats': stats,
        'binary_indicator_violations': int(bad_binary),
        'financial_transform': 'SIGNED_LOG1P',
        'continuous_clip_quantiles': [0.001, 0.999],
        'hgb_missing_policy': 'NATIVE_NAN',
        'scaling': 'NONE',
        'oos_rows_used': False,
        'lockbox_rows_used': False,
    }
    preprocess['stats_sha256'] = canonical_hash({
        'fit_rows': preprocess['fit_rows'],
        'regime_levels': levels,
        'continuous_stats': stats,
        'model_input_feature_names': names,
    })
    prep_path = out / 'final_preprocess_manifest.json'
    prep_path.write_text(json.dumps(preprocess, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    execution_head = os.environ.get('EXECUTION_HEAD')
    if not execution_head:
        raise ValueError('EXECUTION_HEAD is required')

    execution = {
        'schema_version': 1,
        'gate': 'STAGE4_ALPHA_V1_C007_FINAL_DEVELOPMENT_REFIT_EXACT_HEAD',
        'execution_head': execution_head,
        'authorization_fingerprint': EXPECTED_AUTH,
        'selected_candidate': 'C007',
        'candidate_family': selected['family'],
        'candidate_params': selected['params'],
        'fit_count': fit_count,
        'fit_rows': int(fit_rows),
        'fit_date_start': str(dmin),
        'fit_date_end': str(fit_dmax),
        'model_input_feature_count': len(names),
        'fit_seconds': fit_seconds,
        'warnings': warning_text,
        'runtime': runtime,
        'feature_matrix_sha256': sha256_file(matrix),
        'development_labels_sha256': sha256_file(labels),
        'preprocess_manifest_sha256': sha256_file(prep_path),
        'model_sha256': sha256_file(model_path),
        'model_pickle_protocol': 5,
        'model_n_iter': int(model.n_iter_),
        'sentinel_row_count': 256,
        'sentinel_keys_sha256': sentinel_keys_sha,
        'sentinel_features_float32_sha256': sentinel_feature_sha,
        'sentinel_predictions_round12_sha256': sentinel_pred_sha,
        'training_prediction_performance_report_created': False,
        'final_development_refit_executed': True,
        'oos_accessed': False,
        'lockbox_accessed': False,
        'live_signal_allowed': False,
        'main_merge_allowed': False,
        'authoritative_model_output': False,
        'model_output_status': 'RESEARCH_ONLY_NON_AUTHORITATIVE',
        'next_gate': 'SEPARATE_GOVERNANCE_ACCEPTANCE_BEFORE_OOS_AUTHORIZATION',
    }
    (out / 'final_refit_execution_manifest.json').write_text(json.dumps(execution, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'gate': execution['gate'],
        'execution_head': execution['execution_head'],
        'selected_candidate': 'C007',
        'fit_count': fit_count,
        'fit_rows': int(fit_rows),
        'model_sha256': execution['model_sha256'],
        'final_development_refit_executed': True,
        'oos_accessed': False,
        'lockbox_accessed': False,
        'authoritative_model_output': False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
