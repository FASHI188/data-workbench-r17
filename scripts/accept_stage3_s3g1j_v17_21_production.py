#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import glob
import gzip
import hashlib
import json
from pathlib import Path

import requests

import extract_stage3_financial_pdf_values as base
import extract_stage3_financial_pdf_values_v13 as production

EXPECTED_SHARDS = (0, 1, 7, 9)
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
V17_15_ID = "1225153907"
V17_17_ID = "1212731093"
V17_21_ID = "1219311356"
V17_15_ARBITRATION = "V17_15_GROUP_PERIOD_FROZEN_DATE_COLUMN_A_EQUALS_L_PLUS_E_STRICT_ADJACENT_ROW"
V17_17_ARBITRATION = "V17_17_GROUP_PERIOD_STRICT_PAIRED_HEADER_A_EQUALS_L_PLUS_E_EXPLICIT_TOTAL_EQUITY"
V17_21_ARBITRATION = "V17_21_GROUP_PERIOD_FROZEN_DATE_A_EQUALS_L_PLUS_E_EXACT_REVERSE_ASSET_TOTAL"


def read_versions(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.21-production-acceptance",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def raw_balance_fields_found(parsed: dict) -> bool:
    observations = parsed.get("observations") or {}
    return all((observations.get(concept) or {}).get("status") == "FOUND" for concept in CONCEPTS)


def validated_balance_recovered(parsed: dict) -> bool:
    return (
        raw_balance_fields_found(parsed)
        and isinstance(parsed.get("balance_sheet_block"), dict)
        and not list(parsed.get("validation_errors") or [])
    )


def load_v17_18_rows(root: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for path in sorted(glob.glob(str(root / "shard*.json"))):
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        if not report.get("pass"):
            raise ValueError(f"V17.18 source shard not pass: {path}")
        for row in report.get("diagnostics") or []:
            aid = str(row["announcement_id"])
            if aid in rows:
                raise ValueError(f"duplicate V17.18 source row {aid}")
            rows[aid] = row
    if len(rows) != 80:
        raise ValueError(f"expected exact 80 V17.18 rows, got {len(rows)}")
    return rows


def load_v17_11_rows(path: Path) -> dict[str, dict]:
    accepted = json.loads(path.read_text(encoding="utf-8"))
    rows = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if not accepted.get("pass") or int(accepted.get("v17_11_remaining_count", -1)) != 82:
        raise ValueError("not the accepted V17.11 exact-82 source state")
    if len(rows) != 82:
        raise ValueError(f"expected exact 82 V17.11 rows, got {len(rows)}")
    return rows


def require_common_validated_block(aid: str, parsed: dict) -> dict:
    if not validated_balance_recovered(parsed):
        raise ValueError(
            f"{aid} intended recovery is not validated: "
            f"block={parsed.get('balance_sheet_block')} errors={parsed.get('validation_errors')}"
        )
    block = parsed["balance_sheet_block"]
    if block.get("identity_tolerance") != "0.005":
        raise ValueError(f"{aid} identity tolerance changed {block.get('identity_tolerance')}")
    if block.get("global_row_tolerance_changed") is not False:
        raise ValueError(f"{aid} global row tolerance changed")
    if list(parsed.get("validation_errors") or []):
        raise ValueError(f"{aid} intended recovery retains validation errors")
    return block


def require_expected_recovery(aid: str, parsed: dict) -> None:
    block = require_common_validated_block(aid, parsed)
    arbitration = block.get("arbitration")
    observations = parsed.get("observations") or {}

    if aid == V17_15_ID:
        if arbitration != V17_15_ARBITRATION:
            raise ValueError(f"{aid} unexpected arbitration {arbitration}")
        if block.get("adjacent_row_bridge_selected_concepts") != ["TOTAL_EQUITY"]:
            raise ValueError(f"{aid} unexpected bridge concepts")
        return

    if aid == V17_17_ID:
        if arbitration != V17_17_ARBITRATION:
            raise ValueError(f"{aid} unexpected arbitration {arbitration}")
        if block.get("adjacent_row_bridge_selected_concepts") != ["TOTAL_ASSETS", "TOTAL_LIABILITIES"]:
            raise ValueError(f"{aid} unexpected bridge concepts")
        if block.get("strict_total_equity_selected_concepts") != ["TOTAL_EQUITY"]:
            raise ValueError(f"{aid} missing explicit total-equity path")
        if block.get("strict_total_equity_alias") != "股东权益总计":
            raise ValueError(f"{aid} unexpected equity alias")
        if block.get("e_equals_a_minus_l_inference") is not False:
            raise ValueError(f"{aid} equity inference unexpectedly enabled")
        expected = {
            "TOTAL_ASSETS": "20214466018.97",
            "TOTAL_LIABILITIES": "13296884507.65",
            "TOTAL_EQUITY": "6917581511.32",
        }
    elif aid == V17_21_ID:
        if arbitration != V17_21_ARBITRATION:
            raise ValueError(f"{aid} unexpected arbitration {arbitration}")
        if block.get("reverse_asset_total_selected_concepts") != ["TOTAL_ASSETS"]:
            raise ValueError(f"{aid} missing exact reverse asset-total path")
        if block.get("reverse_asset_total_alias") != "资产总计":
            raise ValueError(f"{aid} unexpected asset alias")
        if block.get("reverse_asset_total_y_delta") != "5.87994384765625":
            raise ValueError(f"{aid} unexpected reverse y delta {block.get('reverse_asset_total_y_delta')}")
        if block.get("reverse_asset_total_y_window") != "5.50 <= delta <= 6.25":
            raise ValueError(f"{aid} reverse y window changed")
        if block.get("reverse_asset_total_amount_column_count") != 2:
            raise ValueError(f"{aid} reverse amount column count changed")
        if block.get("e_equals_a_minus_l_inference") is not False:
            raise ValueError(f"{aid} A/L/E inference unexpectedly enabled")
        if str(block.get("identity_residual_cny")) not in {"0", "0.0", "0.00"}:
            raise ValueError(f"{aid} identity residual is not zero {block.get('identity_residual_cny')}")
        expected = {
            "TOTAL_ASSETS": "73523417381.93",
            "TOTAL_LIABILITIES": "35828459679.63",
            "TOTAL_EQUITY": "37694957702.30",
        }
    else:
        raise ValueError(f"unexpected recovery id {aid}")

    actual = {
        concept: str((observations.get(concept) or {}).get("normalized_cny_value"))
        for concept in CONCEPTS
    }
    if actual != expected:
        raise ValueError(f"{aid} unexpected recovered values {actual}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("exact80", "exact82"))
    parser.add_argument("--versions", required=True)
    parser.add_argument("--v17-11-acceptance", required=True)
    parser.add_argument("--v17-18-candidate-root")
    parser.add_argument("--shard", required=True, type=int)
    parser.add_argument("--shards", default=64, type=int)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.shards != 64 or args.shard not in EXPECTED_SHARDS:
        raise ValueError("acceptance frozen to shards 0,1,7,9 of the accepted 64-shard partition")

    source82 = load_v17_11_rows(Path(args.v17_11_acceptance))
    if args.mode == "exact80":
        if not args.v17_18_candidate_root:
            raise ValueError("exact80 requires --v17-18-candidate-root")
        residual80 = load_v17_18_rows(Path(args.v17_18_candidate_root))
        expected_rows = {
            aid: {
                "sha256": row["source_sha256"],
            }
            for aid, row in residual80.items()
        }
        if not set(expected_rows).issubset(source82):
            raise ValueError("V17.18 exact80 rows do not reconcile to V17.11 source state")
        expected_recovery = {V17_21_ID}
        expected_total = 80
    else:
        expected_rows = source82
        expected_recovery = {V17_15_ID, V17_17_ID, V17_21_ID}
        expected_total = 82

    versions = [
        row
        for row in read_versions(Path(args.versions))
        if row["canonical_announcement_id"] in expected_rows
        and base.stable_shard(row["canonical_announcement_id"], args.shards) == args.shard
    ]
    versions.sort(key=lambda row: row["canonical_announcement_id"])

    session = requests.Session()
    results: list[dict] = []
    failures: list[dict] = []
    for index, row in enumerate(versions, 1):
        aid = row["canonical_announcement_id"]
        try:
            raw = download(session, row["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            if digest != expected_rows[aid]["sha256"]:
                raise ValueError(
                    f"source SHA changed expected={expected_rows[aid]['sha256']} actual={digest}"
                )
            parsed = production.parse_pdf_bytes(raw, row["economic_date"])
            raw_found = raw_balance_fields_found(parsed)
            validated = validated_balance_recovered(parsed)
            block = parsed.get("balance_sheet_block")
            errors = list(parsed.get("validation_errors") or [])

            if aid in expected_recovery:
                require_expected_recovery(aid, parsed)
            else:
                if validated or block is not None:
                    raise ValueError("unexpected validated production recovery outside accepted set")
                if not errors:
                    raise ValueError("non-recovered residual lost fail-closed validation errors")

            results.append(
                {
                    "announcement_id": aid,
                    "source_code": row["source_code"],
                    "report_family": row["report_family"],
                    "economic_date": row["economic_date"],
                    "canonical_title": row["canonical_title"],
                    "canonical_source_url": row["canonical_source_url"],
                    "source_sha256": digest,
                    "raw_balance_fields_found": raw_found,
                    "production_balance_sheet_recovered": validated,
                    "balance_sheet_block": block,
                    "validation_errors": errors,
                    "parser_version": parsed.get("parser_version"),
                    "extraction_method": production.METHOD,
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
            f"S3G1J_V17_21_PRODUCTION_{args.mode.upper()} "
            f"shard={args.shard} {index}/{len(versions)} aid={aid}",
            flush=True,
        )

    recovered = sorted(
        row["announcement_id"] for row in results if row["production_balance_sheet_recovered"]
    )
    report = {
        "gate": f"S3G1J_V17_21_PRODUCTION_{args.mode.upper()}_ACCEPTANCE_SHARD",
        "mode": args.mode,
        "production_parser_changed": True,
        "production_method": production.METHOD,
        "methodology_version": production.METHODOLOGY_VERSION,
        "recovery_definition": "A_L_E_FOUND_AND_VALIDATED_BALANCE_SHEET_BLOCK_AND_NO_VALIDATION_ERRORS",
        "expected_total": expected_total,
        "expected_recovery_announcement_ids": sorted(expected_recovery),
        "accounting_tolerance": "0.005",
        "global_row_tolerance_changed": False,
        "reverse_asset_y_window": "5.50 <= delta <= 6.25",
        "reverse_asset_amount_column_count": 2,
        "e_equals_a_minus_l_inference": False,
        "source_policy_changed": False,
        "shard": args.shard,
        "shards": args.shards,
        "input_count": len(versions),
        "processed_count": len(results),
        "source_sha_match_count": len(results),
        "recovered_count": len(recovered),
        "recovered_announcement_ids": recovered,
        "results": results,
        "execution_failures": failures,
        "pass": not failures and len(results) == len(versions),
        "stage4_alpha_locked": True,
        "errors": failures,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "mode": args.mode,
                "shard": args.shard,
                "input_count": len(versions),
                "processed_count": len(results),
                "recovered_announcement_ids": recovered,
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
