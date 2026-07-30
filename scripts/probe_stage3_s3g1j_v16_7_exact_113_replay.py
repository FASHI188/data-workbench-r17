#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import time
from pathlib import Path

import requests

import extract_stage3_financial_pdf_values as base
import stage3_financial_pdf_parser_v10 as v16_runtime
from stage3_financial_pdf_parser_v9 import parse_pdf_bytes as _v14_parse
from stage3_financial_pdf_parser_v10 import parse_pdf_bytes as v16_parse

EXPECTED_INPUT = {0: 41, 1: 31, 7: 32, 9: 23}
EXPECTED_V14_REMAINING = {0: 36, 1: 28, 7: 27, 9: 22}
V16_ARBITRATION = "V16_7_GROUP_PERIOD_FROZEN_DATE_COLUMN_A_EQUALS_L_PLUS_E"
BALANCE_CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")


def v14_parse(raw: bytes) -> dict:
    """Run the frozen V14 parser with diagnostics bounded, never semantics changed."""
    with v16_runtime._mupdf_diagnostic_guard():
        return _v14_parse(raw)


def read_rows(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def download(session: requests.Session, url: str, attempts: int = 6) -> bytes:
    last = None
    for attempt in range(attempts):
        try:
            response = session.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 S3G1J-V16.7-exact-113-replay",
                    "Referer": "https://www.cninfo.com.cn/",
                },
                timeout=120,
            )
            response.raise_for_status()
            raw = response.content
            if not raw.startswith(b"%PDF"):
                raise ValueError(f"not PDF bytes={len(raw)}")
            return raw
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(min(0.8 * (2 ** attempt), 10))
    raise RuntimeError(repr(last))


def valid(parsed: dict) -> bool:
    return bool(parsed.get("balance_sheet_block")) and not bool(parsed.get("validation_errors"))


def balance_obs(parsed: dict) -> dict:
    observations = parsed.get("observations") or {}
    return {concept: observations.get(concept) for concept in BALANCE_CONCEPTS}


def recovery_evidence(row: dict, parsed: dict, digest: str) -> dict:
    block = parsed.get("balance_sheet_block") or {}
    observations = parsed.get("observations") or {}
    values = {
        concept: {
            "raw_value": (observations.get(concept) or {}).get("raw_value"),
            "normalized_cny_value": (observations.get(concept) or {}).get("normalized_cny_value"),
            "unit": (observations.get(concept) or {}).get("unit"),
            "page": (observations.get(concept) or {}).get("page"),
            "matched_alias": (observations.get(concept) or {}).get("matched_alias"),
        }
        for concept in BALANCE_CONCEPTS
    }
    period = block.get("selected_period_evidence") or {}
    column = block.get("column_role_evidence") or {}
    period_ok = all(bool((period.get(concept) or {}).get("matched")) for concept in BALANCE_CONCEPTS)
    column_ok = all(bool((column.get(concept) or {}).get("pass")) for concept in BALANCE_CONCEPTS)
    arbitration_ok = block.get("arbitration") == V16_ARBITRATION
    expected_date_ok = block.get("expected_economic_date") == row["economic_date"]
    return {
        "announcement_id": row["canonical_announcement_id"],
        "source_code": row["source_code"],
        "report_family": row["report_family"],
        "economic_date": row["economic_date"],
        "canonical_title": row["canonical_title"],
        "sha256": digest,
        "arbitration": block.get("arbitration"),
        "arbitration_ok": arbitration_ok,
        "expected_date_ok": expected_date_ok,
        "period_gate_ok": period_ok,
        "column_gate_ok": column_ok,
        "identity_relative_error": block.get("identity_relative_error"),
        "identity_residual_cny": block.get("identity_residual_cny"),
        "values": values,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--shards", type=int, default=64)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.shard not in EXPECTED_INPUT or args.shards != 64:
        raise ValueError("this diagnostic is frozen to shards 0,1,7,9 of the 64-shard partition")

    all_rows = read_rows(Path(args.versions))
    rows = [
        row for row in all_rows
        if base.stable_shard(row["canonical_announcement_id"], args.shards) == args.shard
    ]
    errors: list[str] = []
    if len(rows) != EXPECTED_INPUT[args.shard]:
        errors.append(f"input count mismatch expected={EXPECTED_INPUT[args.shard]} actual={len(rows)}")

    session = requests.Session()
    v14_pass = []
    v14_fail_v16_recovered = []
    v14_fail_v16_remaining = []
    download_failures = []
    old_path_regressions = []

    for idx, row in enumerate(rows, 1):
        aid = row["canonical_announcement_id"]
        try:
            raw = download(session, row["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            old = v14_parse(raw)
            new = v16_parse(raw, row["economic_date"])
        except Exception as exc:
            download_failures.append({"announcement_id": aid, "error": f"{type(exc).__name__}: {exc}"})
            continue

        old_ok = valid(old)
        new_ok = valid(new)
        if old_ok:
            same_obs = balance_obs(old) == balance_obs(new)
            same_block = (old.get("balance_sheet_block") or {}) == (new.get("balance_sheet_block") or {})
            arbitration = str((new.get("balance_sheet_block") or {}).get("arbitration") or "")
            unchanged = same_obs and same_block and arbitration.startswith("V14_") and new_ok
            record = {
                "announcement_id": aid,
                "source_code": row["source_code"],
                "economic_date": row["economic_date"],
                "sha256": digest,
                "same_balance_observations": same_obs,
                "same_balance_sheet_block": same_block,
                "new_arbitration": arbitration,
                "unchanged": unchanged,
            }
            v14_pass.append(record)
            if not unchanged:
                old_path_regressions.append(record)
        else:
            if new_ok:
                evidence = recovery_evidence(row, new, digest)
                v14_fail_v16_recovered.append(evidence)
                if not (
                    evidence["arbitration_ok"]
                    and evidence["expected_date_ok"]
                    and evidence["period_gate_ok"]
                    and evidence["column_gate_ok"]
                ):
                    errors.append(f"V16 recovery missing hard evidence {aid}: {evidence}")
            else:
                v14_fail_v16_remaining.append({
                    "announcement_id": aid,
                    "source_code": row["source_code"],
                    "report_family": row["report_family"],
                    "economic_date": row["economic_date"],
                    "canonical_title": row["canonical_title"],
                    "sha256": digest,
                    "v14_validation_errors": old.get("validation_errors") or [],
                    "v16_validation_errors": new.get("validation_errors") or [],
                    "v16_balance_sheet_block": new.get("balance_sheet_block"),
                    "v16_tier1_found": new.get("tier1_found"),
                    "v16_tier2_found": new.get("tier2_found"),
                })

        if idx % 10 == 0:
            print(f"V16_113_REPLAY shard={args.shard} {idx}/{len(rows)}", flush=True)

    v14_remaining = len(v14_fail_v16_recovered) + len(v14_fail_v16_remaining)
    expected_v14_remaining = EXPECTED_V14_REMAINING[args.shard]
    if v14_remaining != expected_v14_remaining:
        errors.append(f"V14 baseline mismatch expected={expected_v14_remaining} actual={v14_remaining}")
    if old_path_regressions:
        errors.append(f"V14 success path regressions={len(old_path_regressions)}")
    if download_failures:
        errors.append(f"download failures={len(download_failures)}")

    report = {
        "gate": "S3G1J_V16_7_EXACT_113_SINGLE_SOURCE_REPLAY_SHARD",
        "shard": args.shard,
        "shards": args.shards,
        "input_single_source_count": len(rows),
        "expected_input_single_source_count": EXPECTED_INPUT[args.shard],
        "v14_success_count": len(v14_pass),
        "v14_remaining_count": v14_remaining,
        "expected_v14_remaining_count": expected_v14_remaining,
        "v16_new_recovery_count": len(v14_fail_v16_recovered),
        "v16_remaining_count": len(v14_fail_v16_remaining),
        "v14_success_path_regressions": old_path_regressions,
        "v16_new_recoveries": v14_fail_v16_recovered,
        "v16_remaining": v14_fail_v16_remaining,
        "download_failures": download_failures,
        "pass": not errors,
        "errors": errors,
        "stage4_alpha_locked": True,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "shard": args.shard,
        "input": len(rows),
        "v14_success": len(v14_pass),
        "v14_remaining": v14_remaining,
        "v16_new_recovery": len(v14_fail_v16_recovered),
        "v16_remaining": len(v14_fail_v16_remaining),
        "pass": report["pass"],
        "errors": errors,
    }, ensure_ascii=False))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
