#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

AUTH_FP = "d260f1179c6f0c8cac8e2900e11c8f4cc6439eedc5515e02a00b69abb332449d"
EXEC_FP = "224d9144d1989f021c29bb17ce13a6d2644b2d8992d604738b4e596a6907d177"
BOUNDARY_FP = "508f32767ecd12fab85e432e17eecb4f920822de1b3a5bef215e8e08d47bb8c8"
SOURCE_CV_AUTH_FP = "2056eae94770e9afa65367999adf05f57e799c6e6f2e88b501791f02b587706c"
MODEL_SHA = "e85aabf694799a16f8c5a1dea017e3489a9025ecf3d484d7a4f3fd931b0d702c"
PREPROCESS_SHA = "4b7833e4c4bdba9b956dba190f7337003ae944a624b59ddad7654b1457608330"
SOURCE_MATRIX_SHA = "c5fca80bc0f35c008590fe8f6cd7b8a16ab22e13b4978314a812f1ecb60b391c"
OOS_START = "2023-01-03"
OOS_END = "2024-12-31"
LATEST_VALID20 = "2024-12-03"
LOCKBOX_START = "2025-01-02"


def canonical_hash(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def close(a, b, tol=1e-12):
    return abs(float(a) - float(b)) <= tol + tol * max(abs(float(a)), abs(float(b)))


def handling_rate(d: str) -> float:
    return 0.0000341 if d >= "2023-08-28" else 0.0000487


def stamp_rate(d: str) -> float:
    return 0.0005 if d >= "2023-08-28" else 0.001


def roundtrip_cost(entry: str, exitd: str) -> float:
    return 0.003 + handling_rate(entry) + handling_rate(exitd) + stamp_rate(exitd)


def bootstrap(values, *, block=20, resamples=10000, seed=20260817):
    import numpy as np
    x = np.asarray(values, dtype=np.float64)
    if x.ndim != 1 or len(x) < block or not np.isfinite(x).all():
        raise ValueError("invalid bootstrap")
    rng = np.random.Generator(np.random.PCG64(seed))
    need = math.ceil(len(x) / block)
    max_start = len(x) - block + 1
    means = np.empty(resamples, dtype=np.float64)
    for i in range(resamples):
        starts = rng.integers(0, max_start, size=need)
        sample = np.concatenate([x[s:s + block] for s in starts])[: len(x)]
        means[i] = sample.mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def synthetic_self_test() -> int:
    import numpy as np
    x = np.linspace(0.002, 0.04, 80)
    a = bootstrap(x, resamples=250)
    b = bootstrap(x, resamples=250)
    assert a == b and a[0] > 0
    rows = [(0.9, "SSE", "600001", True), (0.8, "SSE", "600002", False), (0.7, "SSE", "600003", True)]
    top = sorted(rows, key=lambda r: (-r[0], r[1], r[2]))[:2]
    assert any(not r[3] for r in top)
    print(json.dumps({"synthetic_audit_self_test": "PASS", "bootstrap_ci": a, "economic_label_lookahead": False, "fit_calls": 0}))
    return 0


def main() -> int:
    if "--synthetic-self-test" in sys.argv:
        return synthetic_self_test()

    ap = argparse.ArgumentParser()
    for n in ["physical-boundary", "boundary-contract", "source-cv-authorization", "model", "preprocess", "authorization", "execution-contract", "predictions", "labels", "evaluation", "execution-dir", "execution-head", "out"]:
        ap.add_argument("--" + n, required=True)
    args = ap.parse_args()

    import duckdb
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq
    from scipy.stats import spearmanr

    out = Path(args.execution_dir)
    root = Path(args.physical_boundary)
    auth = json.loads(Path(args.authorization).read_text(encoding="utf-8"))
    exe = json.loads(Path(args.execution_contract).read_text(encoding="utf-8"))
    boundary = json.loads(Path(args.boundary_contract).read_text(encoding="utf-8"))
    source = json.loads(Path(args.source_cv_authorization).read_text(encoding="utf-8"))
    manifest = json.loads((out / "oos_execution_manifest.json").read_text(encoding="utf-8"))
    consumption = json.loads((out / "authorization_consumption.json").read_text(encoding="utf-8"))
    gate_actual = json.loads((out / "oos_gate_result.json").read_text(encoding="utf-8"))
    quarter_actual = json.loads((out / "oos_quarter_metrics.json").read_text(encoding="utf-8"))
    econ_actual = json.loads((out / "oos_economic_metrics.json").read_text(encoding="utf-8"))
    failures, checks = [], {}

    def ck(name, cond):
        ok = bool(cond)
        checks[name] = ok
        if not ok:
            failures.append(name)

    ck("authorization_fingerprint", auth.get("fingerprint") == AUTH_FP and canonical_hash(auth["fingerprint_basis"]) == AUTH_FP)
    ck("execution_contract_fingerprint", exe.get("fingerprint") == EXEC_FP and canonical_hash(exe["fingerprint_basis"]) == EXEC_FP and exe["fingerprint_basis"].get("version") == "V1.1")
    ck("boundary_contract_fingerprint", boundary.get("fingerprint") == BOUNDARY_FP and canonical_hash(boundary["fingerprint_basis"]) == BOUNDARY_FP)
    ck("source_cv_authorization_fingerprint", source.get("fingerprint") == SOURCE_CV_AUTH_FP and canonical_hash(source["fingerprint_basis"]) == SOURCE_CV_AUTH_FP)
    ck("economic_selection_contract", exe["fingerprint_basis"]["execution_semantics"].get("economic_selection_population") == "ALL_PREDICTED_ROWS_ON_REBALANCE_DATE_BEFORE_ANY_LABEL_VALIDITY_FILTER" and exe["fingerprint_basis"]["metric_semantics"].get("bucket_size") == "CEIL_COVERAGE_TIMES_ALL_PREDICTION_ROWS_ON_REBALANCE_DATE")
    ck("execution_head_exact", bool(re.fullmatch(r"[0-9a-f]{40}", args.execution_head)) and manifest.get("execution_head") == args.execution_head and consumption.get("execution_head") == args.execution_head)
    ck("model_sha", sha256_file(Path(args.model)) == MODEL_SHA == manifest.get("model_sha256"))
    ck("preprocess_sha", sha256_file(Path(args.preprocess)) == PREPROCESS_SHA == manifest.get("preprocess_manifest_sha256"))
    ck("source_matrix_authority", manifest.get("source_feature_matrix_sha256") == SOURCE_MATRIX_SHA == boundary["fingerprint_basis"]["inputs"]["feature_matrix"]["file_sha256"])

    boutputs = boundary["fingerprint_basis"]["outputs"]
    expected_boundary_files = {boutputs[k] for k in ["features", "market", "lifecycle", "manifest", "source_verification", "independent_audit", "hashes"]}
    actual_boundary_files = {p.name for p in root.iterdir() if p.is_file()}
    ck("physical_boundary_file_set_exact", actual_boundary_files == expected_boundary_files)
    bhashes = json.loads((root / boutputs["hashes"]).read_text(encoding="utf-8"))
    ck("physical_boundary_hash_map_exact", set(bhashes) == expected_boundary_files - {boutputs["hashes"]})
    ck("physical_boundary_hashes_verified", all(sha256_file(root / n) == h for n, h in bhashes.items()))
    bmanifest = json.loads((root / boutputs["manifest"]).read_text(encoding="utf-8"))
    baudit = json.loads((root / boutputs["independent_audit"]).read_text(encoding="utf-8"))
    bsource = json.loads((root / boutputs["source_verification"]).read_text(encoding="utf-8"))
    ck("physical_boundary_manifest_clean", bmanifest.get("status") == "PHYSICALLY_OOS_ONLY_PRE_PREDICTION_NON_LABEL" and bmanifest.get("boundary_contract_fingerprint") == BOUNDARY_FP and bmanifest.get("source_cv_authorization_fingerprint") == SOURCE_CV_AUTH_FP)
    ck("physical_boundary_independent_audit_clean", baudit.get("pass") is True and baudit.get("failed_checks") == [] and int(baudit.get("post_oos_rows_observed", -1)) == 0)
    ck("physical_boundary_source_verification_clean", bsource.get("status") == "VERIFIED" and bsource.get("boundary_contract_fingerprint") == BOUNDARY_FP)
    ck("physical_boundary_nonconsuming", baudit.get("oos_prediction_executed") is False and baudit.get("oos_label_constructed") is False and baudit.get("oos_label_value_read") is False and baudit.get("model_loaded") is False and baudit.get("authorization_consumed") is False and baudit.get("final_lockbox_accessed") is False)

    features = root / boutputs["features"]
    market = root / boutputs["market"]
    lifecycle = root / boutputs["lifecycle"]
    ck("physical_features_sha_manifest", sha256_file(features) == manifest.get("physical_oos_features_sha256"))
    ck("physical_market_sha_manifest", sha256_file(market) == manifest.get("physical_oos_market_sha256"))
    ck("physical_lifecycle_sha_manifest", sha256_file(lifecycle) == manifest.get("physical_oos_lifecycle_sha256"))
    ck("physical_boundary_manifest_sha_execution", sha256_file(root / boutputs["manifest"]) == manifest.get("physical_boundary_manifest_sha256"))
    ck("physical_boundary_audit_sha_execution", sha256_file(root / boutputs["independent_audit"]) == manifest.get("physical_boundary_independent_audit_sha256"))
    ck("execution_runner_no_broad_inputs", manifest.get("broad_source_inputs_available_in_execution_runner") is False and manifest.get("market_source_kind") == "SEALED_PHYSICAL_OOS_BOUNDARY")

    ck("authorization_consumed_once", consumption.get("status") == "CONSUMED" and consumption.get("authorization_fingerprint") == AUTH_FP and consumption.get("execution_contract_fingerprint") == EXEC_FP and consumption.get("physical_boundary_contract_fingerprint") == BOUNDARY_FP and consumption.get("consumption_event") == "FIRST_OOS_PREDICTION_COMPUTATION")
    ck("zero_preconsumption_label_read", consumption.get("oos_label_read_before_consumption") is False)
    ck("no_fit", manifest.get("fit_executed") is False and manifest.get("retraining_executed") is False and manifest.get("hyperparameter_search_executed") is False and manifest.get("candidate_reselection_executed") is False and consumption.get("fit_executed") is False)
    ck("no_lockbox", manifest.get("lockbox_accessed") is False and consumption.get("lockbox_accessed") is False)
    ck("no_label_validity_lookahead", manifest.get("economic_label_validity_lookahead") is False and econ_actual.get("selection_population") == "ALL_PREDICTED_ROWS_BEFORE_LABEL_VALIDITY_FILTER" and econ_actual.get("selected_invalid_label_action") == "FAIL_CLOSED_NO_BACKFILL_NO_POST_SELECTION_DROP")
    ck("no_live_main_authoritative", manifest.get("live_signal_allowed") is False and manifest.get("main_merge_allowed") is False and manifest.get("authoritative_model_output") is False)

    con = duckdb.connect()
    qf = str(features).replace("'", "''")
    qm = str(market).replace("'", "''")
    qlife = str(lifecycle).replace("'", "''")
    frow, fu, fmin, fmax = con.execute(f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date) FROM read_parquet('{qf}')").fetchone()
    mrow, mu, mmin, mmax, mnull = con.execute(f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date),count(*) FILTER(WHERE open IS NULL OR close IS NULL OR factor IS NULL) FROM read_parquet('{qm}')").fetchone()
    lleak = con.execute(f"SELECT count(*) FROM read_parquet('{qlife}') WHERE listed_to_exclusive IS NOT NULL AND listed_to_exclusive>DATE '{OOS_END}'").fetchone()[0]
    ck("physical_feature_population", frow > 0 and frow == fu and str(fmin) == OOS_START and str(fmax) == OOS_END and int(frow) == int(bmanifest["features"]["row_count"]))
    ck("physical_market_population", mrow > 0 and mrow == mu and str(mmin) == OOS_START and str(mmax) == OOS_END and int(mrow) == int(bmanifest["market"]["row_count"]) and int(mnull) == 0)
    ck("physical_lifecycle_no_post_oos", int(lleak) == 0)

    pred, labels, ev = Path(args.predictions), Path(args.labels), Path(args.evaluation)
    qp, ql, qe = str(pred).replace("'", "''"), str(labels).replace("'", "''"), str(ev).replace("'", "''")
    prow, pu, pmin, pmax = con.execute(f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date) FROM read_parquet('{qp}')").fetchone()
    lrow, lu, lmin, lmax, valid20, maxvalid20, maxexit20 = con.execute(f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date),count(*) FILTER(WHERE valid_label_20d),max(trade_date) FILTER(WHERE valid_label_20d),max(exit_date_20d) FILTER(WHERE valid_label_20d) FROM read_parquet('{ql}')").fetchone()
    erow, eu, emin, emax = con.execute(f"SELECT count(*),count(DISTINCT (trade_date,exchange,code)),min(trade_date),max(trade_date) FROM read_parquet('{qe}')").fetchone()
    ck("prediction_population_unique", prow > 0 and prow == pu == frow and str(pmin) == OOS_START and str(pmax) == OOS_END and manifest.get("prediction_rows") == prow)
    ck("label_population_unique", lrow == lu == prow and str(lmin) == OOS_START and str(lmax) == OOS_END and manifest.get("label_rows") == lrow)
    ck("valid20_boundary", valid20 == erow and str(maxvalid20) <= LATEST_VALID20 and str(maxexit20) <= OOS_END and str(emax) <= LATEST_VALID20 and manifest.get("valid_20d_rows") == valid20)
    ck("evaluation_population_unique", erow > 0 and erow == eu and manifest.get("evaluation_rows") == erow)
    ck("market_lockbox_boundary", str(manifest.get("market_source_min_date")) == OOS_START and str(manifest.get("market_source_max_date")) == OOS_END and str(manifest.get("market_source_max_date")) < LOCKBOX_START and int(manifest.get("market_source_rows", -1)) == int(mrow))

    icdf = pq.read_table(ev).to_pandas()
    icdf["trade_date"] = pd.to_datetime(icdf["trade_date"]).dt.date
    daily = []
    for d, g in icdf.groupby("trade_date", sort=True):
        p = g["prediction"].to_numpy(dtype=float)
        y = g["excess_return_20d"].to_numpy(dtype=float)
        ok = np.isfinite(p) & np.isfinite(y)
        ic = None
        if int(ok.sum()) >= 20 and np.unique(p[ok]).size > 1 and np.unique(y[ok]).size > 1:
            ic = float(spearmanr(p[ok], y[ok]).statistic)
        daily.append({"trade_date": str(d), "daily_ic_20d": ic})
    vd = [r for r in daily if r["daily_ic_20d"] is not None and math.isfinite(r["daily_ic_20d"])]
    ics = np.asarray([r["daily_ic_20d"] for r in vd], dtype=np.float64)
    mean_ic = float(ics.mean())
    ci_lo, ci_hi = bootstrap(ics)
    ck("mean_ic_recomputed", close(mean_ic, gate_actual["mean_daily_ic_20d"]))
    ck("bootstrap_recomputed", close(ci_lo, gate_actual["bootstrap_95pct_ci"]["lower"]) and close(ci_hi, gate_actual["bootstrap_95pct_ci"]["upper"]))

    ddf = pd.DataFrame(vd)
    ddf["quarter"] = pd.PeriodIndex(pd.to_datetime(ddf["trade_date"]), freq="Q").astype(str)
    qmeans = ddf.groupby("quarter", sort=True)["daily_ic_20d"].mean().to_dict()
    expected_q = exe["fingerprint_basis"]["metric_semantics"]["expected_quarters"]
    qr = []
    for qtr in expected_q:
        v = qmeans.get(qtr)
        qr.append({"quarter": qtr, "mean_daily_ic_20d": None if v is None else float(v), "positive": bool(v is not None and v > 0)})
    qok = len(qr) == len(quarter_actual["quarters"])
    if qok:
        for a, b in zip(qr, quarter_actual["quarters"]):
            if a["quarter"] != b["quarter"] or a["positive"] != b["positive"]:
                qok = False
                break
            av, bv = a["mean_daily_ic_20d"], b["mean_daily_ic_20d"]
            if (av is None) != (bv is None) or (av is not None and not close(av, bv)):
                qok = False
                break
    ck("quarters_recomputed", qok)
    positive_q = sum(x["positive"] for x in qr)

    allq = con.execute(f"SELECT p.trade_date,p.exchange,p.code,p.prediction,l.valid_label_20d,l.censor_reason_20d,l.entry_date,l.exit_date_20d,l.excess_return_20d FROM read_parquet('{qp}') p JOIN read_parquet('{ql}') l USING(trade_date,exchange,code) WHERE p.trade_date<=DATE '{LATEST_VALID20}' ORDER BY p.trade_date,p.exchange,p.code").fetch_arrow_table().to_pandas()
    allq["trade_date"] = pd.to_datetime(allq["trade_date"]).dt.date
    allq["trade_date_str"] = allq["trade_date"].astype(str)
    dates = sorted(allq["trade_date_str"].unique().tolist())
    rebalances = dates[::20]
    ck("rebalance_anchor_exact", bool(rebalances) and rebalances[0] == OOS_START and econ_actual.get("rebalance_dates") == rebalances)

    agg, validity = {}, {}
    econ_ok = True
    for cov in [0.05, 0.10, 0.20]:
        actual = econ_actual["coverages"][f"{int(cov*100):02d}pct"]
        cohorts, coverage_valid = [], True
        for d in rebalances:
            g = allq[allq["trade_date_str"] == d].copy()
            g.sort_values(["prediction", "exchange", "code"], ascending=[False, True, True], kind="mergesort", inplace=True)
            k = max(1, int(math.ceil(cov * len(g))))
            top = g.iloc[:k].copy()
            mask = top["valid_label_20d"].fillna(False).astype(bool) & np.isfinite(top["excess_return_20d"].to_numpy(dtype=float, na_value=np.nan))
            invalid = int((~mask).sum())
            row = {"decision_date": d, "eligible_prediction_rows": int(len(g)), "selected_rows": int(k), "selected_invalid_20d_rows": invalid, "cohort_valid": invalid == 0}
            if invalid:
                coverage_valid = False
                row.update({"entry_date": None, "exit_date": None, "gross_excess_return_20d": None, "roundtrip_cost": None, "net_excess_return_20d": None})
            else:
                entry = sorted({str(x) for x in top["entry_date"]})
                exitd = sorted({str(x) for x in top["exit_date_20d"]})
                if len(entry) != 1 or len(exitd) != 1:
                    econ_ok = False
                    break
                gross = float(top["excess_return_20d"].mean())
                c = roundtrip_cost(entry[0], exitd[0])
                row.update({"entry_date": entry[0], "exit_date": exitd[0], "gross_excess_return_20d": gross, "roundtrip_cost": c, "net_excess_return_20d": gross - c})
            cohorts.append(row)
        if not econ_ok:
            break
        val = None if not coverage_valid else float(np.mean([x["net_excess_return_20d"] for x in cohorts]))
        key = f"{int(cov*100):02d}pct"
        agg[key], validity[key] = val, coverage_valid
        if actual.get("coverage_valid") != coverage_valid or actual.get("aggregate_net_excess_return_20d") != val or actual.get("cohort_count") != len(cohorts) or actual.get("cohorts") != cohorts:
            econ_ok = False
            break
    ck("economic_metrics_recomputed_no_label_lookahead", econ_ok)

    gates = {
        "mean_daily_spearman_ic_20d_gt_0": mean_ic > 0,
        "block_bootstrap_95pct_ci_lower_bound_mean_daily_ic_20d_gt_0": ci_lo > 0,
        "positive_mean_ic_in_at_least_6_of_8_calendar_quarters": positive_q >= 6 and len(qr) == 8 and all(x["mean_daily_ic_20d"] is not None for x in qr),
        "top_10pct_net_excess_return_20d_at_15bps_per_side_gt_0": validity.get("10pct", False) and agg.get("10pct") is not None and agg["10pct"] > 0,
        "no_sign_inversion_5pct_or_20pct_coverage": validity.get("05pct", False) and validity.get("20pct", False) and agg.get("05pct") is not None and agg.get("20pct") is not None and agg["05pct"] >= 0 and agg["20pct"] >= 0,
        "pbo_le_0_20_carried_from_development": 0.11904761904761904 <= 0.20,
        "dsr_ge_0_95_carried_from_development": 0.9999989891602007 >= 0.95,
    }
    ck("gate_checks_recomputed", gate_actual.get("checks") == gates)
    ck("gate_status_recomputed", gate_actual.get("status") == ("PASS" if all(gates.values()) else "FAIL"))
    ck("lockbox_not_opened_on_oos_result", gate_actual.get("final_lockbox_open_allowed") is False)

    hashes = json.loads((out / "artifact_hashes.json").read_text(encoding="utf-8"))
    required = ["oos_execution_manifest.json", "oos_predictions.parquet", "oos_daily_metrics.parquet", "oos_quarter_metrics.json", "oos_economic_metrics.json", "oos_gate_result.json", "authorization_consumption.json"]
    ck("artifact_hashes_match", all(hashes.get(n) == sha256_file(out / n) for n in required))

    audit = {
        "schema_version": 2,
        "gate": "STAGE4_ALPHA_V1_OOS_VALIDATION_INDEPENDENT_AUDIT_PHYSICAL_INPUT",
        "execution_head": args.execution_head,
        "pass": len(failures) == 0,
        "failed_checks": failures,
        "checks": checks,
        "recomputed": {"physical_feature_rows": int(frow), "physical_market_rows": int(mrow), "prediction_rows": int(prow), "label_rows": int(lrow), "valid_20d_rows": int(valid20), "evaluation_rows": int(erow), "mean_daily_ic_20d": mean_ic, "bootstrap_95pct_ci": {"lower": ci_lo, "upper": ci_hi}, "positive_quarters": positive_q, "coverage_validity": validity, "coverage_net_excess": agg, "gate_pass": all(gates.values())},
        "physical_boundary_contract_fingerprint": BOUNDARY_FP,
        "broad_source_inputs_available_to_audit": False,
        "economic_label_validity_lookahead": False,
        "model_fit_executed_by_audit": False,
        "oos_predictions_recomputed_by_audit": False,
        "oos_labels_rebuilt_by_audit": False,
        "lockbox_accessed": False,
        "authoritative_model_output": False,
    }
    Path(args.out).write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))
    return 0 if audit["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
