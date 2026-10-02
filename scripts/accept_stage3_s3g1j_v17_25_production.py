#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import requests

import accept_stage3_s3g1j_v17_25_candidate_safety as evidence
import stage3_financial_pdf_parser_v15 as accepted
import stage3_financial_pdf_parser_v17 as production

TARGET_ANNOUNCEMENT_ID = "1207035181"
EXPECTED_V17_24_RECOVERIES = {
    "1212731093",
    "1219311356",
    "1221568845",
    "1225153907",
}
EXPECTED_V17_25_RECOVERIES = EXPECTED_V17_24_RECOVERIES | {
    TARGET_ANNOUNCEMENT_ID
}


def selected_ids(all_ids: list[str], shard: int, shards: int) -> list[str]:
    if shards <= 0 or shard < 0 or shard >= shards:
        raise ValueError("invalid shard geometry")
    return [aid for index, aid in enumerate(sorted(all_ids)) if index % shards == shard]


def load_target(p0_report: Path, candidate_report: Path) -> dict:
    p0 = json.loads(p0_report.read_text(encoding="utf-8"))
    if p0.get("pass") is not True or p0.get("errors"):
        raise ValueError("P0 source report is not accepted")
    p0_rows = {str(row["announcement_id"]): row for row in p0.get("results") or []}
    if len(p0_rows) != 22 or TARGET_ANNOUNCEMENT_ID not in p0_rows:
        raise ValueError("P0 target population changed")

    candidate = json.loads(candidate_report.read_text(encoding="utf-8"))
    if candidate.get("pass") is not True or candidate.get("errors"):
        raise ValueError("V17.25 candidate safety report is not accepted")
    if candidate.get("candidate_recovered_announcement_ids") != [TARGET_ANNOUNCEMENT_ID]:
        raise ValueError("V17.25 candidate recovery set changed")
    if int(candidate.get("source_sha_match_count", -1)) != 104:
        raise ValueError("V17.25 candidate source accounting changed")
    candidate_rows = {
        str(row["announcement_id"]): row
        for row in candidate.get("p0_results") or []
    }
    candidate_target = candidate_rows.get(TARGET_ANNOUNCEMENT_ID)
    if not candidate_target or candidate_target.get("candidate_v17_25_recovered") is not True:
        raise ValueError("accepted candidate target evidence missing")

    target = dict(p0_rows[TARGET_ANNOUNCEMENT_ID])
    if target.get("source_sha256") != production.TARGET_SOURCE_SHA256:
        raise ValueError("target source SHA differs from production parser lock")
    if target.get("economic_date") != production.TARGET_ECONOMIC_DATE:
        raise ValueError("target economic date differs from production parser lock")
    if candidate_target.get("source_sha256") != target.get("source_sha256"):
        raise ValueError("candidate/P0 target source SHA mismatch")
    target["scope"] = "V17_25_TARGET"
    return target


def validate_new_recovery(parsed: dict) -> None:
    if not evidence.recovered(parsed):
        raise ValueError("V17.25 production target did not recover")
    if parsed.get("parser_version") != production.METHOD:
        raise ValueError("V17.25 production parser identity changed")
    block = parsed.get("balance_sheet_block") or {}
    if block.get("arbitration") != (
        "V17_25_EXACT_SOURCE_GENERIC_GROUP_WITNESS_A_EQUALS_L_PLUS_E"
    ):
        raise ValueError("V17.25 production arbitration changed")
    if block.get("candidate_only") is not False:
        raise ValueError("V17.25 production target remains candidate-only")
    if block.get("production_runtime_generation") != "V17.25":
        raise ValueError("V17.25 production generation changed")
    if block.get("exact_source_sha256") != production.TARGET_SOURCE_SHA256:
        raise ValueError("V17.25 exact source metadata changed")
    if block.get("identity_tolerance") != "0.005":
        raise ValueError("V17.25 identity tolerance changed")
    if block.get("column_role_gate_pass") is not True:
        raise ValueError("V17.25 column-role gate failed")
    if block.get("e_equals_a_minus_l_inference") is not False:
        raise ValueError("V17.25 E=A-L inference enabled")
    if block.get("global_row_tolerance_changed") is not False:
        raise ValueError("V17.25 global row tolerance changed")
    witness = block.get("generic_group_witness") or {}
    if witness.get("witness_alias") != "归属于母公司所有者权益合计":
        raise ValueError("V17.25 witness alias changed")
    if witness.get("total_equity_alias") != "所有者权益合计":
        raise ValueError("V17.25 total equity witness changed")
    if witness.get("amounts_equal") is not True:
        raise ValueError("V17.25 witness amount equality failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p0-report", required=True)
    parser.add_argument("--candidate-report", required=True)
    parser.add_argument("--v17-24-root", required=True)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    target = load_target(Path(args.p0_report), Path(args.candidate_report))
    exact82 = evidence.load_exact82(Path(args.v17_24_root))
    combined: dict[str, dict] = dict(exact82)
    if TARGET_ANNOUNCEMENT_ID in combined:
        raise ValueError("V17.25 target unexpectedly already in exact82")
    combined[TARGET_ANNOUNCEMENT_ID] = target
    if len(combined) != 83:
        raise ValueError(f"expected exact83 population, got {len(combined)}")

    ids = selected_ids(list(combined), args.shard, args.shards)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "data-workbench-r17-stage3-v17-25-production-acceptance/1.0",
            "Accept": "application/pdf,*/*;q=0.8",
        }
    )

    results: list[dict] = []
    failures: list[dict] = []
    source_sha_matches = 0
    for index, aid in enumerate(ids, 1):
        row = combined[aid]
        try:
            raw = evidence.download(session, row["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            if digest != row["source_sha256"]:
                raise ValueError(
                    f"source SHA changed expected={row['source_sha256']} actual={digest}"
                )
            if aid == TARGET_ANNOUNCEMENT_ID and len(raw) != int(row["source_bytes"]):
                raise ValueError("V17.25 target source byte length changed")
            source_sha_matches += 1

            production_result = dict(
                production.parse_pdf_bytes(raw, row["economic_date"])
            )
            if aid == TARGET_ANNOUNCEMENT_ID:
                current = dict(accepted.parse_pdf_bytes(raw, row["economic_date"]))
                if evidence.recovered(current):
                    raise ValueError("V17.24 unexpectedly recovered V17.25 target")
                validate_new_recovery(production_result)
                results.append(
                    {
                        "announcement_id": aid,
                        "source_sha256": digest,
                        "was_v17_24_exact82": False,
                        "v17_24_recovered": False,
                        "production_balance_sheet_recovered": True,
                        "balance_sheet_block": production_result.get("balance_sheet_block"),
                        "validation_errors": list(
                            production_result.get("validation_errors") or []
                        ),
                    }
                )
            else:
                baseline = exact82[aid]
                expected_recovered = bool(
                    baseline["production_balance_sheet_recovered"]
                )
                if evidence.recovered(production_result) != expected_recovered:
                    raise ValueError("V17.25 changed V17.24 recovery state")
                if production_result.get("balance_sheet_block") != baseline.get(
                    "balance_sheet_block"
                ):
                    raise ValueError("V17.25 changed V17.24 balance-sheet block")
                if list(production_result.get("validation_errors") or []) != list(
                    baseline.get("validation_errors") or []
                ):
                    raise ValueError("V17.25 changed V17.24 validation errors")
                results.append(
                    {
                        "announcement_id": aid,
                        "source_sha256": digest,
                        "was_v17_24_exact82": True,
                        "v17_24_recovered": expected_recovered,
                        "production_balance_sheet_recovered": expected_recovered,
                        "balance_sheet_block": production_result.get("balance_sheet_block"),
                        "validation_errors": list(
                            production_result.get("validation_errors") or []
                        ),
                    }
                )
        except Exception as exc:
            failures.append(
                {
                    "announcement_id": aid,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(
            f"S3G1J_V17_25_PRODUCTION_ACCEPTANCE {index}/{len(ids)} aid={aid}",
            flush=True,
        )

    report = {
        "gate": "S3G1J_V17_25_PRODUCTION_ACCEPTANCE_SHARD",
        "shard": args.shard,
        "shards": args.shards,
        "selected_announcement_ids": ids,
        "input_count_exact83": len(ids),
        "processed_count": len(results),
        "source_sha_match_count": source_sha_matches,
        "results": results,
        "execution_failures": failures,
        "accepted_v17_24_recovery_announcement_ids": sorted(
            EXPECTED_V17_24_RECOVERIES
        ),
        "expected_v17_25_recovery_announcement_ids": sorted(
            EXPECTED_V17_25_RECOVERIES
        ),
        "accounting_tolerance": "0.005",
        "source_policy_changed": False,
        "global_row_tolerance_changed": False,
        "e_equals_a_minus_l_inference": False,
        "production_data_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_locked": True,
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
