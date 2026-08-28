#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def row(con, sql: str) -> dict[str, Any]:
    cur = con.execute(sql)
    cols = [x[0] for x in cur.description]
    return dict(zip(cols, cur.fetchone()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True)
    ap.add_argument("--package-dir", required=True)
    ap.add_argument("--source-verification", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import duckdb

    errors: list[str] = []
    checks: dict[str, bool] = {}
    out_path = Path(args.out)

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks[name] = bool(condition)
        if not condition:
            errors.append(name + (f": {detail}" if detail else ""))

    try:
        contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
        basis = contract["fingerprint_basis"]
        check("contract_fingerprint", canonical_hash(basis) == contract["fingerprint"])
        check("contract_status", contract.get("status") == "BOUNDARY_COMPILER_DEVELOPMENT_ONLY_NON_EVALUATION")
        start, end = basis["scope"]["development_start"], basis["scope"]["development_end"]
        outputs = basis["outputs"]
        package = Path(args.package_dir)

        source = json.loads(Path(args.source_verification).read_text(encoding="utf-8"))
        check("source_verification_status", source.get("status") == "VERIFIED")
        for key in ["c007_oof", "stage2_g3", "stage2_g4"]:
            expected = basis["inputs"][key]
            got = source.get("artifacts", {}).get(key, {})
            check(f"source_{key}_artifact_id", int(got.get("artifact_id", -1)) == int(expected["artifact_id"]))
            check(f"source_{key}_archive_digest", got.get("archive_digest") == expected["artifact_digest"])
            check(f"source_{key}_verified", got.get("verified") is True)

        g3, g4, oof = package / outputs["g3"], package / outputs["g4"], package / outputs["c007_oof"]
        manifest_path, hashes_path = package / outputs["manifest"], package / outputs["hashes"]
        for p in [g3, g4, oof, manifest_path, hashes_path]:
            check(f"exists_{p.name}", p.is_file())

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        preliminary_hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
        check("manifest_status", manifest.get("status") == "PHYSICALLY_DEVELOPMENT_ONLY")
        check("manifest_contract_binding", manifest.get("boundary_contract_fingerprint") == contract["fingerprint"])
        check("manifest_start", manifest.get("development_start") == start)
        check("manifest_end", manifest.get("development_end") == end)
        guards = manifest.get("physical_guards", {})
        check("guard_min_inside", guards.get("all_output_min_dates_gte_development_start") is True)
        check("guard_max_inside", guards.get("all_output_max_dates_lte_development_end") is True)
        check("guard_post_2022_zero", int(guards.get("post_2022_output_rows", -1)) == 0)
        for key in [
            "downstream_requires_broad_g3_artifact",
            "downstream_requires_broad_g4_artifact",
            "oos_prediction_executed",
            "oos_label_accessed",
            "model_loaded",
            "fit_retrain_tune_reselect_executed",
            "final_lockbox_evaluation_executed",
            "business_metrics_computed",
        ]:
            check(f"guard_{key}_false", guards.get(key) is False)

        for p in [g3, g4, oof, manifest_path]:
            check(f"preliminary_hash_{p.name}", preliminary_hashes.get(p.name) == sha256_file(p))
        check("oof_byte_identity", sha256_file(oof) == basis["inputs"]["c007_oof"]["oof_file_sha256"])

        con = duckdb.connect()
        con.execute("PRAGMA threads=2")
        con.execute(f"CREATE TEMP VIEW g3p AS SELECT * FROM read_parquet({q(str(g3))})")
        con.execute(f"CREATE TEMP VIEW g4p AS SELECT * FROM read_parquet({q(str(g4))})")
        con.execute(f"CREATE TEMP VIEW oofp AS SELECT * FROM read_parquet({q(str(oof))})")

        g3_stats = row(con, f'SELECT count(*)::BIGINT AS "rows",count(DISTINCT (trade_date,exchange,code))::BIGINT AS unique_keys,min(trade_date) AS date_min,max(trade_date) AS date_max,count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT AS outside_rows FROM g3p')
        g4_stats = row(con, f'SELECT count(*)::BIGINT AS "rows",count(DISTINCT (trade_date,exchange,code))::BIGINT AS unique_keys,min(trade_date) AS date_min,max(trade_date) AS date_max,count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT AS outside_rows FROM g4p')
        oof_stats = row(con, f'SELECT count(*)::BIGINT AS "rows",count(DISTINCT trade_date)::BIGINT AS decision_days,count(DISTINCT split_id)::BIGINT AS split_count,min(trade_date) AS date_min,max(trade_date) AS date_max,count(*) FILTER(WHERE trade_date<DATE {q(start)} OR trade_date>DATE {q(end)})::BIGINT AS outside_rows FROM oofp')

        for name, stats in [("g3", g3_stats), ("g4", g4_stats), ("oof", oof_stats)]:
            check(f"{name}_outside_rows_zero", int(stats["outside_rows"]) == 0, str(stats))
            check(f"{name}_min_inside", str(stats["date_min"]) >= start, str(stats))
            check(f"{name}_max_inside", str(stats["date_max"]) <= end, str(stats))
        check("g3_unique_keys", int(g3_stats["rows"]) == int(g3_stats["unique_keys"]))
        check("g4_unique_keys", int(g4_stats["rows"]) == int(g4_stats["unique_keys"]))

        oexp = basis["inputs"]["c007_oof"]
        check("oof_rows", int(oof_stats["rows"]) == int(oexp["expected_rows"]))
        check("oof_decision_days", int(oof_stats["decision_days"]) == int(oexp["expected_decision_days"]))
        check("oof_split_count", int(oof_stats["split_count"]) == int(oexp["expected_split_count"]))

        universe_rows = int(con.execute("SELECT count(*) FROM g3p WHERE close>0 AND close<70").fetchone()[0])
        check("development_universe_rows", universe_rows == int(basis["population_invariants"]["expected_development_universe_rows"]))

        con.execute("""
          CREATE TEMP TABLE calendar_map AS
          WITH d AS (SELECT DISTINCT trade_date FROM g3p)
          SELECT trade_date,lead(trade_date) OVER(ORDER BY trade_date) AS next_trade_date FROM d
        """)
        structural = row(con, """
          WITH o AS (
            SELECT trade_date,upper(exchange) AS exchange,lpad(CAST(code AS VARCHAR),6,'0') AS code FROM oofp
          ), j AS (
            SELECT o.trade_date,cm.next_trade_date,d.close AS decision_close,gd.tradable AS decision_tradable,
                   e.open AS entry_open,ge.tradable AS entry_tradable
            FROM o
            LEFT JOIN calendar_map cm ON o.trade_date=cm.trade_date
            LEFT JOIN g3p d ON o.trade_date=d.trade_date AND o.exchange=d.exchange AND o.code=d.code
            LEFT JOIN g4p gd ON o.trade_date=gd.trade_date AND o.exchange=gd.exchange AND o.code=gd.code
            LEFT JOIN g3p e ON cm.next_trade_date=e.trade_date AND o.exchange=e.exchange AND o.code=e.code
            LEFT JOIN g4p ge ON cm.next_trade_date=ge.trade_date AND o.exchange=ge.exchange AND o.code=ge.code
          )
          SELECT count(*)::BIGINT AS "rows",
                 sum(next_trade_date IS NULL)::BIGINT AS missing_entry_date,
                 sum(decision_close IS NULL)::BIGINT AS missing_decision_g3,
                 sum(decision_tradable IS NULL)::BIGINT AS missing_decision_g4,
                 sum(entry_open IS NULL)::BIGINT AS missing_entry_g3,
                 sum(entry_tradable IS NULL)::BIGINT AS missing_entry_g4,
                 max(next_trade_date) AS max_entry_date
          FROM j
        """)
        for key in ["missing_entry_date", "missing_decision_g3", "missing_decision_g4", "missing_entry_g3", "missing_entry_g4"]:
            check(f"structural_{key}_zero", int(structural[key]) == 0, str(structural))
        check("structural_entry_inside_boundary", str(structural["max_entry_date"]) <= end, str(structural))

        check("manifest_g3_rows_match", int(manifest["g3"]["rows"]) == int(g3_stats["rows"]))
        check("manifest_g4_rows_match", int(manifest["g4"]["rows"]) == int(g4_stats["rows"]))
        check("manifest_oof_rows_match", int(manifest["c007_oof"]["rows"]) == int(oof_stats["rows"]))
        check("manifest_universe_match", int(manifest["g3"]["development_universe_rows"]) == universe_rows)

        result = {
            "schema_version": 1,
            "pass": not errors,
            "status": "PASS" if not errors else "FAIL",
            "boundary_contract_fingerprint": contract["fingerprint"],
            "checks": checks,
            "failed_checks": errors,
            "g3": g3_stats,
            "g4": g4_stats,
            "c007_oof": oof_stats,
            "development_universe_rows": universe_rows,
            "structural_readiness": structural,
            "post_development_rows_observed": int(g3_stats["outside_rows"]) + int(g4_stats["outside_rows"]) + int(oof_stats["outside_rows"]),
            "oos_prediction_executed": False,
            "oos_label_accessed": False,
            "model_loaded": False,
            "final_lockbox_evaluation_executed": False,
        }
    except Exception as exc:
        errors.append(f"exception: {type(exc).__name__}: {exc}")
        result = {"schema_version": 1, "pass": False, "status": "FAIL", "checks": checks, "failed_checks": errors}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
