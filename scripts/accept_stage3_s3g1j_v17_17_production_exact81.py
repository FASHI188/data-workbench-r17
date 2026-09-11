#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

import requests

import extract_stage3_financial_pdf_values as base
import extract_stage3_financial_pdf_values_v12 as production

EXPECTED_TOTAL = 81
EXPECTED_SHARDS = (0, 1, 7, 9)
EXPECTED_RECOVERY = {"1212731093"}
BALANCE_CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
EXPECTED_ARBITRATION = "V17_17_GROUP_PERIOD_STRICT_PAIRED_HEADER_A_EQUALS_L_PLUS_E_EXPLICIT_TOTAL_EQUITY"
EXPECTED_HEADER_SOURCE = "V17_17_STRICT_THREE_COLUMN_TWO_ROW_YEAR_MONTH_DAY_HEADER"


def read_versions(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.17-production-exact81-acceptance",
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
    return all((observations.get(concept) or {}).get("status") == "FOUND" for concept in BALANCE_CONCEPTS)


def validated_balance_recovered(parsed: dict) -> bool:
    return (
        raw_balance_fields_found(parsed)
        and isinstance(parsed.get("balance_sheet_block"), dict)
        and not list(parsed.get("validation_errors") or [])
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--v17-11-acceptance", required=True)
    ap.add_argument("--v17-15-summary", required=True)
    ap.add_argument("--shard", required=True, type=int)
    ap.add_argument("--shards", default=64, type=int)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.shards != 64 or args.shard not in EXPECTED_SHARDS:
        raise ValueError("acceptance frozen to shards 0,1,7,9 of the accepted 64-shard partition")

    accepted = json.loads(Path(args.v17_11_acceptance).read_text(encoding="utf-8"))
    source_rows = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if not accepted.get("pass") or len(source_rows) != 82:
        raise ValueError("not the accepted V17.11 exact-82 source state")

    previous = json.loads(Path(args.v17_15_summary).read_text(encoding="utf-8"))
    remaining_ids = {str(x) for x in previous.get("remaining_announcement_ids") or []}
    if not previous.get("pass") or int(previous.get("remaining_count", -1)) != EXPECTED_TOTAL:
        raise ValueError("not the accepted V17.15 exact-81 state")
    if len(remaining_ids) != EXPECTED_TOTAL or not remaining_ids.issubset(source_rows):
        raise ValueError("V17.15 remaining IDs do not reconcile to V17.11 source state")

    rows = [
        row for row in read_versions(Path(args.versions))
        if row["canonical_announcement_id"] in remaining_ids
        and base.stable_shard(row["canonical_announcement_id"], args.shards) == args.shard
    ]
    rows.sort(key=lambda row: row["canonical_announcement_id"])

    session = requests.Session()
    results: list[dict] = []
    failures: list[dict] = []
    for index, row in enumerate(rows, 1):
        aid = row["canonical_announcement_id"]
        try:
            raw = download(session, row["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            if digest != source_rows[aid]["sha256"]:
                raise ValueError(
                    f"source SHA changed expected={source_rows[aid]['sha256']} actual={digest}"
                )
            parsed = production.parse_pdf_bytes(raw, row["economic_date"])
            raw_found = raw_balance_fields_found(parsed)
            validated = validated_balance_recovered(parsed)
            block = parsed.get("balance_sheet_block")
            errors = list(parsed.get("validation_errors") or [])
            expected_found = aid in EXPECTED_RECOVERY

            if expected_found:
                if not validated:
                    raise ValueError(
                        f"intended production recovery is not a validated A/L/E block "
                        f"raw_found={raw_found} block={block} errors={errors}"
                    )
                if block.get("arbitration") != EXPECTED_ARBITRATION:
                    raise ValueError(f"unexpected arbitration {block.get('arbitration')}")
                if block.get("identity_tolerance") != "0.005":
                    raise ValueError(f"identity tolerance changed {block.get('identity_tolerance')}")
                if str(block.get("identity_residual_cny")) not in {"0", "0.0", "0.00"}:
                    raise ValueError(f"identity residual is not zero {block.get('identity_residual_cny')}")
                if block.get("adjacent_row_bridge_selected_concepts") != ["TOTAL_ASSETS", "TOTAL_LIABILITIES"]:
                    raise ValueError(
                        f"unexpected bridge concepts {block.get('adjacent_row_bridge_selected_concepts')}"
                    )
                if block.get("strict_total_equity_selected_concepts") != ["TOTAL_EQUITY"]:
                    raise ValueError(
                        f"unexpected strict equity concepts {block.get('strict_total_equity_selected_concepts')}"
                    )
                if block.get("strict_total_equity_alias") != "股东权益总计":
                    raise ValueError(f"unexpected strict equity alias {block.get('strict_total_equity_alias')}")
                if block.get("paired_header_evidence_source") != EXPECTED_HEADER_SOURCE:
                    raise ValueError(f"unexpected header source {block.get('paired_header_evidence_source')}")
                if block.get("paired_header_expected_column_index") != 0:
                    raise ValueError("frozen-date header did not select first column")
                if block.get("paired_header_column_count") != 3:
                    raise ValueError("paired header is not exact three-column evidence")
                if block.get("e_equals_a_minus_l_inference") is not False:
                    raise ValueError("equity was inferred instead of explicitly extracted")
                if block.get("global_row_tolerance_changed") is not False:
                    raise ValueError("global row tolerance changed")
                observations = parsed.get("observations") or {}
                expected_values = {
                    "TOTAL_ASSETS": "20214466018.97",
                    "TOTAL_LIABILITIES": "13296884507.65",
                    "TOTAL_EQUITY": "6917581511.32",
                }
                actual_values = {
                    concept: str((observations.get(concept) or {}).get("normalized_cny_value"))
                    for concept in BALANCE_CONCEPTS
                }
                if actual_values != expected_values:
                    raise ValueError(f"unexpected recovered values {actual_values}")
            else:
                if validated or block is not None:
                    raise ValueError("unexpected validated production recovery outside accepted exact-one set")
                if not errors:
                    raise ValueError("non-recovered residual lost fail-closed validation errors")

            results.append({
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
            })
        except Exception as exc:
            failures.append({
                "announcement_id": aid,
                "source_code": row.get("source_code"),
                "error": f"{type(exc).__name__}: {exc}",
            })
        print(
            f"S3G1J_V17_17_PRODUCTION_EXACT81 shard={args.shard} {index}/{len(rows)} aid={aid}",
            flush=True,
        )

    recovered_ids = sorted(
        row["announcement_id"] for row in results if row["production_balance_sheet_recovered"]
    )
    raw_found_ids = sorted(
        row["announcement_id"] for row in results if row["raw_balance_fields_found"]
    )
    report = {
        "gate": "S3G1J_V17_17_PRODUCTION_EXACT_81_ACCEPTANCE_SHARD",
        "production_parser_changed": True,
        "production_method": production.METHOD,
        "recovery_definition": "A_L_E_FOUND_AND_VALIDATED_BALANCE_SHEET_BLOCK_AND_NO_VALIDATION_ERRORS",
        "accounting_tolerance": "0.005",
        "global_row_tolerance_changed": False,
        "strict_equity_label": "股东权益总计",
        "paired_header_source": EXPECTED_HEADER_SOURCE,
        "e_equals_a_minus_l_inference": False,
        "source_policy_changed": False,
        "shard": args.shard,
        "shards": args.shards,
        "input_count": len(rows),
        "processed_count": len(results),
        "source_sha_match_count": len(results),
        "raw_balance_fields_found_count": len(raw_found_ids),
        "raw_balance_fields_found_announcement_ids": raw_found_ids,
        "recovered_count": len(recovered_ids),
        "recovered_announcement_ids": recovered_ids,
        "results": results,
        "execution_failures": failures,
        "pass": not failures and len(results) == len(rows),
        "stage4_alpha_locked": True,
        "errors": failures,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "shard": args.shard,
        "input_count": len(rows),
        "processed_count": len(results),
        "raw_balance_fields_found_announcement_ids": raw_found_ids,
        "recovered_announcement_ids": recovered_ids,
        "failures": failures,
        "pass": report["pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
