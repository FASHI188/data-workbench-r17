#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
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


def floats_close(a: object, b: object, atol: float = 1e-12, rtol: float = 1e-12) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        aa, bb = float(a), float(b)
    except Exception:
        return False
    if math.isnan(aa) or math.isnan(bb):
        return math.isnan(aa) and math.isnan(bb)
    return math.isclose(aa, bb, abs_tol=atol, rel_tol=rtol)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--matrix', required=True)
    ap.add_argument('--labels', required=True)
    ap.add_argument('--authorization', required=True)
    ap.add_argument('--source-cv-authorization', required=True)
    ap.add_argument('--accepted-state', required=True)
    ap.add_argument('--execution-dir', required=True)
    ap.add_argument('--work-dir', required=True)
    args = ap.parse_args()

    import duckdb
    import numpy as np
    import pyarrow as pa
    import scipy
    import sklearn
    from sklearn.ensemble import HistGradientBoostingRegressor

    matrix = Path(args.matrix)
    labels = Path(args.labels)
    auth_path = Path(args.authorization)
    source_path = Path(args.source_cv_authorization)
    state_path = Path(args.accepted_state)
    out = Path(args.execution_dir)
    work = Path(args.work_dir)
    (work / 'duckdb-tmp').mkdir(parents=True, exist_ok=True)

    auth = json.loads(auth_path.read_text(encoding='utf-8'))
    source = json.loads(source_path.read_text(encoding='utf-8'))
    state = json.loads(state_path.read_text(encoding='utf-8'))
    prep = json.loads((out / 'final_preprocess_manifest.json').read_text(encoding='utf-8'))
    exe = json.loads((out / 'final_refit_execution_manifest.json').read_text(encoding='utf-8'))

    checks: dict[str, bool] = {}
    checks['authorization_fingerprint_exact'] = (
        auth['fingerprint'] == EXPECTED_AUTH
        and canonical_hash(auth['fingerprint_basis']) == EXPECTED_AUTH
        and auth['fingerprint_basis']['fit_execution']['fit_count_exact'] == 1
        and auth['fingerprint_basis']['fit_execution']['authorization_single_use'] is True
    )
    checks['source_cv_authority_exact'] = (
        source['fingerprint'] == SOURCE_CV_AUTH
        and canonical_hash(source['fingerprint_basis']) == SOURCE_CV_AUTH
        and source['fingerprint_basis']['post_selection']['final_refit_requires_separate_gate_after_candidate_selection'] is True
        and source['fingerprint_basis']['post_selection']['oos_access_still_forbidden'] is True
    )
    p = state['permissions']
    checks['accepted_single_use_scope_exact'] = (
        p['model_fit_allowed'] is True
        and p['development_final_refit_allowed'] is True
        and p['model_fit_scope'] == EXPECTED_SCOPE
        and p['oos_label_access_allowed'] is False
        and p['lockbox_label_access_allowed'] is False
        and p['live_signal_allowed'] is False
        and p['main_merge_allowed'] is False
        and p['authoritative_model_output_allowed'] is False
    )

    basis = auth['fingerprint_basis']
    selected = basis['selected_candidate']
    source_c007 = next(c for c in source['fingerprint_basis']['candidate_catalog'] if c['candidate_id'] == 'C007')
    checks['selected_candidate_exact'] = (
        selected['candidate_id'] == 'C007'
        and selected['family'] == 'HIST_GRADIENT_BOOSTING_V1'
        and selected['params'] == source_c007['params']
        and selected['selection_frozen'] is True
        and selected['posthoc_parameter_changes_forbidden'] is True
    )

    runtime = exe['runtime']
    expected_runtime = basis['runtime']
    checks['runtime_exact'] = (
        all(runtime[k] == expected_runtime[k] for k in ['python', 'numpy', 'scipy', 'scikit_learn', 'pyarrow', 'duckdb'])
        and runtime['threads'] == expected_runtime['thread_env']
        and os.sys.version.split()[0] == expected_runtime['python']
        and np.__version__ == expected_runtime['numpy']
        and scipy.__version__ == expected_runtime['scipy']
        and sklearn.__version__ == expected_runtime['scikit_learn']
        and pa.__version__ == expected_runtime['pyarrow']
        and duckdb.__version__ == expected_runtime['duckdb']
    )

    checks['immutable_input_hashes_exact'] = (
        sha256_file(matrix) == basis['authority']['feature_matrix_sha256'] == exe['feature_matrix_sha256']
        and sha256_file(labels) == basis['authority']['development_labels_sha256'] == exe['development_labels_sha256']
    )

    execution_head = os.environ.get('EXECUTION_HEAD')
    checks['exact_head_bound'] = bool(execution_head and exe['execution_head'] == execution_head)
    checks['execution_semantics_exact'] = (
        exe['gate'] == 'STAGE4_ALPHA_V1_C007_FINAL_DEVELOPMENT_REFIT_EXACT_HEAD'
        and exe['authorization_fingerprint'] == EXPECTED_AUTH
        and exe['selected_candidate'] == 'C007'
        and exe['candidate_family'] == selected['family']
        and exe['candidate_params'] == selected['params']
        and exe['fit_count'] == 1
        and exe['fit_rows'] == 5103016
        and exe['fit_date_start'] == '2015-01-05'
        and exe['fit_date_end'] == '2022-12-02'
        and exe['model_pickle_protocol'] == 5
        and exe['training_prediction_performance_report_created'] is False
        and exe['final_development_refit_executed'] is True
        and exe['oos_accessed'] is False
        and exe['lockbox_accessed'] is False
        and exe['live_signal_allowed'] is False
        and exe['main_merge_allowed'] is False
        and exe['authoritative_model_output'] is False
        and exe['model_output_status'] == 'RESEARCH_ONLY_NON_AUTHORITATIVE'
        and exe['next_gate'] == 'SEPARATE_GOVERNANCE_ACCEPTANCE_BEFORE_OOS_AUTHORIZATION'
    )

    model_path = out / 'model.pkl'
    with model_path.open('rb') as f:
        model = pickle.load(f)
    checks['model_identity_exact'] = (
        type(model) is HistGradientBoostingRegressor
        and all(model.get_params()[k] == v for k, v in selected['params'].items())
        and int(getattr(model, 'n_iter_', -1)) == 200
        and int(getattr(model, 'n_features_in_', -1)) == exe['model_input_feature_count'] == prep['model_input_feature_count']
        and sha256_file(model_path) == exe['model_sha256']
        and sha256_file(out / 'final_preprocess_manifest.json') == exe['preprocess_manifest_sha256']
    )

    features = source['fingerprint_basis']['feature_columns']
    roles = source['fingerprint_basis']['feature_roles']
    continuous = list(roles['continuous_clip_train_only'])
    binary = set(roles['binary_missing_indicators'])
    financial = set(roles['financial_signed_log1p'])

    con = duckdb.connect()
    con.execute('PRAGMA threads=4')
    con.execute("PRAGMA memory_limit='7GB'")
    con.execute(f"PRAGMA temp_directory={q(str(work / 'duckdb-tmp'))}")
    audit_joined = work / 'audit_joined_development.parquet'
    feat_sql = ','.join(f'm.{qi(c)} AS {qi(c)}' for c in features)
    con.execute(f"""
      COPY (
        SELECT CAST(m.trade_date AS DATE) AS trade_date,
               upper(CAST(m.exchange AS VARCHAR)) AS exchange,
               lpad(CAST(m.code AS VARCHAR),6,'0') AS code,
               {feat_sql},
               CAST(l.valid_label_20d AS BOOLEAN) AS valid_label_20d,
               CAST(l.excess_return_20d AS DOUBLE) AS excess_return_20d
        FROM read_parquet({q(str(matrix))}) m
        INNER JOIN read_parquet({q(str(labels))}) l
          ON CAST(m.trade_date AS DATE)=CAST(l.trade_date AS DATE)
         AND upper(CAST(m.exchange AS VARCHAR))=upper(CAST(l.exchange AS VARCHAR))
         AND lpad(CAST(m.code AS VARCHAR),6,'0')=lpad(CAST(l.code AS VARCHAR),6,'0')
        WHERE CAST(m.trade_date AS DATE)>=DATE '2015-01-05'
          AND CAST(m.trade_date AS DATE)<=DATE '2022-12-30'
      ) TO {q(str(audit_joined))} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    rows, ukeys, dmin, dmax, fit_rows, fit_dmax = con.execute(
        f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date),count(*) FILTER(WHERE valid_label_20d),max(trade_date) FILTER(WHERE valid_label_20d) FROM read_parquet({q(str(audit_joined))})"
    ).fetchone()
    checks['population_recomputed'] = (
        rows == ukeys == 5197648
        and fit_rows == 5103016
        and str(dmin) == '2015-01-05'
        and str(dmax) == '2022-12-30'
        and str(fit_dmax) == '2022-12-02'
        and prep['prepared_rows'] == 5197648
        and prep['fit_rows'] == 5103016
        and prep['feature_date_min'] == '2015-01-05'
        and prep['feature_date_max'] == '2022-12-30'
        and prep['fit_date_max'] == '2022-12-02'
    )

    bad_binary = 0
    if binary:
        bad_expr = ' + '.join(
            f"sum(CASE WHEN {qi(c)} IS NULL OR CAST({qi(c)} AS DOUBLE) NOT IN (0.0,1.0) THEN 1 ELSE 0 END)"
            for c in sorted(binary)
        )
        bad_binary = con.execute(
            f"SELECT {bad_expr} FROM read_parquet({q(str(audit_joined))}) WHERE valid_label_20d"
        ).fetchone()[0]
    checks['binary_features_recomputed'] = bad_binary == 0 == prep['binary_indicator_violations']

    def audit_xbase(c: str) -> str:
        z = qi(c)
        if c in financial:
            return f"sign(CAST({z} AS DOUBLE))*ln(1+abs(CAST({z} AS DOUBLE)))"
        return f"CAST({z} AS DOUBLE)"

    levels = [r[0] for r in con.execute(
        f"SELECT DISTINCT CAST(regime_state AS VARCHAR) FROM read_parquet({q(str(audit_joined))}) WHERE valid_label_20d AND regime_state IS NOT NULL ORDER BY CAST(regime_state AS VARCHAR)"
    ).fetchall()]
    checks['regime_levels_recomputed'] = levels == prep['regime_levels']

    agg_parts: list[str] = []
    for idx, c in enumerate(continuous):
        e = audit_xbase(c)
        agg_parts.extend([
            f"quantile_cont({e}, CAST(0.001 AS DOUBLE)) AS q{idx}_lo",
            f"quantile_cont({e}, CAST(0.999 AS DOUBLE)) AS q{idx}_hi",
            f"median({e}) AS q{idx}_med",
        ])
    vals = con.execute(
        f"SELECT {','.join(agg_parts)} FROM read_parquet({q(str(audit_joined))}) WHERE valid_label_20d"
    ).fetchone()
    stat_ok = True
    independent_stats: dict[str, dict[str, float | None]] = {}
    j = 0
    for c in continuous:
        lo, hi, med = vals[j], vals[j + 1], vals[j + 2]
        j += 3
        independent_stats[c] = {
            'q001': None if lo is None else float(lo),
            'q999': None if hi is None else float(hi),
            'median': None if med is None else float(med),
        }
        got = prep['continuous_stats'][c]
        stat_ok &= floats_close(got['q001'], lo) and floats_close(got['q999'], hi) and floats_close(got['median'], med)
    checks['continuous_stats_recomputed'] = bool(stat_ok)

    names: list[str] = []
    for c in features:
        if c == 'regime_state':
            names.extend([f'regime__{i}' for i in range(len(levels))])
            names.append('regime__unknown')
        elif c in binary or c in continuous:
            names.append(c)
        else:
            raise ValueError(f'unclassified feature {c}')
    checks['feature_order_recomputed'] = names == prep['model_input_feature_names'] and len(names) == prep['model_input_feature_count']

    sentinel_raw_cols = ','.join(qi(c) for c in features)
    sentinel = con.execute(
        f"SELECT trade_date,exchange,code,{sentinel_raw_cols} FROM read_parquet({q(str(audit_joined))}) WHERE valid_label_20d ORDER BY trade_date,exchange,code LIMIT 256"
    ).fetch_arrow_table()
    keys = [
        [str(sentinel.column('trade_date')[i].as_py()), str(sentinel.column('exchange')[i].as_py()), str(sentinel.column('code')[i].as_py())]
        for i in range(sentinel.num_rows)
    ]
    X = np.empty((sentinel.num_rows, len(names)), dtype=np.float32)
    col_out = 0
    for c in features:
        if c == 'regime_state':
            raw = sentinel.column(c).combine_chunks().to_pylist()
            known = set(levels)
            for lev in levels:
                X[:, col_out] = np.asarray([1.0 if x is not None and str(x) == str(lev) else 0.0 for x in raw], dtype=np.float32)
                col_out += 1
            X[:, col_out] = np.asarray([1.0 if x is None or str(x) not in known else 0.0 for x in raw], dtype=np.float32)
            col_out += 1
        elif c in binary:
            raw = np.asarray(sentinel.column(c).combine_chunks().to_numpy(zero_copy_only=False), dtype=np.float64)
            X[:, col_out] = raw.astype(np.float32)
            col_out += 1
        elif c in continuous:
            raw = np.asarray(sentinel.column(c).combine_chunks().to_numpy(zero_copy_only=False), dtype=np.float64)
            if c in financial:
                raw = np.sign(raw) * np.log1p(np.abs(raw))
            st = prep['continuous_stats'][c]
            raw = np.where(np.isnan(raw), np.nan, np.clip(raw, st['q001'], st['q999']))
            X[:, col_out] = raw.astype(np.float32)
            col_out += 1
    pred = np.asarray(model.predict(X), dtype=np.float64)
    checks['sentinel_recomputed_independently'] = (
        sentinel.num_rows == 256
        and col_out == len(names)
        and not np.isinf(X).any()
        and np.isfinite(pred).all()
        and canonical_hash(keys) == exe['sentinel_keys_sha256']
        and hashlib.sha256(np.ascontiguousarray(X).tobytes()).hexdigest() == exe['sentinel_features_float32_sha256']
        and canonical_hash([round(float(x), 12) for x in pred]) == exe['sentinel_predictions_round12_sha256']
    )

    recomputed_stats_sha = canonical_hash({
        'fit_rows': int(fit_rows),
        'regime_levels': levels,
        'continuous_stats': independent_stats,
        'model_input_feature_names': names,
    })
    checks['preprocess_hash_semantics_recomputed'] = recomputed_stats_sha == prep['stats_sha256']
    checks['preprocess_contract_exact'] = (
        prep['authorization_fingerprint'] == EXPECTED_AUTH
        and prep['source_cv_authorization_fingerprint'] == SOURCE_CV_AUTH
        and prep['fit_population'] == 'DEVELOPMENT_ONLY_VALID_LABEL_20D'
        and prep['financial_transform'] == 'SIGNED_LOG1P'
        and prep['continuous_clip_quantiles'] == [0.001, 0.999]
        and prep['hgb_missing_policy'] == 'NATIVE_NAN'
        and prep['scaling'] == 'NONE'
        and prep['oos_rows_used'] is False
        and prep['lockbox_rows_used'] is False
    )

    expected_before_audit = {'model.pkl', 'final_preprocess_manifest.json', 'final_refit_execution_manifest.json'}
    existing_before = {p.name for p in out.iterdir() if p.is_file()}
    checks['no_unapproved_output_before_audit'] = existing_before == expected_before_audit

    failed = [k for k, v in checks.items() if not v]
    report = {
        'schema_version': 1,
        'gate': 'STAGE4_ALPHA_V1_C007_FINAL_DEVELOPMENT_REFIT_INDEPENDENT_AUDIT',
        'pass': not failed,
        'execution_head': exe['execution_head'],
        'authorization_fingerprint': EXPECTED_AUTH,
        'selected_candidate': 'C007',
        'fit_rows_recomputed': int(fit_rows),
        'fit_date_max_recomputed': str(fit_dmax),
        'model_sha256_recomputed': sha256_file(model_path),
        'preprocess_manifest_sha256_recomputed': sha256_file(out / 'final_preprocess_manifest.json'),
        'sentinel_row_count': 256,
        'checks': checks,
        'failed_checks': failed,
        'training_performance_metric_computed': False,
        'model_fit_executed_by_audit': False,
        'oos_accessed': False,
        'lockbox_accessed': False,
        'live_signal_allowed': False,
        'main_merge_allowed': False,
        'authoritative_model_output': False,
    }
    audit_path = out / 'final_refit_independent_audit.json'
    audit_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    artifact_hashes = {
        name: sha256_file(out / name)
        for name in ['model.pkl', 'final_preprocess_manifest.json', 'final_refit_execution_manifest.json', 'final_refit_independent_audit.json']
    }
    (out / 'artifact_hashes.json').write_text(json.dumps(artifact_hashes, sort_keys=True, indent=2) + '\n', encoding='utf-8')

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['pass'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
