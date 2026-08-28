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


def canon_hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    ).hexdigest()


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def sql_file_list(paths: list[Path]) -> str:
    return '[' + ','.join(q(str(p)) for p in paths) + ']'


def rows_as_dicts(cur) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--contract', required=True)
    ap.add_argument('--oof-root', required=True)
    ap.add_argument('--g3-root', required=True)
    ap.add_argument('--g4-root', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    import duckdb

    contract_path = Path(args.contract)
    contract = json.loads(contract_path.read_text(encoding='utf-8'))
    expected_fp = contract['fingerprint']
    actual_fp = canon_hash(contract['fingerprint_basis'])
    if actual_fp != expected_fp:
        raise ValueError(f'contract fingerprint mismatch expected={expected_fp} actual={actual_fp}')

    basis = contract['fingerprint_basis']
    scope = basis['scope']
    if not all([
        scope['oos_prediction_forbidden'],
        scope['oos_label_access_forbidden'],
        scope['model_load_forbidden'],
        scope['fit_retrain_tune_reselect_forbidden'],
        scope['final_lockbox_access_forbidden'],
    ]):
        raise ValueError('development-only permission guard is not fully closed')

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    oof_hits = list(Path(args.oof_root).rglob('oof_predictions.parquet'))
    if len(oof_hits) != 1:
        raise ValueError(f'expected exactly one C007 OOF parquet, got {oof_hits}')
    oof = oof_hits[0]
    oof_sha = sha256_file(oof)
    expected_oof_sha = basis['inputs']['c007_oof']['oof_file_sha256']
    if oof_sha != expected_oof_sha:
        raise ValueError(f'C007 OOF SHA mismatch expected={expected_oof_sha} actual={oof_sha}')

    year_re = re.compile(r'(2015|2016|2017|2018|2019|2020|2021|2022)')
    g3_all = sorted(Path(args.g3_root).rglob('*.csv.gz'))
    g3_files = [p for p in g3_all if year_re.search(p.name)]
    if not g3_files:
        raise ValueError('no 2015-2022 G3 CSV.GZ files found')
    if any(re.search(r'202[3-9]|203\d', p.name) for p in g3_files):
        raise ValueError('post-2022 G3 file entered development audit')

    g4_files = sorted(Path(args.g4_root).rglob('g4_state_shard*.csv.gz'))
    if len(g4_files) != 16:
        raise ValueError(f'expected 16 G4 state shards, found {len(g4_files)}')

    g3_cols = """{
      'exchange':'VARCHAR','code':'VARCHAR','trade_date':'DATE','open':'DOUBLE','high':'DOUBLE','low':'DOUBLE',
      'close':'DOUBLE','volume_shares':'DOUBLE','amount_cny':'DOUBLE'
    }"""
    g4_cols = """{
      'exchange':'VARCHAR','code':'VARCHAR','trade_date':'DATE','tradable':'INTEGER','risk_warning':'INTEGER',
      'preclose':'DOUBLE','pct_chg':'DOUBLE','limit_rule':'VARCHAR','limit_up_rate':'DOUBLE','limit_down_rate':'DOUBLE','evidence':'VARCHAR'
    }"""

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='6GB'")
    con.execute(f"PRAGMA temp_directory={q(str(out / 'duckdb-tmp'))}")

    g3_list = sql_file_list(g3_files)
    g4_list = sql_file_list(g4_files)
    cutoff = scope['development_decision_date_max']

    con.execute(f"""
      CREATE TEMP VIEW g3 AS
      SELECT exchange, code, trade_date, open, high, low, close, volume_shares, amount_cny
      FROM read_csv({g3_list}, header=true, columns={g3_cols}, compression='gzip', union_by_name=true)
      WHERE trade_date BETWEEN DATE '2015-01-05' AND DATE {q(cutoff)}
    """)
    con.execute(f"""
      CREATE TEMP VIEW g4_dev AS
      SELECT exchange, code, trade_date, tradable, risk_warning, preclose, pct_chg,
             limit_rule, limit_up_rate, limit_down_rate
      FROM read_csv({g4_list}, header=true, columns={g4_cols}, compression='gzip', union_by_name=true)
      WHERE trade_date BETWEEN DATE '2015-01-05' AND DATE {q(cutoff)}
    """)

    max_g3 = str(scalar(con, 'SELECT max(trade_date) FROM g3'))
    max_g4 = str(scalar(con, 'SELECT max(trade_date) FROM g4_dev'))
    if max_g3 > cutoff or max_g4 > cutoff:
        raise ValueError(f'development date guard failed g3={max_g3} g4={max_g4} cutoff={cutoff}')

    universe_rows = int(scalar(con, 'SELECT count(*) FROM g3 WHERE close > 0 AND close < 70'))
    expected_universe_rows = int(basis['population_reconciliation']['expected_development_universe_rows'])
    if universe_rows != expected_universe_rows:
        raise ValueError(f'development universe row mismatch expected={expected_universe_rows} actual={universe_rows}')

    con.execute('''
      CREATE TEMP TABLE calendar_map AS
      WITH d AS (SELECT DISTINCT trade_date FROM g3),
      x AS (SELECT trade_date, lead(trade_date) OVER (ORDER BY trade_date) AS next_trade_date FROM d)
      SELECT * FROM x
    ''')

    con.execute(f"""
      CREATE TEMP VIEW oof AS
      SELECT trade_date, exchange, code, split_id, prediction,
             excess_return_20d, excess_return_5d, stock_total_return_20d, benchmark_return_20d
      FROM read_parquet({q(str(oof))})
    """)

    oof_max = str(scalar(con, 'SELECT max(trade_date) FROM oof'))
    if oof_max > cutoff:
        raise ValueError(f'OOF contains post-development date {oof_max}')
    if int(scalar(con, 'SELECT count(*) FROM oof WHERE prediction IS NULL OR NOT isfinite(prediction)')) != 0:
        raise ValueError('OOF contains invalid prediction')

    con.execute('''
      CREATE TEMP TABLE joined AS
      SELECT
        o.*,
        cm.next_trade_date AS entry_date,
        d.close AS decision_close,
        d.volume_shares AS decision_volume_shares,
        gd.tradable AS decision_tradable,
        gd.risk_warning AS decision_risk_warning,
        e.open AS entry_open,
        e.high AS entry_high,
        e.low AS entry_low,
        e.close AS entry_close,
        e.volume_shares AS entry_volume_shares,
        ge.tradable AS entry_tradable,
        ge.risk_warning AS entry_risk_warning,
        ge.preclose AS entry_preclose,
        ge.pct_chg AS entry_pct_chg,
        ge.limit_rule AS entry_limit_rule,
        ge.limit_up_rate AS entry_limit_up_rate,
        ge.limit_down_rate AS entry_limit_down_rate
      FROM oof o
      LEFT JOIN calendar_map cm ON o.trade_date = cm.trade_date
      LEFT JOIN g3 d ON o.trade_date=d.trade_date AND o.exchange=d.exchange AND o.code=d.code
      LEFT JOIN g4_dev gd ON o.trade_date=gd.trade_date AND o.exchange=gd.exchange AND o.code=gd.code
      LEFT JOIN g3 e ON cm.next_trade_date=e.trade_date AND o.exchange=e.exchange AND o.code=e.code
      LEFT JOIN g4_dev ge ON cm.next_trade_date=ge.trade_date AND o.exchange=ge.exchange AND o.code=ge.code
    ''')

    join_checks = rows_as_dicts(con.execute('''
      SELECT
        count(*) AS rows,
        sum(entry_date IS NULL)::BIGINT AS missing_entry_date,
        sum(decision_close IS NULL)::BIGINT AS missing_decision_g3,
        sum(decision_tradable IS NULL)::BIGINT AS missing_decision_g4,
        sum(entry_open IS NULL)::BIGINT AS missing_entry_g3,
        sum(entry_tradable IS NULL)::BIGINT AS missing_entry_g4,
        min(trade_date) AS min_decision_date,
        max(trade_date) AS max_decision_date,
        max(entry_date) AS max_entry_date,
        count(DISTINCT trade_date) AS decision_days,
        count(DISTINCT split_id) AS split_count
      FROM joined
    '''))[0]
    for k in ['missing_entry_date','missing_decision_g3','missing_decision_g4','missing_entry_g3','missing_entry_g4']:
        if int(join_checks[k]) != 0:
            raise ValueError(f'join integrity failed {k}={join_checks[k]}')
    if str(join_checks['max_entry_date']) > cutoff:
        raise ValueError(f'entry date crossed development cutoff: {join_checks["max_entry_date"]}')

    con.execute('''
      CREATE TEMP TABLE audit_rows AS
      SELECT *,
        (decision_close < 2.0)::INTEGER AS decision_low_price_lt2,
        (decision_tradable = 0)::INTEGER AS decision_nontradable,
        (decision_risk_warning = 1)::INTEGER AS decision_risk_warning_flag,
        (entry_tradable = 0)::INTEGER AS entry_nontradable,
        (entry_risk_warning = 1)::INTEGER AS entry_risk_warning_flag,
        (coalesce(entry_volume_shares,0) <= 0)::INTEGER AS entry_zero_volume,
        (abs(entry_high-entry_low) <= 1e-12)::INTEGER AS entry_one_price,
        (
          abs(entry_high-entry_low) <= 1e-12
          AND entry_volume_shares > 0
          AND abs(entry_close - floor(entry_preclose*(1.0+entry_limit_up_rate)*100.0 + 0.5)/100.0) <= 0.005001
        )::INTEGER AS entry_one_price_limit_up,
        (
          abs(entry_high-entry_low) <= 1e-12
          AND entry_volume_shares > 0
          AND abs(entry_close - floor(entry_preclose*(1.0-entry_limit_down_rate)*100.0 + 0.5)/100.0) <= 0.005001
        )::INTEGER AS entry_one_price_limit_down,
        ((entry_tradable = 0) OR (coalesce(entry_volume_shares,0) <= 0))::INTEGER AS hard_unexecutable_entry,
        (
          (decision_tradable = 0) OR (decision_risk_warning = 1) OR
          (entry_tradable = 0) OR (coalesce(entry_volume_shares,0) <= 0) OR
          (entry_risk_warning = 1) OR
          (abs(entry_high-entry_low) <= 1e-12 AND entry_volume_shares > 0
             AND abs(entry_close - floor(entry_preclose*(1.0+entry_limit_up_rate)*100.0 + 0.5)/100.0) <= 0.005001)
        )::INTEGER AS high_execution_risk_union
      FROM joined
    ''')

    con.execute('''
      CREATE TEMP TABLE ranked AS
      SELECT *,
        row_number() OVER (PARTITION BY trade_date ORDER BY prediction DESC, exchange ASC, code ASC) AS pred_rank,
        count(*) OVER (PARTITION BY trade_date) AS date_n,
        dense_rank() OVER (PARTITION BY split_id ORDER BY trade_date) - 1 AS test_session_index_within_split
      FROM audit_rows
    ''')
    con.execute('''
      CREATE TEMP TABLE selected AS
      SELECT c.coverage, r.*, ceil(c.coverage * r.date_n)::BIGINT AS bucket_n
      FROM ranked r
      CROSS JOIN (VALUES (0.05::DOUBLE),(0.10::DOUBLE),(0.20::DOUBLE)) c(coverage)
      WHERE r.pred_rank <= ceil(c.coverage * r.date_n)
    ''')

    flag_cols = [
      'decision_low_price_lt2','decision_nontradable','decision_risk_warning_flag',
      'entry_nontradable','entry_risk_warning_flag','entry_zero_volume','entry_one_price',
      'entry_one_price_limit_up','entry_one_price_limit_down','hard_unexecutable_entry',
      'high_execution_risk_union'
    ]

    base_select = ',\n'.join(f'avg({c}) AS {c}_share, sum({c})::BIGINT AS {c}_count' for c in flag_cols)
    base = rows_as_dicts(con.execute(f'''
      SELECT count(*)::BIGINT AS rows, count(DISTINCT trade_date)::BIGINT AS decision_days,
             min(trade_date) AS date_min, max(trade_date) AS date_max,
             avg(excess_return_20d) AS mean_excess_return_20d,
             {base_select}
      FROM audit_rows
    '''))[0]

    daily_aggs = ',\n'.join(f'avg({c}) AS {c}_share' for c in flag_cols)
    con.execute(f'''
      CREATE TEMP TABLE daily_exposure AS
      SELECT coverage, split_id, trade_date, test_session_index_within_split,
             count(*)::BIGINT AS selected_rows, max(bucket_n)::BIGINT AS bucket_n,
             avg(excess_return_20d) AS mean_excess_return_20d,
             {daily_aggs}
      FROM selected
      GROUP BY coverage, split_id, trade_date, test_session_index_within_split
      ORDER BY coverage, trade_date
    ''')

    daily_csv = out / 'c007_top_bucket_daily_exposure.csv'
    con.execute(f"COPY daily_exposure TO {q(str(daily_csv))} (HEADER, DELIMITER ',')")

    def summarize_selected(where_sql: str) -> list[dict[str, Any]]:
        row_aggs = ',\n'.join(
            f'avg({c}) AS {c}_share, sum({c})::BIGINT AS {c}_count' for c in flag_cols
        )
        daily_mean_aggs = ',\n'.join(
            f'avg({c}_share) AS daily_mean_{c}_share' for c in flag_cols
        )
        core = rows_as_dicts(con.execute(f'''
          SELECT coverage,
                 count(*)::BIGINT AS selected_rows,
                 count(DISTINCT trade_date)::BIGINT AS decision_days,
                 avg(excess_return_20d) AS mean_excess_return_20d,
                 sum(CASE WHEN hard_unexecutable_entry=1 THEN excess_return_20d ELSE 0 END)/count(*) AS hard_unexecutable_contribution_to_mean_excess,
                 sum(CASE WHEN high_execution_risk_union=1 THEN excess_return_20d ELSE 0 END)/count(*) AS high_risk_union_contribution_to_mean_excess,
                 avg(CASE WHEN hard_unexecutable_entry=1 THEN excess_return_20d END) AS mean_excess_hard_unexecutable_rows,
                 avg(CASE WHEN hard_unexecutable_entry=0 THEN excess_return_20d END) AS mean_excess_other_rows,
                 avg(CASE WHEN high_execution_risk_union=1 THEN excess_return_20d END) AS mean_excess_high_risk_union_rows,
                 avg(CASE WHEN high_execution_risk_union=0 THEN excess_return_20d END) AS mean_excess_low_risk_rows,
                 {row_aggs}
          FROM selected
          WHERE {where_sql}
          GROUP BY coverage
          ORDER BY coverage
        '''))
        daily = rows_as_dicts(con.execute(f'''
          SELECT coverage, {daily_mean_aggs}
          FROM daily_exposure
          WHERE {where_sql}
          GROUP BY coverage
          ORDER BY coverage
        '''))
        dm = {round(float(r['coverage']), 4): r for r in daily}
        for r in core:
            key = round(float(r['coverage']), 4)
            r.update({k:v for k,v in dm[key].items() if k != 'coverage'})
        return core

    all_dates = summarize_selected('1=1')
    nonoverlap = summarize_selected('(test_session_index_within_split % 20) = 0')

    base_low = float(base['decision_low_price_lt2_share'])
    base_hard = float(base['hard_unexecutable_entry_share'])
    base_high = float(base['high_execution_risk_union_share'])
    for group in (all_dates, nonoverlap):
        for r in group:
            r['decision_low_price_lt2_risk_ratio_vs_all_oof'] = (
                float(r['decision_low_price_lt2_share']) / base_low if base_low > 0 else None
            )
            r['hard_unexecutable_entry_risk_ratio_vs_all_oof'] = (
                float(r['hard_unexecutable_entry_share']) / base_hard if base_hard > 0 else None
            )
            r['high_execution_risk_union_ratio_vs_all_oof'] = (
                float(r['high_execution_risk_union_share']) / base_high if base_high > 0 else None
            )

    result = {
      'schema_version': 1,
      'audit_id': basis['audit_id'],
      'status': 'PASS_DEVELOPMENT_ONLY_EXECUTABILITY_AUDIT',
      'contract_fingerprint': expected_fp,
      'permissions': {
        'development_only': True,
        'oos_prediction_performed': False,
        'oos_label_access_performed': False,
        'model_loaded': False,
        'fit_retrain_tune_reselect_performed': False,
        'final_lockbox_access_performed': False
      },
      'input_verification': {
        'c007_oof_file_sha256': oof_sha,
        'g3_files_2015_2022': len(g3_files),
        'g4_state_shards': len(g4_files),
        'max_g3_row_retained': max_g3,
        'max_g4_row_retained': max_g4,
        'development_universe_rows_recomputed': universe_rows,
        'development_universe_rows_expected': expected_universe_rows
      },
      'join_integrity': join_checks,
      'baseline_all_c007_oof_valid20_rows': base,
      'top_bucket_all_oof_test_dates': all_dates,
      'top_bucket_nonoverlap_20_session_anchor': nonoverlap,
      'interpretation_guard': {
        'selection_population': 'frozen C007 OOF valid_label_20d rows, matching original development CV economic diagnostic',
        'hard_unexecutable_entry': 'entry tradable=0 or entry volume_shares<=0',
        'one_price_limit_up': 'diagnostic exact-cent limit-price proxy using frozen G4 preclose/rate and G3 one-price positive-volume bar',
        'contribution_metrics_are_not_a_replacement_or_backfill_backtest': True,
        'no_outcome_dependent_model_change_allowed': True
      }
    }

    result_path = out / 'c007_development_executability_audit.json'
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    hashes = {
      result_path.name: sha256_file(result_path),
      daily_csv.name: sha256_file(daily_csv),
      contract_path.name: sha256_file(contract_path),
      'oof_predictions.parquet': oof_sha
    }
    (out / 'artifact_hashes.json').write_text(json.dumps(hashes, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
