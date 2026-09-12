#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

PREREG_FP="0e9b79a406e3a7789ade5b93878cd4276c5f424b0f0e9e4906048b9254e4cac3"
BOUNDARY_FP="67e8555d3a9212a003a8293dc381cce0f7294917ef72875fed3218f240e0c255"
PRED_SHA256="66a039aa76e4b1962049e3e0d41a43fb1f6c626d934a552f871f91bd27fe01da"
PRED_ROWS=1515811
OOS_START="2023-01-03";OOS_END="2024-12-31";LATEST_VALID20="2024-12-03";LOCKBOX_START="2025-01-02"
IMPLEMENTATION_FP="a9addd6eefc82737e5a39c7828dc9b68a5d4336e2ee3e8ebeaeee1d628014045"
BOUNDARY_FILES={"market":"oos_market.parquet","execution_state":"oos_execution_state.parquet","lifecycle":"oos_lifecycle.parquet","manifest":"oos_physical_boundary_manifest.json","independent_audit":"oos_physical_boundary_independent_audit.json","hashes":"artifact_hashes.json"}

def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

def one(con, sql: str) -> dict[str, Any]:
    cur = con.execute(sql)
    return dict(zip([x[0] for x in cur.description], cur.fetchone()))

def validate_prediction_input(predictions: Path, synthetic: bool = False) -> dict[str, Any]:
    import duckdb

    if not synthetic and sha256_file(predictions) != PRED_SHA256:
        raise ValueError("immutable prediction file sha256 mismatch")
    con = duckdb.connect()
    stat = one(
        con,
        f"SELECT count(*)::BIGINT rows,count(DISTINCT (CAST(trade_date AS DATE),upper(CAST(exchange AS VARCHAR)),lpad(CAST(code AS VARCHAR),6,'0')))::BIGINT unique_keys,min(CAST(trade_date AS DATE)) min_date,max(CAST(trade_date AS DATE)) max_date,count(*) FILTER(WHERE prediction IS NULL OR NOT isfinite(CAST(prediction AS DOUBLE)))::BIGINT invalid_predictions FROM read_parquet({q(str(predictions))})",
    )
    if int(stat["rows"]) <= 0 or int(stat["rows"]) != int(stat["unique_keys"]) or int(stat["invalid_predictions"]) != 0:
        raise ValueError("prediction population invalid")
    if not synthetic:
        if int(stat["rows"]) != PRED_ROWS or str(stat["min_date"]) != OOS_START or str(stat["max_date"]) != OOS_END:
            raise ValueError("immutable prediction identity mismatch")
    return stat

def validate_physical_boundary(root: Path, synthetic: bool = False) -> dict[str, Path]:
    expected = {BOUNDARY_FILES[k] for k in BOUNDARY_FILES}
    missing = [name for name in expected if not (root / name).is_file()]
    if missing:
        raise ValueError(f"physical boundary files missing: {missing}")
    hashes = json.loads((root / BOUNDARY_FILES["hashes"]).read_text(encoding="utf-8"))
    required_hashed = {BOUNDARY_FILES["market"], BOUNDARY_FILES["execution_state"], BOUNDARY_FILES["lifecycle"], BOUNDARY_FILES["manifest"], BOUNDARY_FILES["independent_audit"]}
    if not synthetic:
        for name in required_hashed:
            if hashes.get(name) != sha256_file(root / name):
                raise ValueError(f"physical boundary file hash mismatch: {name}")
    manifest = json.loads((root / BOUNDARY_FILES["manifest"]).read_text(encoding="utf-8"))
    audit = json.loads((root / BOUNDARY_FILES["independent_audit"]).read_text(encoding="utf-8"))
    if not synthetic:
        if manifest.get("status") != "PHYSICALLY_OOS_ONLY_PRE_PREDICTION_NON_LABEL":
            raise ValueError("physical boundary manifest status mismatch")
        if manifest.get("boundary_contract_fingerprint") != BOUNDARY_FP:
            raise ValueError("physical boundary fingerprint mismatch")
        if manifest.get("boundary_implementation") != "V1_2_LIFECYCLE_AWARE_CANDIDATE_READINESS":
            raise ValueError("physical boundary implementation mismatch")
        ready = manifest.get("runtime_candidate_path_readiness", {})
        if int(ready.get("candidate_rows", -1)) != 1453359 or int(ready.get("entry_lifecycle_inactive_rows", -1)) != 52 or int(ready.get("exit_lifecycle_inactive_rows", -1)) != 1217:
            raise ValueError("physical boundary candidate readiness identity mismatch")
        for k, v in ready.items():
            if k not in {"candidate_rows", "entry_lifecycle_inactive_rows", "exit_lifecycle_inactive_rows"} and int(v) != 0:
                raise ValueError(f"physical boundary active-lifecycle readiness failure: {k}")
        if audit.get("pass") is not True or audit.get("failed_checks") != [] or int(audit.get("post_oos_rows_observed", -1)) != 0:
            raise ValueError("physical boundary independent audit mismatch")
    return {k: root / v for k, v in BOUNDARY_FILES.items()}

def write_consumption_marker(out: Path, authorization: dict[str, Any], execution_head: str) -> Path:
    marker = out / "label_completion_consumption.json"
    if marker.exists():
        raise ValueError("label-completion consumption marker already exists; reexecution forbidden")
    payload = {
        "schema_version": 1,
        "status": "CONSUMED",
        "authorization_fingerprint": authorization["fingerprint"],
        "implementation_fingerprint": IMPLEMENTATION_FP,
        "preregistration_fingerprint": PREREG_FP,
        "execution_head": execution_head,
        "consumption_event": CONSUMPTION_EVENT,
        "consumed_at_utc": datetime.now(timezone.utc).isoformat(),
        "prediction_computation_executed": False,
        "model_loaded": False,
        "fit_executed": False,
        "final_lockbox_accessed": False,
    }
    marker.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return marker

def materialize_labels(
    predictions: Path,
    market: Path,
    lifecycle: Path,
    work: Path,
    *,
    expected_start: str,
    expected_end: str,
    latest_valid20: str,
    lockbox_start: str,
    consume_callback=None,
) -> tuple[Path, dict[str, Any]]:
    import duckdb

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='7GB'")
    tmp = work / "duckdb-label-tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"PRAGMA temp_directory={q(str(tmp))}")

    # Intentional parser repair: quote source identifiers and alias away from OPEN/CLOSE.
    probe = con.execute(f'SELECT CAST("close" AS DOUBLE) FROM read_parquet({q(str(market))}) LIMIT 1').fetchone()
    if probe is None:
        raise ValueError("market value probe returned no row")
    if consume_callback is not None:
        consume_callback()

    con.execute(
        f'''CREATE TEMP TABLE market AS
        SELECT upper(CAST(exchange AS VARCHAR)) AS exchange,
               lpad(CAST(code AS VARCHAR),6,'0') AS code,
               CAST(trade_date AS DATE) AS trade_date,
               CAST("open" AS DOUBLE) AS open_px,
               CAST("close" AS DOUBLE) AS close_px,
               CAST(factor AS DOUBLE) AS factor
        FROM read_parquet({q(str(market))})'''
    )
    mr, mn, mx = con.execute("SELECT count(*),min(trade_date),max(trade_date) FROM market").fetchone()
    if mr <= 0 or str(mn) != expected_start or str(mx) != expected_end or str(mx) >= lockbox_start:
        raise ValueError("market boundary mismatch")
    con.execute(
        f'''CREATE TEMP TABLE lifecycle AS
        SELECT upper(CAST(exchange AS VARCHAR)) AS exchange,
               lpad(CAST(code AS VARCHAR),6,'0') AS code,
               CAST(listed_from AS DATE) AS listed_from,
               CAST(listed_to_exclusive AS DATE) AS listed_to_exclusive
        FROM read_parquet({q(str(lifecycle))})'''
    )
    if con.execute(f"SELECT count(*) FROM lifecycle WHERE listed_to_exclusive IS NOT NULL AND listed_to_exclusive>DATE '{expected_end}'").fetchone()[0]:
        raise ValueError("lifecycle contains post-OOS information")
    con.execute(
        f'''CREATE TEMP TABLE decisions AS
        SELECT CAST(trade_date AS DATE) AS decision_date,
               upper(CAST(exchange AS VARCHAR)) AS exchange,
               lpad(CAST(code AS VARCHAR),6,'0') AS code
        FROM read_parquet({q(str(predictions))})'''
    )
    dr, du, dn, dx = con.execute("SELECT count(*),count(DISTINCT (decision_date,exchange,code)),min(decision_date),max(decision_date) FROM decisions").fetchone()
    if dr != du or str(dn) != expected_start or str(dx) != expected_end:
        raise ValueError("decision population mismatch")
    con.execute("CREATE TEMP TABLE calendar AS SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 session_idx FROM (SELECT DISTINCT trade_date FROM market) ORDER BY trade_date")
    con.execute("CREATE TEMP TABLE schedule AS SELECT d.*,c.session_idx,e.trade_date entry_date,x5.trade_date exit_date_5d,x20.trade_date exit_date_20d FROM decisions d JOIN calendar c ON c.trade_date=d.decision_date LEFT JOIN calendar e ON e.session_idx=c.session_idx+1 LEFT JOIN calendar x5 ON x5.session_idx=c.session_idx+5 LEFT JOIN calendar x20 ON x20.session_idx=c.session_idx+20")
    con.execute(
        f'''CREATE TEMP TABLE raw_labels AS
        SELECT s.decision_date,s.exchange,s.code,s.entry_date,s.exit_date_5d,s.exit_date_20d,
               ep.open_px entry_open_raw,ep.factor entry_factor,
               p5.close_px exit_close_5d_raw,p5.factor exit_factor_5d,
               p20.close_px exit_close_20d_raw,p20.factor exit_factor_20d,
               lc.listed_to_exclusive,
          CASE WHEN s.exit_date_5d IS NULL THEN 'PARTITION_BOUNDARY_INCOMPLETE_HORIZON'
               WHEN lc.listed_to_exclusive IS NOT NULL AND lc.listed_to_exclusive>s.decision_date AND lc.listed_to_exclusive<=s.exit_date_5d THEN 'DELISTING_HORIZON_CENSOR_NO_TERMINAL_IMPUTATION'
               WHEN ep.open_px IS NULL OR ep.open_px<=0 THEN 'MISSING_ENTRY_OPEN'
               WHEN p5.close_px IS NULL OR p5.close_px<=0 THEN 'MISSING_EXIT_CLOSE'
               ELSE 'VALID' END censor_reason_5d,
          CASE WHEN s.exit_date_20d IS NULL OR s.decision_date>DATE '{latest_valid20}' THEN 'PARTITION_BOUNDARY_INCOMPLETE_HORIZON'
               WHEN lc.listed_to_exclusive IS NOT NULL AND lc.listed_to_exclusive>s.decision_date AND lc.listed_to_exclusive<=s.exit_date_20d THEN 'DELISTING_HORIZON_CENSOR_NO_TERMINAL_IMPUTATION'
               WHEN ep.open_px IS NULL OR ep.open_px<=0 THEN 'MISSING_ENTRY_OPEN'
               WHEN p20.close_px IS NULL OR p20.close_px<=0 THEN 'MISSING_EXIT_CLOSE'
               ELSE 'VALID' END censor_reason_20d
        FROM schedule s
        LEFT JOIN market ep ON ep.exchange=s.exchange AND ep.code=s.code AND ep.trade_date=s.entry_date
        LEFT JOIN market p5 ON p5.exchange=s.exchange AND p5.code=s.code AND p5.trade_date=s.exit_date_5d
        LEFT JOIN market p20 ON p20.exchange=s.exchange AND p20.code=s.code AND p20.trade_date=s.exit_date_20d
        LEFT JOIN lifecycle lc ON lc.exchange=s.exchange AND lc.code=s.code AND s.decision_date>=lc.listed_from AND (lc.listed_to_exclusive IS NULL OR s.decision_date<lc.listed_to_exclusive)'''
    )
    con.execute("CREATE TEMP TABLE stock_returns AS SELECT *,CASE WHEN censor_reason_5d='VALID' THEN (exit_close_5d_raw*exit_factor_5d)/(entry_open_raw*entry_factor)-1 END stock_total_return_5d,CASE WHEN censor_reason_20d='VALID' THEN (exit_close_20d_raw*exit_factor_20d)/(entry_open_raw*entry_factor)-1 END stock_total_return_20d FROM raw_labels")
    con.execute("CREATE TEMP TABLE benchmarks AS SELECT decision_date,avg(stock_total_return_5d) FILTER(WHERE censor_reason_5d='VALID') benchmark_return_5d,avg(stock_total_return_20d) FILTER(WHERE censor_reason_20d='VALID') benchmark_return_20d FROM stock_returns GROUP BY decision_date")
    labels = work / "oos_labels.parquet"
    con.execute(
        f'''COPY (SELECT r.decision_date trade_date,r.exchange,r.code,r.entry_date,r.exit_date_5d,r.exit_date_20d,
                 r.censor_reason_5d='VALID' valid_label_5d,r.censor_reason_20d='VALID' valid_label_20d,
                 r.censor_reason_5d,r.censor_reason_20d,r.stock_total_return_5d,b.benchmark_return_5d,
                 CASE WHEN r.censor_reason_5d='VALID' THEN r.stock_total_return_5d-b.benchmark_return_5d END excess_return_5d,
                 r.stock_total_return_20d,b.benchmark_return_20d,
                 CASE WHEN r.censor_reason_20d='VALID' THEN r.stock_total_return_20d-b.benchmark_return_20d END excess_return_20d
          FROM stock_returns r JOIN benchmarks b USING(decision_date)
          ORDER BY trade_date,exchange,code)
        TO {q(str(labels))} (FORMAT PARQUET,COMPRESSION ZSTD)'''
    )
    rows, uniq, v20, mv, me = con.execute(f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),count(*) FILTER(WHERE valid_label_20d),max(trade_date) FILTER(WHERE valid_label_20d),max(exit_date_20d) FILTER(WHERE valid_label_20d) FROM read_parquet({q(str(labels))})").fetchone()
    if rows != dr or uniq != dr or (mv is not None and str(mv) > latest_valid20) or (me is not None and str(me) > expected_end):
        raise ValueError("label boundary mismatch")
    return labels, {
        "label_rows": int(rows),
        "valid_20d_rows": int(v20),
        "latest_valid_20d_decision": None if mv is None else str(mv),
        "latest_valid_20d_exit": None if me is None else str(me),
        "market_source_rows": int(mr),
        "market_source_min_date": str(mn),
        "market_source_max_date": str(mx),
    }

