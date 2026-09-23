#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import hashlib
import json
from pathlib import Path

import requests

import accept_stage3_s3g1j_v17_21_production as accepted
import stage3_financial_pdf_parser_v15 as production

EXPECTED_SHARDS = (0, 1, 7, 9)
PREVIOUS_RECOVERIES = {"1212731093", "1219311356", "1225153907"}
NEW_RECOVERY = "1221568845"
EXPECTED_EXACT82_RECOVERIES = PREVIOUS_RECOVERIES | {NEW_RECOVERY}
EXPECTED_EXACT79_RECOVERIES = {NEW_RECOVERY}
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
EXPECTED_VALUES = {
    NEW_RECOVERY: {
        "TOTAL_ASSETS": "3642768851.01",
        "TOTAL_LIABILITIES": "2382626915.88",
        "TOTAL_EQUITY": "1260141935.13",
    }
}
EXPECTED_ARBITRATION = {
    "1212731093": "V17_17_GROUP_PERIOD_STRICT_PAIRED_HEADER_A_EQUALS_L_PLUS_E_EXPLICIT_TOTAL_EQUITY",
    "1219311356": "V17_21_GROUP_PERIOD_FROZEN_DATE_A_EQUALS_L_PLUS_E_EXACT_REVERSE_ASSET_TOTAL",
    "1225153907": "V17_15_GROUP_PERIOD_FROZEN_DATE_COLUMN_A_EQUALS_L_PLUS_E_STRICT_ADJACENT_ROW",
    NEW_RECOVERY: "V17_24_GROUP_PERIOD_FROZEN_DATE_A_EQUALS_L_PLUS_E_EXACT_CORRUPTED_EQUITY_ALIAS",
}


def _load_v17_21(root: Path) -> tuple[dict[str, dict], set[str]]:
    rows: dict[str, dict] = {}
    recovered: set[str] = set()
    paths = sorted(glob.glob(str(root / "candidate" / "shard*.json")))
    if len(paths) != 4:
        raise ValueError(f"expected four V17.21 shards, got {paths}")
    for path in paths:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        if not report.get("pass"):
            raise ValueError(f"V17.21 shard not pass: {path}")
        for row in report.get("results") or []:
            aid = str(row["announcement_id"])
            if aid in rows:
                raise ValueError(f"duplicate V17.21 row {aid}")
            rows[aid] = row
            if row.get("production_balance_sheet_recovered"):
                recovered.add(aid)
    if len(rows) != 82:
        raise ValueError(f"expected 82 V17.21 rows, got {len(rows)}")
    if recovered != PREVIOUS_RECOVERIES:
        raise ValueError(f"previous recovery set changed {sorted(recovered)}")
    return rows, recovered


def _validated(parsed: dict) -> bool:
    observations = parsed.get("observations") or {}
    return (
        all(
            (observations.get(concept) or {}).get("status") == "FOUND"
            for concept in CONCEPTS
        )
        and isinstance(parsed.get("balance_sheet_block"), dict)
        and not list(parsed.get("validation_errors") or [])
    )


def _validate_recovery(aid: str, parsed: dict) -> None:
    if not _validated(parsed):
        raise ValueError(f"expected recovery did not validate {aid}")
    block = parsed["balance_sheet_block"]
    if block.get("arbitration") != EXPECTED_ARBITRATION[aid]:
        raise ValueError(
            f"arbitration changed {aid}: {block.get('arbitration')}"
        )
    if block.get("identity_tolerance") != "0.005":
        raise ValueError(f"identity tolerance changed {aid}")
    if block.get("global_row_tolerance_changed") is not False:
        raise ValueError(f"global row tolerance changed {aid}")
    if block.get("e_equals_a_minus_l_inference") is not False:
        raise ValueError(f"E=A-L inference enabled {aid}")
    if aid == NEW_RECOVERY:
        if block.get("candidate_only") is not False:
            raise ValueError("V17.24 production block still marked candidate-only")
        if block.get("production_runtime_generation") != "V17.24":
            raise ValueError("V17.24 production generation missing")
        if block.get("corrupted_equity_selected_concepts") != ["TOTAL_EQUITY"]:
            raise ValueError("V17.24 corrupted equity not required")
        if block.get("corrupted_equity_alias") != "所有者权益（或d股东权益）合计":
            raise ValueError("V17.24 corrupted alias changed")
        if block.get("corrupted_equity_amount_column_count") != 2:
            raise ValueError("V17.24 amount column count changed")
        if block.get("column_role_gate_pass") is not True:
            raise ValueError("V17.24 frozen-date column gate failed")
        if str(block.get("identity_residual_cny")) not in {"0", "0.0", "0.00"}:
            raise ValueError("V17.24 identity residual is nonzero")
        observations = parsed.get("observations") or {}
        actual = {
            concept: str(
                (observations.get(concept) or {}).get("normalized_cny_value")
            )
            for concept in CONCEPTS
        }
        if actual != EXPECTED_VALUES[aid]:
            raise ValueError(f"V17.24 values changed {actual}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", required=True)
    parser.add_argument("--v17-21-root", required=True)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, default=64)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.shards != 64 or args.shard not in EXPECTED_SHARDS:
        raise ValueError("production replay frozen to shards 0,1,7,9")

    source_rows, prior_recovered = _load_v17_21(Path(args.v17_21_root))
    residual79 = set(source_rows) - prior_recovered
    if len(residual79) != 79:
        raise ValueError(f"expected exact79 residuals, got {len(residual79)}")

    versions = [
        row
        for row in accepted.read_versions(Path(args.versions))
        if row["canonical_announcement_id"] in source_rows
        and accepted.base.stable_shard(
            row["canonical_announcement_id"], args.shards
        )
        == args.shard
    ]
    versions.sort(key=lambda row: row["canonical_announcement_id"])

    session = requests.Session()
    results: list[dict] = []
    failures: list[dict] = []
    for index, row in enumerate(versions, 1):
        aid = row["canonical_announcement_id"]
        try:
            raw = accepted.download(session, row["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            expected_sha = source_rows[aid]["source_sha256"]
            if digest != expected_sha:
                raise ValueError(
                    f"source SHA changed expected={expected_sha} actual={digest}"
                )
            parsed = production.parse_pdf_bytes(raw, row["economic_date"])
            recovered = _validated(parsed)
            block = parsed.get("balance_sheet_block")
            errors = list(parsed.get("validation_errors") or [])
            if aid in EXPECTED_EXACT82_RECOVERIES:
                _validate_recovery(aid, parsed)
            else:
                if recovered or block is not None:
                    raise ValueError("unexpected production recovery")
                if not errors:
                    raise ValueError(
                        "non-recovered row lost fail-closed validation errors"
                    )
            results.append(
                {
                    "announcement_id": aid,
                    "source_code": row["source_code"],
                    "report_family": row["report_family"],
                    "economic_date": row["economic_date"],
                    "canonical_title": row["canonical_title"],
                    "canonical_source_url": row["canonical_source_url"],
                    "source_sha256": digest,
                    "was_v17_21_residual": aid in residual79,
                    "production_balance_sheet_recovered": recovered,
                    "balance_sheet_block": block,
                    "validation_errors": errors,
                    "parser_version": parsed.get("parser_version"),
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "announcement_id": aid,
                    "source_code": row.get("source_code"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(
            f"S3G1J_V17_24_PRODUCTION shard={args.shard} "
            f"{index}/{len(versions)} aid={aid}",
            flush=True,
        )

    exact82_recovered = sorted(
        row["announcement_id"]
        for row in results
        if row["production_balance_sheet_recovered"]
    )
    exact79_results = [
        row for row in results if row["was_v17_21_residual"]
    ]
    exact79_recovered = sorted(
        row["announcement_id"]
        for row in exact79_results
        if row["production_balance_sheet_recovered"]
    )
    report = {
        "gate": "S3G1J_V17_24_PRODUCTION_REPLAY_SHARD",
        "production_parser_changed": True,
        "shard": args.shard,
        "shards": args.shards,
        "input_count_exact82": len(versions),
        "input_count_exact79": len(exact79_results),
        "processed_count": len(results),
        "source_sha_match_count": len(results),
        "exact82_recovered_announcement_ids": exact82_recovered,
        "exact79_recovered_announcement_ids": exact79_recovered,
        "results": results,
        "execution_failures": failures,
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "global_row_tolerance_changed": False,
        "fuzzy_alias_matching_enabled": False,
        "e_equals_a_minus_l_inference": False,
        "source_policy_changed": False,
        "stage4_alpha_locked": True,
        "pass": not failures and len(results) == len(versions),
        "errors": failures,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "shard": args.shard,
                "input_exact82": len(versions),
                "input_exact79": len(exact79_results),
                "exact82_recovered": exact82_recovered,
                "exact79_recovered": exact79_recovered,
                "failures": failures,
                "pass": report["pass"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
