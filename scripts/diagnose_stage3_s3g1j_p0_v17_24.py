#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
import requests

import stage3_financial_pdf_parser_v13 as v17_21
import stage3_financial_pdf_parser_v15 as v17_24
import stage3_financial_spatial_alias_v17_24 as spatial

CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
P0_CLASS = "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3"
P0_PRIORITY = "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_targets(
    p0_path: Path,
    expected_gzip_sha256: str,
    excluded_ids: set[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    actual = sha256_file(p0_path)
    if actual != expected_gzip_sha256:
        raise ValueError(
            f"P0 ledger gzip SHA mismatch expected={expected_gzip_sha256} actual={actual}"
        )
    source_rows = read_gzip_csv(p0_path)
    if len(source_rows) != 23:
        raise ValueError(f"expected 23 source-basis P0 rows, got {len(source_rows)}")
    ids = [str(row["announcement_id"]) for row in source_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate P0 announcement IDs")
    for row in source_rows:
        if row.get("residual_class") != P0_CLASS:
            raise ValueError(
                f"unexpected P0 residual class {row.get('announcement_id')} "
                f"{row.get('residual_class')}"
            )
        if row.get("priority_class") != P0_PRIORITY:
            raise ValueError(
                f"unexpected P0 priority {row.get('announcement_id')} "
                f"{row.get('priority_class')}"
            )
    if not excluded_ids.issubset(set(ids)):
        raise ValueError(
            f"excluded IDs absent from P0 source basis {sorted(excluded_ids - set(ids))}"
        )
    targets = [row for row in source_rows if row["announcement_id"] not in excluded_ids]
    if len(targets) != 22:
        raise ValueError(f"expected 22 current P0 targets, got {len(targets)}")
    targets.sort(key=lambda row: (row["economic_date"], row["announcement_id"]))
    return source_rows, targets


def load_full_documents(
    path: Path,
    expected_gzip_sha256: str,
    target_ids: set[str],
) -> dict[str, dict[str, str]]:
    actual = sha256_file(path)
    if actual != expected_gzip_sha256:
        raise ValueError(
            "full document ledger gzip SHA mismatch "
            f"expected={expected_gzip_sha256} actual={actual}"
        )
    matched: dict[str, dict[str, str]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            aid = str(row.get("announcement_id") or "")
            if aid not in target_ids:
                continue
            if aid in matched:
                raise ValueError(f"duplicate full document row {aid}")
            matched[aid] = row
    if set(matched) != target_ids:
        raise ValueError(
            f"missing target documents {sorted(target_ids - set(matched))}"
        )
    return matched


def source_evidence(document: dict[str, str]) -> dict[str, Any]:
    candidates = json.loads(document.get("candidate_evidence_json") or "[]")
    if len(candidates) != 1:
        raise ValueError(
            f"expected one canonical candidate {document.get('announcement_id')} "
            f"got={len(candidates)}"
        )
    candidate = dict(candidates[0])
    aid = str(document.get("announcement_id") or "")
    if str(candidate.get("id") or "") != aid:
        raise ValueError(f"candidate identity mismatch {aid} {candidate.get('id')}")
    url = str(candidate.get("url") or "")
    expected_sha = str(candidate.get("sha256") or "")
    expected_bytes = int(candidate.get("bytes") or 0)
    if not url.startswith("https://static.cninfo.com.cn/"):
        raise ValueError(f"unexpected canonical URL {aid} {url}")
    if len(expected_sha) != 64 or expected_bytes <= 0:
        raise ValueError(f"incomplete source identity {aid}")
    if str(document.get("canonical_source_url") or "") != url:
        raise ValueError(f"canonical source URL mismatch {aid}")
    return {
        "url": url,
        "sha256": expected_sha,
        "bytes": expected_bytes,
        "candidate": candidate,
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
        except Exception as exc:  # diagnostic evidence must preserve source failures
            last = exc
            if attempt < 6:
                time.sleep(attempt * 5)
    assert last is not None
    raise last


def is_recovered(parsed: dict[str, Any]) -> bool:
    observations = parsed.get("observations") or {}
    return (
        all(
            (observations.get(concept) or {}).get("status") == "FOUND"
            for concept in CONCEPTS
        )
        and isinstance(parsed.get("balance_sheet_block"), dict)
        and not list(parsed.get("validation_errors") or [])
    )


def slim_parsed(parsed: dict[str, Any]) -> dict[str, Any]:
    observations = parsed.get("observations") or {}
    keep = {
        key: value
        for key, value in observations.items()
        if key in CONCEPTS or key == "EQUITY_ATTRIBUTABLE_TO_PARENT"
    }
    return {
        "parser_version": parsed.get("parser_version"),
        "recovered": is_recovered(parsed),
        "validation_errors": list(parsed.get("validation_errors") or []),
        "balance_sheet_block": parsed.get("balance_sheet_block"),
        "observations": keep,
    }


def diagnostic_signature(
    current_recovered: bool,
    diagnostic: dict[str, Any],
) -> str:
    if current_recovered:
        return "CURRENT_V17_24_RECOVERED"
    column_gate = diagnostic.get("column_role_gate") or {}
    if (
        diagnostic.get("identity_recovered_before_column_gate") is True
        and column_gate.get("pass") is not True
    ):
        return "IDENTITY_FOUND_BUT_COLUMN_ROLE_GATE_FAILED"
    counts = diagnostic.get("candidate_counts") or {}
    missing = [concept for concept in CONCEPTS if int(counts.get(concept) or 0) == 0]
    if missing:
        return "MISSING_CANDIDATES_" + "_".join(missing)
    if all(int(counts.get(concept) or 0) > 0 for concept in CONCEPTS):
        return "ALL_CONCEPT_CANDIDATES_PRESENT_NO_VALID_IDENTITY"
    return "NO_VALIDATED_BALANCE_SHEET_BLOCK_UNCLASSIFIED"


def signature_key(row: dict[str, Any]) -> str:
    diagnostic = row.get("spatial_diagnostic") or {}
    counts = diagnostic.get("candidate_counts") or {}
    column = diagnostic.get("column_role_gate") or {}
    payload = {
        "signature": row["diagnostic_signature"],
        "candidate_counts": {key: int(counts.get(key) or 0) for key in CONCEPTS},
        "corrupted_equity_candidate_count": int(
            diagnostic.get("corrupted_equity_candidate_count") or 0
        ),
        "column_gate_pass": bool(column.get("pass")),
        "column_gate_reason": str(column.get("reason") or ""),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p0-ledger", required=True)
    parser.add_argument("--p0-gzip-sha256", required=True)
    parser.add_argument("--full-documents", required=True)
    parser.add_argument("--full-documents-gzip-sha256", required=True)
    parser.add_argument("--exclude-announcement-id", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    excluded_ids = {str(value) for value in args.exclude_announcement_id}
    if excluded_ids != {"1221568845"}:
        raise ValueError(
            f"diagnostic exclusion must equal accepted V17.24 recovery, got {sorted(excluded_ids)}"
        )
    source_rows, targets = load_targets(
        Path(args.p0_ledger), args.p0_gzip_sha256, excluded_ids
    )
    target_ids = {row["announcement_id"] for row in targets}
    documents = load_full_documents(
        Path(args.full_documents),
        args.full_documents_gzip_sha256,
        target_ids,
    )

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "data-workbench-r17-stage3-p0-diagnostic/1.0",
            "Accept": "application/pdf,*/*;q=0.8",
        }
    )
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    source_sha_matches = 0

    for index, target in enumerate(targets, 1):
        aid = target["announcement_id"]
        try:
            evidence = source_evidence(documents[aid])
            raw = download(session, evidence["url"])
            actual_sha = hashlib.sha256(raw).hexdigest()
            if actual_sha != evidence["sha256"]:
                raise ValueError(
                    f"source SHA changed expected={evidence['sha256']} actual={actual_sha}"
                )
            if len(raw) != evidence["bytes"]:
                raise ValueError(
                    f"source byte length changed expected={evidence['bytes']} actual={len(raw)}"
                )
            source_sha_matches += 1

            prior = dict(v17_21.parse_pdf_bytes(raw, target["economic_date"]))
            current = dict(v17_24.parse_pdf_bytes(raw, target["economic_date"]))
            prior_recovered = is_recovered(prior)
            current_recovered = is_recovered(current)
            if prior_recovered:
                raise ValueError("source-basis V17.21 residual unexpectedly recovered")
            with fitz.open(stream=raw, filetype="pdf") as doc:
                diagnostic = spatial.diagnose_spatial_balance_sheet_v17_24(
                    doc, target["economic_date"]
                )
            row = {
                "announcement_id": aid,
                "source_code": target["source_code"],
                "issuer_org_id": target["issuer_org_id"],
                "report_family": target["report_family"],
                "economic_date": target["economic_date"],
                "canonical_title": target["canonical_title"],
                "canonical_source_url": evidence["url"],
                "source_sha256": actual_sha,
                "source_bytes": len(raw),
                "source_basis_candidate": evidence["candidate"],
                "v17_21": slim_parsed(prior),
                "v17_24": slim_parsed(current),
                "spatial_diagnostic": diagnostic,
            }
            row["diagnostic_signature"] = diagnostic_signature(
                current_recovered, diagnostic
            )
            results.append(row)
        except Exception as exc:
            failures.append(
                {
                    "announcement_id": aid,
                    "source_code": target.get("source_code", ""),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(f"S3G1J_P0_V17_24_DIAGNOSTIC {index}/{len(targets)} aid={aid}", flush=True)

    results.sort(key=lambda row: (row["economic_date"], row["announcement_id"]))
    current_recovered_ids = sorted(
        row["announcement_id"] for row in results if row["v17_24"]["recovered"]
    )
    fail_closed_ids = sorted(
        row["announcement_id"] for row in results if not row["v17_24"]["recovered"]
    )
    signatures = Counter(row["diagnostic_signature"] for row in results)
    detailed_signatures = Counter(signature_key(row) for row in results)
    candidate_patterns = Counter(
        json.dumps(
            {
                key: int(
                    ((row.get("spatial_diagnostic") or {}).get("candidate_counts") or {}).get(key)
                    or 0
                )
                for key in CONCEPTS
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        for row in results
    )
    funnel_totals: dict[str, Counter] = {
        name: Counter()
        for name in (
            "base_funnel",
            "bridge_funnel",
            "strict_equity_funnel",
            "reverse_asset_funnel",
            "corrupted_equity_funnel",
        )
    }
    for row in results:
        diagnostic = row.get("spatial_diagnostic") or {}
        for name, counter in funnel_totals.items():
            counter.update(
                {
                    str(key): int(value)
                    for key, value in (diagnostic.get(name) or {}).items()
                }
            )

    report = {
        "gate": "S3G1J_P0_CURRENT_V17_24_DIAGNOSTIC_V1",
        "source_classifier_run": 30687393120,
        "source_classifier_artifact": "stage3-s3g1j-full-basis-residual-classification-v1",
        "source_classifier_artifact_digest": "sha256:3451a94bb70758bbb93d3be4600ad7e0d8d65de618928b1c635f8a29686f7052",
        "source_full_basis_run": 30649251360,
        "source_full_basis_artifact": "stage3-s3g1j-v17-21-full-final",
        "source_full_basis_artifact_digest": "sha256:7faff72949a6e0a98f49088bce99bc2df37c7cbcb0259b39d1b2655fc02f6086",
        "current_runtime_authority_run": 30685830808,
        "current_runtime_generation": "V17.24",
        "source_basis_p0_count": len(source_rows),
        "excluded_accepted_recovery_announcement_ids": sorted(excluded_ids),
        "target_count": len(targets),
        "processed_count": len(results),
        "source_sha_match_count": source_sha_matches,
        "v17_21_recovered_count": sum(row["v17_21"]["recovered"] for row in results),
        "v17_24_recovered_count": len(current_recovered_ids),
        "v17_24_recovered_announcement_ids": current_recovered_ids,
        "v17_24_fail_closed_count": len(fail_closed_ids),
        "v17_24_fail_closed_announcement_ids": fail_closed_ids,
        "signature_counts": dict(sorted(signatures.items())),
        "detailed_signature_counts": dict(sorted(detailed_signatures.items())),
        "candidate_count_patterns": dict(sorted(candidate_patterns.items())),
        "funnel_totals": {
            name: dict(sorted(counter.items()))
            for name, counter in funnel_totals.items()
        },
        "results": results,
        "execution_failures": failures,
        "accounting_tolerance_changed": False,
        "source_policy_changed": False,
        "parser_changed": False,
        "production_data_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_locked": True,
        "pass": (
            not failures
            and len(results) == 22
            and source_sha_matches == 22
            and sum(row["v17_21"]["recovered"] for row in results) == 0
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
            default=str,
        )
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
