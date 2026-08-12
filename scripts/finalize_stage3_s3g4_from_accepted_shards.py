#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from stage3_earnings_forecast_parser import compare_actual

SHARD_COUNT = 64
FORECAST_POPULATION = 51732
EXPECTED_ACTUAL_PARENT_NET_PROFIT = 118505
EXPECTED_ACTUAL_PIT_EXCLUSIONS = {
    "1207046114",
    "1208263921",
    "1220457006",
    "1221055839",
}
EXPECTED_PARSER_BLOB = "4e22de08c5094b64374c03fe646c61d6ca26ad0b"
SOURCE_SHARD_RUN = 31557145693
SOURCE_SHARD_HEAD = "8422f1ce24a19c80560ee9a626b14a7eb9b2a5be"
METHOD = "V3.3.16_S3G4_ACCEPTED_64_SHARD_EXACT_ISSUER_PIT_FINAL"

SURPRISE_FIELDS = [
    "exchange","effective_code","issuer_org_id","economic_date","actual_report_family",
    "actual_announcement_id","actual_available_at","actual_source_sha256","actual_parent_net_profit_cny",
    "forecast_announcement_id","forecast_available_at","forecast_source_url","forecast_source_sha256",
    "forecast_low_cny","forecast_high_cny","forecast_midpoint_cny","forecast_status","forecast_sign_inference",
    "surprise_cny","range_position","surprise_direction","expectation_is_strictly_prior","identity_match_mode",
    "expectation_source","actual_source","analyst_consensus_used","methodology_version",
]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def write_det_gzip(path: Path, fields: list[str], rows: list[dict]) -> None:
    raw = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as gz:
        txt = io.TextIOWrapper(gz, encoding="utf-8", newline="", write_through=True)
        w = csv.DictWriter(txt, fieldnames=fields, lineterminator="\n")
        w.writeheader(); w.writerows(rows); txt.flush()
    path.write_bytes(raw.getvalue())


def dump_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def parse_dt(value: str) -> datetime:
    if not value:
        raise ValueError("blank PIT timestamp")
    return datetime.fromisoformat(value)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", required=True)
    ap.add_argument("--financial-values", required=True)
    ap.add_argument("--financial-documents", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(args.shards)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    forecast_rows: list[dict] = []
    shard_evidence: list[dict] = []

    for i in range(SHARD_COUNT):
        mp = list(root.rglob(f"stage3_s3g4_forecast_shard_{i:02d}.json"))
        lp = list(root.rglob(f"stage3_s3g4_forecast_shard_{i:02d}.csv.gz"))
        hp = list(root.rglob(f"stage3_s3g4_forecast_shard_{i:02d}_sha256.json"))
        if len(mp) != 1 or len(lp) != 1 or len(hp) != 1:
            errors.append(f"shard {i} cardinality manifest={len(mp)} ledger={len(lp)} hash={len(hp)}")
            continue
        manifest = json.loads(mp[0].read_text(encoding="utf-8"))
        hashes = json.loads(hp[0].read_text(encoding="utf-8"))
        if manifest.get("gate") != "S3G4_OFFICIAL_FORECAST_SHARD": errors.append(f"shard {i} gate drift")
        if manifest.get("pass") is not True: errors.append(f"shard {i} not pass")
        if manifest.get("shard_index") != i or manifest.get("shard_count") != SHARD_COUNT: errors.append(f"shard {i} identity drift")
        if manifest.get("parser_blob") != EXPECTED_PARSER_BLOB: errors.append(f"shard {i} parser blob drift")
        if manifest.get("source_policy") != "CNINFO_OFFICIAL_PDF_ONLY": errors.append(f"shard {i} source policy drift")
        if manifest.get("analyst_consensus_used") is not False: errors.append(f"shard {i} analyst consensus drift")
        if manifest.get("hard_error_count") != 0: errors.append(f"shard {i} hard errors={manifest.get('hard_error_count')}")
        if manifest.get("selected_count") != manifest.get("output_count") or int(manifest.get("selected_count") or 0) <= 0:
            errors.append(f"shard {i} population mismatch")
        if manifest.get("ledger_sha256") != sha_file(lp[0]): errors.append(f"shard {i} manifest ledger SHA mismatch")
        if hashes.get(lp[0].name) != sha_file(lp[0]): errors.append(f"shard {i} hash ledger mismatch")
        if hashes.get(mp[0].name) != sha_file(mp[0]): errors.append(f"shard {i} hash manifest mismatch")
        rows = list(read_gz(lp[0]))
        if len(rows) != manifest.get("output_count"): errors.append(f"shard {i} row count mismatch")
        if any(r.get("fetch_status") != "OK" for r in rows): errors.append(f"shard {i} non-OK source fetch row")
        if any(r.get("parser_status") not in {"FOUND","FOUND_POINT_ESTIMATE","NOT_FOUND"} for r in rows): errors.append(f"shard {i} parser status outside contract")
        if any(not r.get("source_sha256") or not r.get("source_bytes") or not r.get("pdf_pages") for r in rows): errors.append(f"shard {i} incomplete source identity")
        forecast_rows.extend(rows)
        shard_evidence.append({
            "shard_index": i,
            "selected_count": manifest.get("selected_count"),
            "ledger_sha256": sha_file(lp[0]),
            "manifest_sha256": sha_file(mp[0]),
            "parser_status_counts": manifest.get("parser_status_counts"),
        })

    forecast_rows.sort(key=lambda r: r["announcement_id"])
    forecast_ids = [r["announcement_id"] for r in forecast_rows]
    if len(forecast_rows) != FORECAST_POPULATION: errors.append(f"forecast rows {len(forecast_rows)} != {FORECAST_POPULATION}")
    if len(set(forecast_ids)) != len(forecast_ids): errors.append("duplicate forecast announcement_id")
    if any(not r.get("available_at") or not r.get("org_id") or not r.get("effective_code") for r in forecast_rows):
        errors.append("forecast population contains missing PIT or identity")

    numeric_forecasts = [r for r in forecast_rows if r["parser_status"] in {"FOUND","FOUND_POINT_ESTIMATE"} and r.get("economic_date")]
    by_period: dict[tuple[str,str], list[dict]] = defaultdict(list)
    for r in numeric_forecasts:
        try:
            parse_dt(r["available_at"])
        except Exception as exc:
            errors.append(f"numeric forecast invalid available_at {r['announcement_id']}: {exc}")
            continue
        by_period[(r["org_id"], r["economic_date"])].append(r)
    for rows in by_period.values():
        rows.sort(key=lambda r: (parse_dt(r["available_at"]), r["announcement_id"]))

    docs = {r["announcement_id"]: r for r in read_gz(Path(args.financial_documents))}
    total_actuals = 0
    eligible_actuals: list[dict] = []
    excluded_actuals: list[dict] = []
    for r in read_gz(Path(args.financial_values)):
        if r["concept"] != "NET_PROFIT_ATTRIBUTABLE_TO_PARENT":
            continue
        total_actuals += 1
        d = docs.get(r["announcement_id"])
        if not d or d.get("document_status") != "PASS":
            errors.append(f"actual document missing/not PASS {r['announcement_id']}")
            continue
        for k in ["issuer_org_id","economic_date","source_code","exchange"]:
            if d.get(k) != r.get(k): errors.append(f"actual document/value {k} mismatch {r['announcement_id']}")
        if d.get("selected_source_sha256") != r.get("source_sha256"):
            errors.append(f"actual source SHA mismatch {r['announcement_id']}")
        value_av = r.get("available_at") or ""
        doc_av = d.get("available_at") or ""
        value_code = r.get("effective_code") or ""
        doc_code = d.get("effective_code") or ""
        if value_av != doc_av or value_code != doc_code:
            errors.append(f"actual PIT/document identity mismatch {r['announcement_id']}")
        if not value_av or not value_code:
            excluded_actuals.append({
                "announcement_id": r["announcement_id"],
                "issuer_org_id": r["issuer_org_id"],
                "economic_date": r["economic_date"],
                "effective_code": value_code,
                "available_at": value_av,
                "reason": "MISSING_FORMAL_PIT_OR_EFFECTIVE_CODE_FAIL_CLOSED",
            })
            continue
        try:
            parse_dt(value_av)
        except Exception as exc:
            errors.append(f"actual invalid available_at {r['announcement_id']}: {exc}")
            continue
        eligible_actuals.append(r)

    if total_actuals != EXPECTED_ACTUAL_PARENT_NET_PROFIT:
        errors.append(f"parent actual count {total_actuals} != {EXPECTED_ACTUAL_PARENT_NET_PROFIT}")
    excluded_ids = {r["announcement_id"] for r in excluded_actuals}
    if excluded_ids != EXPECTED_ACTUAL_PIT_EXCLUSIONS:
        errors.append(f"actual PIT exclusion set {sorted(excluded_ids)} != {sorted(EXPECTED_ACTUAL_PIT_EXCLUSIONS)}")
    if len(excluded_actuals) != len(EXPECTED_ACTUAL_PIT_EXCLUSIONS): errors.append("actual PIT exclusion duplicate/cardinality drift")
    if len(eligible_actuals) != EXPECTED_ACTUAL_PARENT_NET_PROFIT - len(EXPECTED_ACTUAL_PIT_EXCLUSIONS):
        errors.append(f"eligible actual count {len(eligible_actuals)} drift")

    surprise_rows: list[dict] = []
    no_prior: list[dict] = []
    for actual in eligible_actuals:
        actual_dt = parse_dt(actual["available_at"])
        candidates = [f for f in by_period.get((actual["issuer_org_id"], actual["economic_date"]), []) if parse_dt(f["available_at"]) < actual_dt]
        if not candidates:
            no_prior.append({
                "actual_announcement_id": actual["announcement_id"],
                "issuer_org_id": actual["issuer_org_id"],
                "economic_date": actual["economic_date"],
                "actual_available_at": actual["available_at"],
            })
            continue
        forecast = candidates[-1]
        parsed = {
            "status": forecast["parser_status"],
            "low_cny": forecast["forecast_low_cny"],
            "high_cny": forecast["forecast_high_cny"],
            "midpoint_cny": forecast["forecast_midpoint_cny"],
        }
        cmp = compare_actual(parsed, actual["normalized_cny_value"])
        if parse_dt(forecast["available_at"]) >= actual_dt:
            errors.append(f"non-prior expectation {forecast['announcement_id']}->{actual['announcement_id']}")
            continue
        surprise_rows.append({
            "exchange": actual["exchange"],
            "effective_code": actual["effective_code"],
            "issuer_org_id": actual["issuer_org_id"],
            "economic_date": actual["economic_date"],
            "actual_report_family": actual["report_family"],
            "actual_announcement_id": actual["announcement_id"],
            "actual_available_at": actual["available_at"],
            "actual_source_sha256": actual["source_sha256"],
            "actual_parent_net_profit_cny": actual["normalized_cny_value"],
            "forecast_announcement_id": forecast["announcement_id"],
            "forecast_available_at": forecast["available_at"],
            "forecast_source_url": forecast["source_url"],
            "forecast_source_sha256": forecast["source_sha256"],
            "forecast_low_cny": forecast["forecast_low_cny"],
            "forecast_high_cny": forecast["forecast_high_cny"],
            "forecast_midpoint_cny": forecast["forecast_midpoint_cny"],
            "forecast_status": forecast["parser_status"],
            "forecast_sign_inference": forecast["forecast_sign_inference"],
            "surprise_cny": cmp["surprise_cny"],
            "range_position": cmp["range_position"] or "",
            "surprise_direction": cmp["surprise_direction"],
            "expectation_is_strictly_prior": "1",
            "identity_match_mode": "EXACT_ISSUER_ORG_ID_AND_ECONOMIC_DATE",
            "expectation_source": "OFFICIAL_COMPANY_EARNINGS_FORECAST_PDF",
            "actual_source": "ORIGINAL_PERIODIC_FILING_PDF",
            "analyst_consensus_used": "0",
            "methodology_version": METHOD,
        })

    surprise_rows.sort(key=lambda r: (r["actual_available_at"], r["exchange"], r["effective_code"], r["actual_announcement_id"]))
    if not surprise_rows: errors.append("zero surprise observations")
    if any(r["expectation_is_strictly_prior"] != "1" for r in surprise_rows): errors.append("non-prior output row")
    if any(r["analyst_consensus_used"] != "0" for r in surprise_rows): errors.append("analyst consensus output row")

    forecast_fields = list(forecast_rows[0].keys()) if forecast_rows else []
    forecast_ledger = out / "stage3_earnings_forecast_parse_ledger.csv.gz"
    surprise_ledger = out / "stage3_earnings_surprise.csv.gz"
    write_det_gzip(forecast_ledger, forecast_fields, forecast_rows)
    write_det_gzip(surprise_ledger, SURPRISE_FIELDS, surprise_rows)

    parser_status_counts = Counter(r["parser_status"] for r in forecast_rows)
    audit = {
        "gate": "S3G4_OFFICIAL_EARNINGS_GUIDANCE_SURPRISE_FINAL",
        "pass": not errors,
        "source_shard_run_id": SOURCE_SHARD_RUN,
        "source_shard_head_sha": SOURCE_SHARD_HEAD,
        "shard_count": SHARD_COUNT,
        "forecast_population": len(forecast_rows),
        "source_pdf_fetch_completeness": (sum(1 for r in forecast_rows if r["fetch_status"] == "OK") / FORECAST_POPULATION) if forecast_rows else 0,
        "forecast_parser_status_counts": dict(parser_status_counts),
        "numeric_forecast_versions": len(numeric_forecasts),
        "numeric_forecast_org_count": len({r["org_id"] for r in numeric_forecasts}),
        "financial_parent_net_profit_observations_total": total_actuals,
        "financial_actuals_excluded_missing_formal_pit_identity": len(excluded_actuals),
        "financial_actual_pit_exclusions": excluded_actuals,
        "financial_actual_observations_eligible": len(eligible_actuals),
        "financial_actual_org_count_eligible": len({r["issuer_org_id"] for r in eligible_actuals}),
        "surprise_observations": len(surprise_rows),
        "actuals_without_prior_numeric_forecast": len(no_prior),
        "actuals_without_prior_samples": no_prior[:50],
        "identity_match_mode": "EXACT_ISSUER_ORG_ID_AND_ECONOMIC_DATE",
        "expectation_is_strictly_prior": True,
        "expectation_source": "OFFICIAL_COMPANY_EARNINGS_FORECAST_PDF",
        "actual_source": "ORIGINAL_PERIODIC_FILING_PDF",
        "analyst_consensus_used": False,
        "missing_actual_pit_policy": "FAIL_CLOSED_EXCLUDE_FROM_S3G4; DO_NOT_INFER_AVAILABLE_AT_OR_EFFECTIVE_CODE",
        "forecast_parse_ledger_sha256": sha_file(forecast_ledger),
        "surprise_ledger_sha256": sha_file(surprise_ledger),
        "parser_blob": EXPECTED_PARSER_BLOB,
        "methodology_version": METHOD,
        "stage4_unlocked": False,
        "alpha_training_allowed": False,
        "live_signal_allowed": False,
        "errors": errors,
        "shard_evidence": shard_evidence,
    }
    dump_json(out / "stage3_earnings_surprise_audit.json", audit)
    hashes = {p.name: sha_file(p) for p in sorted(out.iterdir()) if p.is_file()}
    dump_json(out / "output_sha256.json", hashes)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
