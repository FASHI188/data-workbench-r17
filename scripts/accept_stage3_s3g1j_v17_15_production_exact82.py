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
import extract_stage3_financial_pdf_values_v11 as production

EXPECTED_TOTAL = 82
EXPECTED_SHARDS = (0, 1, 7, 9)
EXPECTED_RECOVERY = {"1225153907"}
BALANCE_CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")


def read_versions(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.15-production-exact82-acceptance",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def balance_found(parsed: dict) -> bool:
    observations = parsed.get("observations") or {}
    return all((observations.get(concept) or {}).get("status") == "FOUND" for concept in BALANCE_CONCEPTS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--acceptance", required=True)
    ap.add_argument("--shard", required=True, type=int)
    ap.add_argument("--shards", default=64, type=int)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.shards != 64 or args.shard not in EXPECTED_SHARDS:
        raise ValueError("acceptance frozen to shards 0,1,7,9 of the accepted 64-shard partition")
    accepted = json.loads(Path(args.acceptance).read_text(encoding="utf-8"))
    if not accepted.get("pass") or int(accepted.get("v17_11_remaining_count", -1)) != EXPECTED_TOTAL:
        raise ValueError("not the accepted V17.11 exact-82 state")
    expected_rows = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if len(expected_rows) != EXPECTED_TOTAL:
        raise ValueError(f"expected 82 accepted residual rows, got {len(expected_rows)}")

    rows = [
        row for row in read_versions(Path(args.versions))
        if row["canonical_announcement_id"] in expected_rows
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
            if digest != expected_rows[aid]["sha256"]:
                raise ValueError(
                    f"source SHA changed expected={expected_rows[aid]['sha256']} actual={digest}"
                )
            parsed = production.parse_pdf_bytes(raw, row["economic_date"])
            found = balance_found(parsed)
            block = parsed.get("balance_sheet_block")
            errors = list(parsed.get("validation_errors") or [])
            expected_found = aid in EXPECTED_RECOVERY
            if expected_found:
                if not found:
                    raise ValueError(f"intended production recovery did not produce A/L/E: {errors}")
                if not isinstance(block, dict):
                    raise ValueError("intended production recovery missing balance_sheet_block metadata")
                if block.get("arbitration") != "V17_15_GROUP_PERIOD_FROZEN_DATE_COLUMN_A_EQUALS_L_PLUS_E_STRICT_ADJACENT_ROW":
                    raise ValueError(f"unexpected arbitration {block.get('arbitration')}")
                if block.get("identity_tolerance") != "0.005":
                    raise ValueError(f"identity tolerance changed {block.get('identity_tolerance')}")
                if block.get("adjacent_row_bridge_selected_concepts") != ["TOTAL_EQUITY"]:
                    raise ValueError(
                        f"unexpected bridge concepts {block.get('adjacent_row_bridge_selected_concepts')}"
                    )
                if block.get("global_row_tolerance_changed") is not False:
                    raise ValueError("global row tolerance changed")
                if errors:
                    raise ValueError(f"intended production recovery still has validation errors: {errors}")
            else:
                if found or block is not None:
                    raise ValueError("unexpected production recovery outside accepted exact-one set")
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
                "production_balance_sheet_recovered": found,
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
            f"S3G1J_V17_15_PRODUCTION_EXACT82 shard={args.shard} {index}/{len(rows)} aid={aid}",
            flush=True,
        )

    recovered_ids = sorted(
        row["announcement_id"] for row in results if row["production_balance_sheet_recovered"]
    )
    report = {
        "gate": "S3G1J_V17_15_PRODUCTION_EXACT_82_ACCEPTANCE_SHARD",
        "production_parser_changed": True,
        "production_method": production.METHOD,
        "accounting_tolerance": "0.005",
        "global_row_tolerance_changed": False,
        "bridge_y_window": "2.8 < delta <= 3.25",
        "source_policy_changed": False,
        "shard": args.shard,
        "shards": args.shards,
        "input_count": len(rows),
        "processed_count": len(results),
        "source_sha_match_count": len(results),
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
        "recovered_announcement_ids": recovered_ids,
        "failures": failures,
        "pass": report["pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
