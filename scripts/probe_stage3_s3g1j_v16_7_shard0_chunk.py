#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import requests

import extract_stage3_financial_pdf_values as base
import probe_stage3_s3g1j_v16_7_exact_113_replay as exact

SHARD = 0
SHARDS = 64
EXPECTED_INPUT = 41
EXPECTED_V14_REMAINING = 36


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--part", type=int, required=True)
    ap.add_argument("--parts", type=int, default=8)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.parts <= 0 or args.part < 0 or args.part >= args.parts:
        raise ValueError("invalid part/parts")

    all_rows = exact.read_rows(Path(args.versions))
    shard_rows = [
        row for row in all_rows
        if base.stable_shard(row["canonical_announcement_id"], SHARDS) == SHARD
    ]
    if len(shard_rows) != EXPECTED_INPUT:
        raise ValueError(f"frozen shard0 input mismatch expected={EXPECTED_INPUT} actual={len(shard_rows)}")

    rows = [row for idx, row in enumerate(shard_rows) if idx % args.parts == args.part]
    session = requests.Session()

    v14_pass: list[dict] = []
    recovered: list[dict] = []
    remaining: list[dict] = []
    old_path_regressions: list[dict] = []
    download_failures: list[dict] = []
    processing_failures: list[dict] = []
    errors: list[str] = []

    for idx, row in enumerate(rows, 1):
        aid = row["canonical_announcement_id"]
        started = time.monotonic()
        print(
            f"SHARD0_CHUNK_START part={args.part}/{args.parts} row={idx}/{len(rows)} "
            f"aid={aid} code={row['source_code']} family={row['report_family']} date={row['economic_date']}",
            flush=True,
        )

        try:
            raw = exact.download(session, row["canonical_source_url"])
        except Exception as exc:
            rec = {
                "announcement_id": aid,
                "source_code": row["source_code"],
                "url": row["canonical_source_url"],
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
            download_failures.append(rec)
            print(f"SHARD0_CHUNK_DOWNLOAD_FAIL {json.dumps(rec, ensure_ascii=False)}", flush=True)
            continue

        digest = hashlib.sha256(raw).hexdigest()
        try:
            old = exact.v14_parse(raw)
            new = exact.v16_parse(raw, row["economic_date"])
        except Exception as exc:
            rec = {
                "announcement_id": aid,
                "source_code": row["source_code"],
                "sha256": digest,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
            processing_failures.append(rec)
            print(f"SHARD0_CHUNK_PROCESS_FAIL {json.dumps(rec, ensure_ascii=False)}", flush=True)
            continue

        old_ok = exact.valid(old)
        new_ok = exact.valid(new)
        outcome = "V16_REMAINING"
        if old_ok:
            same_obs = exact.balance_obs(old) == exact.balance_obs(new)
            same_block = (old.get("balance_sheet_block") or {}) == (new.get("balance_sheet_block") or {})
            arbitration = str((new.get("balance_sheet_block") or {}).get("arbitration") or "")
            unchanged = same_obs and same_block and arbitration.startswith("V14_") and new_ok
            rec = {
                "announcement_id": aid,
                "source_code": row["source_code"],
                "economic_date": row["economic_date"],
                "sha256": digest,
                "same_balance_observations": same_obs,
                "same_balance_sheet_block": same_block,
                "new_arbitration": arbitration,
                "unchanged": unchanged,
            }
            v14_pass.append(rec)
            if not unchanged:
                old_path_regressions.append(rec)
            outcome = "V14_UNCHANGED" if unchanged else "V14_REGRESSION"
        elif new_ok:
            evidence = exact.recovery_evidence(row, new, digest)
            recovered.append(evidence)
            if not (
                evidence["arbitration_ok"]
                and evidence["expected_date_ok"]
                and evidence["period_gate_ok"]
                and evidence["column_gate_ok"]
            ):
                errors.append(f"V16 recovery missing hard evidence {aid}: {evidence}")
            outcome = "V16_RECOVERED"
        else:
            remaining.append({
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

        print(
            f"SHARD0_CHUNK_DONE part={args.part}/{args.parts} aid={aid} outcome={outcome} "
            f"elapsed={time.monotonic() - started:.3f}s bytes={len(raw)} sha256={digest}",
            flush=True,
        )

    if old_path_regressions:
        errors.append(f"V14 success path regressions={len(old_path_regressions)}")
    if download_failures:
        errors.append(f"download failures={len(download_failures)}")
    if processing_failures:
        errors.append(f"processing failures={len(processing_failures)}")

    report = {
        "gate": "S3G1J_V16_7_SHARD0_SPLIT_DIAGNOSTIC_CHUNK",
        "shard": SHARD,
        "shards": SHARDS,
        "part": args.part,
        "parts": args.parts,
        "input_count": len(rows),
        "announcement_ids": [row["canonical_announcement_id"] for row in rows],
        "v14_success_count": len(v14_pass),
        "v14_remaining_count": len(recovered) + len(remaining),
        "v16_new_recovery_count": len(recovered),
        "v16_remaining_count": len(remaining),
        "v14_success_paths": v14_pass,
        "v14_success_path_regressions": old_path_regressions,
        "v16_new_recoveries": recovered,
        "v16_remaining": remaining,
        "download_failures": download_failures,
        "processing_failures": processing_failures,
        "pass": not errors,
        "errors": errors,
        "stage4_alpha_locked": True,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "part": args.part,
        "parts": args.parts,
        "input": len(rows),
        "v14_success": len(v14_pass),
        "v14_remaining": len(recovered) + len(remaining),
        "v16_new_recovery": len(recovered),
        "v16_remaining": len(remaining),
        "download_failures": len(download_failures),
        "processing_failures": len(processing_failures),
        "pass": report["pass"],
    }, ensure_ascii=False), flush=True)
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
