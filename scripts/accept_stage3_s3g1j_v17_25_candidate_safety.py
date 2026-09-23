#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import time
from pathlib import Path

import fitz
import requests

import stage3_financial_pdf_parser_v15 as accepted
import stage3_financial_pdf_parser_v16 as candidate
import stage3_financial_statement_blocks_v17_25 as candidate_blocks

CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
EXPECTED_WITNESS_IDS = {
    "1200907104",
    "1201708762",
    "1202195310",
    "1202774611",
    "1203358200",
    "1204077386",
    "1205543437",
    "1207035181",
}
EXPECTED_NEGATIVE_IDS = {
    "1202799494",
    "1209806910",
    "1219834247",
}
EXPECTED_MISSING_EQUITY_COUNT = 11
EXPECTED_EXACT82_RECOVERED = {
    "1212731093",
    "1219311356",
    "1221568845",
    "1225153907",
}


def download(session: requests.Session, url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(1, 7):
        try:
            response = session.get(url, timeout=(30, 180))
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise ValueError(f"download is not PDF {url}")
            return response.content
        except Exception as exc:
            last = exc
            if attempt < 6:
                time.sleep(attempt * 5)
    assert last is not None
    raise last


def recovered(parsed: dict) -> bool:
    observations = parsed.get("observations") or {}
    return (
        all(
            (observations.get(concept) or {}).get("status") == "FOUND"
            for concept in CONCEPTS
        )
        and isinstance(parsed.get("balance_sheet_block"), dict)
        and not list(parsed.get("validation_errors") or [])
    )


def load_exact82(root: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    paths = sorted(glob.glob(str(root / "candidate" / "shard*.json")))
    if len(paths) != 4:
        raise ValueError(f"expected four V17.24 shard files, got {paths}")
    for path in paths:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        if report.get("pass") is not True or report.get("errors"):
            raise ValueError(f"accepted V17.24 shard not pass {path}")
        for row in report.get("results") or []:
            aid = str(row["announcement_id"])
            if aid in rows:
                raise ValueError(f"duplicate exact82 row {aid}")
            rows[aid] = row
    if len(rows) != 82:
        raise ValueError(f"expected exact82 rows, got {len(rows)}")
    baseline_recovered = {
        aid for aid, row in rows.items() if row["production_balance_sheet_recovered"]
    }
    if baseline_recovered != EXPECTED_EXACT82_RECOVERED:
        raise ValueError(
            f"accepted exact82 recovery set changed {sorted(baseline_recovered)}"
        )
    return rows


def parse_pair(raw: bytes, economic_date: str) -> tuple[dict, dict]:
    current = dict(accepted.parse_pdf_bytes(raw, economic_date))
    proposed = dict(candidate.parse_pdf_bytes(raw, economic_date))
    return current, proposed


def require_candidate_recovery_safety(aid: str, parsed: dict) -> None:
    if not recovered(parsed):
        raise ValueError(f"candidate recovery did not validate {aid}")
    block = parsed["balance_sheet_block"]
    if block.get("identity_tolerance") != "0.005":
        raise ValueError(f"identity tolerance changed {aid}")
    if block.get("global_row_tolerance_changed") not in (None, False):
        raise ValueError(f"global row tolerance changed {aid}")
    if block.get("e_equals_a_minus_l_inference") not in (None, False):
        raise ValueError(f"E=A-L inference enabled {aid}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p0-report", required=True)
    parser.add_argument("--v17-24-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    p0 = json.loads(Path(args.p0_report).read_text(encoding="utf-8"))
    if p0.get("pass") is not True or p0.get("errors"):
        raise ValueError("P0 source diagnostic is not accepted")
    p0_rows = {str(row["announcement_id"]): row for row in p0.get("results") or []}
    if len(p0_rows) != 22:
        raise ValueError(f"expected 22 P0 rows, got {len(p0_rows)}")
    if not EXPECTED_WITNESS_IDS.issubset(p0_rows):
        raise ValueError("expected witness IDs absent from P0 report")
    if not EXPECTED_NEGATIVE_IDS.issubset(p0_rows):
        raise ValueError("expected negative IDs absent from P0 report")

    exact82 = load_exact82(Path(args.v17_24_root))
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "data-workbench-r17-stage3-v17-25-candidate-safety/1.0",
            "Accept": "application/pdf,*/*;q=0.8",
        }
    )

    p0_results: list[dict] = []
    exact82_results: list[dict] = []
    failures: list[dict] = []
    source_sha_matches = 0

    for index, aid in enumerate(sorted(p0_rows), 1):
        row = p0_rows[aid]
        try:
            raw = download(session, row["canonical_source_url"])
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
            should_witness = aid in EXPECTED_WITNESS_IDS
            promoted_count = int(witness["promoted_generic_group_count"])
            if should_witness and promoted_count != 1:
                raise ValueError(
                    f"expected exactly one generic GROUP witness, got {promoted_count}"
                )
            if not should_witness and promoted_count != 0:
                raise ValueError("unexpected generic GROUP witness")

            current, proposed = parse_pair(raw, row["economic_date"])
            if recovered(current):
                raise ValueError("accepted V17.24 unexpectedly recovers P0 residual")
            proposed_recovered = recovered(proposed)
            if proposed_recovered and not should_witness:
                raise ValueError("candidate recovered outside exact witness population")
            if proposed_recovered:
                require_candidate_recovery_safety(aid, proposed)
            elif not list(proposed.get("validation_errors") or []):
                raise ValueError("fail-closed candidate lost validation errors")
            p0_results.append(
                {
                    "announcement_id": aid,
                    "source_code": row["source_code"],
                    "report_family": row["report_family"],
                    "economic_date": row["economic_date"],
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
        print(f"S3G1J_V17_25_P0_SAFETY {index}/22 aid={aid}", flush=True)

    for index, aid in enumerate(sorted(exact82), 1):
        baseline = exact82[aid]
        try:
            raw = download(session, baseline["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            if digest != baseline["source_sha256"]:
                raise ValueError(
                    f"exact82 source SHA changed expected={baseline['source_sha256']} actual={digest}"
                )
            source_sha_matches += 1
            current, proposed = parse_pair(raw, baseline["economic_date"])
            expected_recovered = bool(baseline["production_balance_sheet_recovered"])
            if recovered(current) != expected_recovered:
                raise ValueError("current V17.24 exact82 recovery state changed")
            if current.get("balance_sheet_block") != baseline.get("balance_sheet_block"):
                raise ValueError("current V17.24 exact82 block changed")
            if list(current.get("validation_errors") or []) != list(
                baseline.get("validation_errors") or []
            ):
                raise ValueError("current V17.24 exact82 validation errors changed")
            if recovered(proposed) != expected_recovered:
                raise ValueError("candidate changed exact82 recovery state")
            if proposed.get("balance_sheet_block") != current.get("balance_sheet_block"):
                raise ValueError("candidate changed exact82 balance-sheet block")
            if list(proposed.get("validation_errors") or []) != list(
                current.get("validation_errors") or []
            ):
                raise ValueError("candidate changed exact82 validation errors")
            exact82_results.append(
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
        print(f"S3G1J_V17_25_EXACT82_SAFETY {index}/82 aid={aid}", flush=True)

    promoted_ids = sorted(
        row["announcement_id"]
        for row in p0_results
        if row["group_witness_diagnostic"]["promoted_generic_group_count"] == 1
    )
    candidate_recovered_ids = sorted(
        row["announcement_id"]
        for row in p0_results
        if row["candidate_v17_25_recovered"]
    )
    missing_equity_ids = {
        aid
        for aid, row in p0_rows.items()
        if row["diagnostic_signature"] == "MISSING_CANDIDATES_TOTAL_EQUITY"
    }
    if len(missing_equity_ids) != EXPECTED_MISSING_EQUITY_COUNT:
        failures.append(
            {
                "scope": "ACCOUNTING",
                "announcement_id": "",
                "error": (
                    "ValueError: expected 11 missing-equity rows, got "
                    f"{len(missing_equity_ids)}"
                ),
            }
        )

    report = {
        "gate": "S3G1J_V17_25_GENERIC_GROUP_WITNESS_CANDIDATE_SAFETY",
        "source_p0_diagnostic_run": 30687837626,
        "source_v17_24_authority_run": 30685830808,
        "p0_input_count": 22,
        "exact82_input_count": 82,
        "processed_p0_count": len(p0_results),
        "processed_exact82_count": len(exact82_results),
        "source_sha_match_count": source_sha_matches,
        "expected_group_witness_announcement_ids": sorted(EXPECTED_WITNESS_IDS),
        "promoted_group_witness_announcement_ids": promoted_ids,
        "candidate_recovered_announcement_ids": candidate_recovered_ids,
        "candidate_recovered_count": len(candidate_recovered_ids),
        "candidate_remaining_p0_fail_closed_count": 22 - len(candidate_recovered_ids),
        "required_negative_announcement_ids": sorted(EXPECTED_NEGATIVE_IDS),
        "missing_equity_population_count": len(missing_equity_ids),
        "exact82_recovery_announcement_ids": sorted(EXPECTED_EXACT82_RECOVERED),
        "p0_results": p0_results,
        "exact82_results": exact82_results,
        "execution_failures": failures,
        "candidate_only": True,
        "parser_changed": True,
        "production_runtime_changed": False,
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "source_policy_changed": False,
        "fuzzy_alias_matching_enabled": False,
        "e_equals_a_minus_l_inference": False,
        "production_data_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_locked": True,
        "pass": (
            not failures
            and len(p0_results) == 22
            and len(exact82_results) == 82
            and source_sha_matches == 104
            and set(promoted_ids) == EXPECTED_WITNESS_IDS
            and set(candidate_recovered_ids).issubset(EXPECTED_WITNESS_IDS)
            and not (set(candidate_recovered_ids) & missing_equity_ids)
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
            {key: value for key, value in report.items() if key not in ("p0_results", "exact82_results")},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
