#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import requests

from extract_stage3_financial_pdf_values_v7 import parse_pdf_bytes


def readgz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V12-recovery-48",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=90,
    )
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise ValueError(f"not PDF bytes={len(response.content)} content_type={response.headers.get('Content-Type')}")
    return response.content


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--versions", required=True)
    ap.add_argument("--samples", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ledger = readgz(Path(args.ledger))
    versions = readgz(Path(args.versions))
    sample_spec = json.loads(Path(args.samples).read_text(encoding="utf-8"))
    samples = sample_spec.get("samples") or []
    if len(samples) != int(sample_spec.get("sample_count") or -1):
        raise ValueError("sample_count contract mismatch")

    ledger_by_id = {r["announcement_id"]: r for r in ledger}
    versions_by_moment = {
        (r["org_id"], r["report_family"], r["economic_date"], r["source_published_at"]): r
        for r in versions
    }
    session = requests.Session()
    rows = []
    diagnostic_errors: list[str] = []
    outcome_counts = Counter()

    for sample in samples:
        row = {
            "source_code": sample["source_code"],
            "report_family": sample["report_family"],
            "economic_date": sample["economic_date"],
            "v10_original_announcement_id": sample["announcement_id"],
            "v10_original_url": sample["url"],
            "v10_original_sha256": sample["sha256"],
            "era": sample["era"],
            "shard": sample["shard"],
        }
        try:
            original = ledger_by_id.get(sample["announcement_id"])
            if not original:
                raise AssertionError("V10 sample announcement missing from frozen S3G1E ledger")
            moment = (
                original["org_id"],
                original["report_family"],
                original["economic_date"],
                original["source_published_at"],
            )
            row["source_published_at"] = original["source_published_at"]
            selected = versions_by_moment.get(moment)
            if not selected:
                outcome = "NO_FULL_AUTHORITY_SAME_MOMENT"
                row.update(
                    {
                        "outcome": outcome,
                        "recovered": False,
                        "selected_announcement_id": None,
                        "selected_title": None,
                        "selected_url": None,
                    }
                )
                outcome_counts[outcome] += 1
                rows.append(row)
                continue

            selected_id = selected["canonical_announcement_id"]
            source_changed = selected_id != sample["announcement_id"]
            row.update(
                {
                    "selected_announcement_id": selected_id,
                    "selected_title": selected["canonical_title"],
                    "selected_url": selected["canonical_source_url"],
                    "selection_class": selected["selection_class"],
                    "source_changed": source_changed,
                }
            )
            raw = download(session, selected["canonical_source_url"])
            parsed = parse_pdf_bytes(raw)
            validation_errors = parsed.get("validation_errors") or []
            balance = parsed.get("balance_sheet_block")
            recovered = bool(balance) and not validation_errors
            if recovered and source_changed:
                outcome = "SOURCE_SWITCH_RECOVERED"
            elif recovered:
                outcome = "PARSER_ONLY_RECOVERED"
            elif source_changed:
                outcome = "SOURCE_SWITCH_STILL_FAILS"
            else:
                outcome = "UNCHANGED_SOURCE_STILL_FAILS"
            outcome_counts[outcome] += 1
            row.update(
                {
                    "selected_sha256": hashlib.sha256(raw).hexdigest(),
                    "selected_bytes": len(raw),
                    "page_count": parsed.get("page_count"),
                    "declared_a_share_codes": parsed.get("declared_a_share_codes") or [],
                    "tier1_found": parsed.get("tier1_found"),
                    "tier2_found": parsed.get("tier2_found"),
                    "validation_errors": validation_errors,
                    "balance_sheet_block": balance,
                    "recovered": recovered,
                    "outcome": outcome,
                }
            )
        except Exception as exc:
            outcome = "DIAGNOSTIC_ERROR"
            outcome_counts[outcome] += 1
            row.update(
                {
                    "recovered": False,
                    "outcome": outcome,
                    "diagnostic_error": f"{type(exc).__name__}: {exc}",
                }
            )
            diagnostic_errors.append(
                f"{sample.get('announcement_id')}: {type(exc).__name__}: {exc}"
            )
        rows.append(row)

    recovered_count = sum(bool(r.get("recovered")) for r in rows)
    report = {
        "gate": "S3G1J_V12_1_COMBINED_SOURCE_PARSER_RECOVERY_48",
        "diagnostic_pass": not diagnostic_errors,
        "sample_count": len(rows),
        "recovered_count": recovered_count,
        "remaining_not_recovered_count": len(rows) - recovered_count,
        "recovery_rate": recovered_count / len(rows) if rows else None,
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "policy": {
            "same_v10_1_failure_sample": True,
            "same_frozen_s3g1e_ledger": True,
            "v12_1_full_statement_selection": True,
            "v11_1_parser": True,
            "original_pdf_bytes_required_for_selected_sources": True,
            "a_equals_l_plus_e_gate_unchanged": "0.005",
            "no_full_authority_same_moment_is_not_silently_replaced_by_later_filing": True,
            "no_current_f10_backfill": True,
        },
        "rows": rows,
        "diagnostic_errors": diagnostic_errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not diagnostic_errors else 2


if __name__ == "__main__":
    sys.exit(main())
