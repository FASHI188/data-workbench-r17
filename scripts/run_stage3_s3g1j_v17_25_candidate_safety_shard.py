#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import fitz
import requests

import accept_stage3_s3g1j_v17_25_candidate_safety as common
import stage3_financial_statement_blocks_v17_25 as candidate_blocks


def selected_ids(all_ids: list[str], shard_index: int, shard_count: int) -> list[str]:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index outside geometry")
    return [aid for index, aid in enumerate(sorted(all_ids)) if index % shard_count == shard_index]


def process_p0(
    rows: dict[str, dict],
    ids: list[str],
    session: requests.Session,
) -> tuple[list[dict], list[dict], int]:
    results: list[dict] = []
    failures: list[dict] = []
    source_sha_matches = 0
    for index, aid in enumerate(ids, 1):
        row = rows[aid]
        try:
            raw = common.download(session, row["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            if digest != row["source_sha256"]:
                raise ValueError(
                    f"P0 source SHA changed expected={row['source_sha256']} actual={digest}"
                )
            if len(raw) != int(row["source_bytes"]):
                raise ValueError("P0 source byte length changed")
            source_sha_matches += 1

            with fitz.open(stream=raw, filetype="pdf") as doc:
                witness = candidate_blocks.diagnose_generic_group_witness(doc)
            should_witness = aid in common.EXPECTED_WITNESS_IDS
            promoted_count = int(witness["promoted_generic_group_count"])
            if should_witness and promoted_count != 1:
                raise ValueError(
                    f"expected exactly one generic GROUP witness, got {promoted_count}"
                )
            if not should_witness and promoted_count != 0:
                raise ValueError("unexpected generic GROUP witness")

            current, proposed = common.parse_pair(raw, row["economic_date"])
            if common.recovered(current):
                raise ValueError("accepted V17.24 unexpectedly recovers P0 residual")
            proposed_recovered = common.recovered(proposed)
            if proposed_recovered and not should_witness:
                raise ValueError("candidate recovered outside exact witness population")
            if proposed_recovered:
                common.require_candidate_recovery_safety(aid, proposed)
            elif not list(proposed.get("validation_errors") or []):
                raise ValueError("fail-closed candidate lost validation errors")

            results.append(
                {
                    "announcement_id": aid,
                    "source_code": row["source_code"],
                    "report_family": row["report_family"],
                    "economic_date": row["economic_date"],
                    "diagnostic_signature": row["diagnostic_signature"],
                    "source_sha256": digest,
                    "expected_group_witness": should_witness,
                    "group_witness_diagnostic": witness,
                    "current_v17_24_recovered": False,
                    "candidate_v17_25_recovered": proposed_recovered,
                    "candidate_balance_sheet_block": proposed.get("balance_sheet_block"),
                    "candidate_validation_errors": list(
                        proposed.get("validation_errors") or []
                    ),
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "scope": "P0",
                    "announcement_id": aid,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(f"S3G1J_V17_25_P0_SHARD {index}/{len(ids)} aid={aid}", flush=True)
    return results, failures, source_sha_matches


def process_exact82(
    rows: dict[str, dict],
    ids: list[str],
    session: requests.Session,
) -> tuple[list[dict], list[dict], int]:
    results: list[dict] = []
    failures: list[dict] = []
    source_sha_matches = 0
    for index, aid in enumerate(ids, 1):
        baseline = rows[aid]
        try:
            raw = common.download(session, baseline["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            if digest != baseline["source_sha256"]:
                raise ValueError(
                    f"exact82 source SHA changed expected={baseline['source_sha256']} actual={digest}"
                )
            source_sha_matches += 1
            current, proposed = common.parse_pair(raw, baseline["economic_date"])
            expected_recovered = bool(baseline["production_balance_sheet_recovered"])
            if common.recovered(current) != expected_recovered:
                raise ValueError("current V17.24 exact82 recovery state changed")
            if current.get("balance_sheet_block") != baseline.get("balance_sheet_block"):
                raise ValueError("current V17.24 exact82 block changed")
            if list(current.get("validation_errors") or []) != list(
                baseline.get("validation_errors") or []
            ):
                raise ValueError("current V17.24 exact82 validation errors changed")
            if common.recovered(proposed) != expected_recovered:
                raise ValueError("candidate changed exact82 recovery state")
            if proposed.get("balance_sheet_block") != current.get("balance_sheet_block"):
                raise ValueError("candidate changed exact82 balance-sheet block")
            if list(proposed.get("validation_errors") or []) != list(
                current.get("validation_errors") or []
            ):
                raise ValueError("candidate changed exact82 validation errors")
            results.append(
                {
                    "announcement_id": aid,
                    "source_sha256": digest,
                    "recovered": expected_recovered,
                    "block_equal": True,
                    "validation_errors_equal": True,
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "scope": "EXACT82",
                    "announcement_id": aid,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(f"S3G1J_V17_25_EXACT82_SHARD {index}/{len(ids)} aid={aid}", flush=True)
    return results, failures, source_sha_matches


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p0-report", required=True)
    parser.add_argument("--v17-24-root", required=True)
    parser.add_argument("--scope", choices=("p0", "exact82"), required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    p0 = json.loads(Path(args.p0_report).read_text(encoding="utf-8"))
    if p0.get("pass") is not True or p0.get("errors"):
        raise ValueError("P0 source diagnostic is not accepted")
    p0_rows = {str(row["announcement_id"]): row for row in p0.get("results") or []}
    if len(p0_rows) != 22:
        raise ValueError(f"expected 22 P0 rows, got {len(p0_rows)}")
    exact82 = common.load_exact82(Path(args.v17_24_root))

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "data-workbench-r17-stage3-v17-25-candidate-safety-shard/1.0",
            "Accept": "application/pdf,*/*;q=0.8",
        }
    )

    source_rows = p0_rows if args.scope == "p0" else exact82
    ids = selected_ids(list(source_rows), args.shard_index, args.shard_count)
    if not ids:
        raise ValueError("empty shard")
    if args.scope == "p0":
        results, failures, source_sha_matches = process_p0(p0_rows, ids, session)
    else:
        results, failures, source_sha_matches = process_exact82(exact82, ids, session)

    report = {
        "gate": "S3G1J_V17_25_GENERIC_GROUP_WITNESS_CANDIDATE_SAFETY_SHARD",
        "scope": args.scope,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "selected_announcement_ids": ids,
        "selected_count": len(ids),
        "processed_count": len(results),
        "source_sha_match_count": source_sha_matches,
        "results": results,
        "execution_failures": failures,
        "candidate_only": True,
        "production_runtime_changed": False,
        "accounting_tolerance": "0.005",
        "source_policy_changed": False,
        "e_equals_a_minus_l_inference": False,
        "pass": (
            not failures
            and len(results) == len(ids)
            and source_sha_matches == len(ids)
        ),
        "errors": failures,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "results"},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
