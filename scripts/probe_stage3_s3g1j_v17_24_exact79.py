#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import hashlib
import json
from pathlib import Path

import requests

import accept_stage3_s3g1j_v17_21_production as accepted
import stage3_financial_pdf_parser_v14 as candidate

EXPECTED_SHARDS = (0, 1, 7, 9)
EXPECTED_TOTAL = 79
EXPECTED_RECOVERY = {"1221568845"}
PREVIOUS_RECOVERIES = {"1212731093", "1219311356", "1225153907"}
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
EXPECTED_VALUES = {
    "TOTAL_ASSETS": "3642768851.01",
    "TOTAL_LIABILITIES": "2382626915.88",
    "TOTAL_EQUITY": "1260141935.13",
}
EXPECTED_ARBITRATION = (
    "V17_24_GROUP_PERIOD_FROZEN_DATE_A_EQUALS_L_PLUS_E_"
    "EXACT_CORRUPTED_EQUITY_ALIAS"
)


def _load_exact79(root: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    recovered: set[str] = set()
    paths = sorted(glob.glob(str(root / "candidate" / "shard*.json")))
    if len(paths) != 4:
        raise ValueError(f"expected four V17.21 production shards, got {paths}")
    for path in paths:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        if not report.get("pass"):
            raise ValueError(f"V17.21 production shard not pass: {path}")
        for row in report.get("results") or []:
            aid = str(row["announcement_id"])
            if aid in rows or aid in recovered:
                raise ValueError(f"duplicate V17.21 production row {aid}")
            if row.get("production_balance_sheet_recovered"):
                recovered.add(aid)
            else:
                if not row.get("validation_errors"):
                    raise ValueError(
                        f"non-recovered V17.21 row lost validation errors {aid}"
                    )
                rows[aid] = row
    if recovered != PREVIOUS_RECOVERIES:
        raise ValueError(
            f"previous production recovery set changed: {sorted(recovered)}"
        )
    if len(rows) != EXPECTED_TOTAL:
        raise ValueError(f"expected exact 79 residuals, got {len(rows)}")
    return rows


def _validated(parsed: dict) -> bool:
    observations = parsed.get("observations") or {}
    raw_found = all(
        (observations.get(concept) or {}).get("status") == "FOUND"
        for concept in CONCEPTS
    )
    return (
        raw_found
        and isinstance(parsed.get("balance_sheet_block"), dict)
        and not list(parsed.get("validation_errors") or [])
    )


def _require_target(parsed: dict) -> None:
    if not _validated(parsed):
        raise ValueError(
            "target did not produce a validated candidate block: "
            f"block={parsed.get('balance_sheet_block')} "
            f"errors={parsed.get('validation_errors')}"
        )
    block = parsed["balance_sheet_block"]
    if block.get("arbitration") != EXPECTED_ARBITRATION:
        raise ValueError(f"unexpected arbitration {block.get('arbitration')}")
    if block.get("identity_tolerance") != "0.005":
        raise ValueError("identity tolerance changed")
    if block.get("global_row_tolerance_changed") is not False:
        raise ValueError("global row tolerance changed")
    if block.get("e_equals_a_minus_l_inference") is not False:
        raise ValueError("E=A-L inference unexpectedly enabled")
    if block.get("corrupted_equity_selected_concepts") != ["TOTAL_EQUITY"]:
        raise ValueError("candidate did not require corrupted equity")
    if block.get("corrupted_equity_alias") != (
        "所有者权益（或d股东权益）合计"
    ):
        raise ValueError("corrupted alias changed")
    if block.get("corrupted_equity_amount_column_count") != 2:
        raise ValueError("corrupted equity amount count changed")
    if str(block.get("identity_residual_cny")) not in {"0", "0.0", "0.00"}:
        raise ValueError(
            f"target identity residual not zero {block.get('identity_residual_cny')}"
        )
    if block.get("column_role_gate_pass") is not True:
        raise ValueError("frozen-date column gate did not pass")
    observations = parsed.get("observations") or {}
    actual = {
        concept: str(
            (observations.get(concept) or {}).get("normalized_cny_value")
        )
        for concept in CONCEPTS
    }
    if actual != EXPECTED_VALUES:
        raise ValueError(f"unexpected target values {actual}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", required=True)
    parser.add_argument("--v17-21-root", required=True)
    parser.add_argument("--shard", required=True, type=int)
    parser.add_argument("--shards", default=64, type=int)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.shards != 64 or args.shard not in EXPECTED_SHARDS:
        raise ValueError(
            "V17.24 replay is frozen to shards 0,1,7,9 "
            "of the accepted 64-shard partition"
        )

    residuals = _load_exact79(Path(args.v17_21_root))
    versions = [
        row
        for row in accepted.read_versions(Path(args.versions))
        if row["canonical_announcement_id"] in residuals
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
            expected_sha = residuals[aid]["source_sha256"]
            if digest != expected_sha:
                raise ValueError(
                    f"source SHA changed expected={expected_sha} actual={digest}"
                )
            parsed = candidate.parse_pdf_bytes(raw, row["economic_date"])
            recovered = _validated(parsed)
            block = parsed.get("balance_sheet_block")
            errors = list(parsed.get("validation_errors") or [])
            if aid in EXPECTED_RECOVERY:
                _require_target(parsed)
            else:
                if recovered or block is not None:
                    raise ValueError(
                        "unexpected V17.24 recovery outside accepted exact-one set"
                    )
                if not errors:
                    raise ValueError(
                        "non-recovered residual lost fail-closed validation errors"
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
                    "candidate_recovered": recovered,
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
            f"S3G1J_V17_24_EXACT79 shard={args.shard} "
            f"{index}/{len(versions)} aid={aid}",
            flush=True,
        )

    recovered_ids = sorted(
        row["announcement_id"]
        for row in results
        if row["candidate_recovered"]
    )
    report = {
        "gate": "S3G1J_V17_24_EXACT_79_CANDIDATE_SAFETY_SHARD",
        "candidate_only": True,
        "production_parser_changed": False,
        "expected_recovery_announcement_ids": sorted(EXPECTED_RECOVERY),
        "shard": args.shard,
        "shards": args.shards,
        "input_count": len(versions),
        "processed_count": len(results),
        "source_sha_match_count": len(results),
        "candidate_recovered_count": len(recovered_ids),
        "candidate_recovered_announcement_ids": recovered_ids,
        "results": results,
        "execution_failures": failures,
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "global_row_tolerance_changed": False,
        "corrupted_equity_alias": "所有者权益（或d股东权益）合计",
        "corrupted_equity_amount_column_count": 2,
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
                "input_count": len(versions),
                "processed_count": len(results),
                "candidate_recovered_announcement_ids": recovered_ids,
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
