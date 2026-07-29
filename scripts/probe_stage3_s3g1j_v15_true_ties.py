#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter
from pathlib import Path

import requests

import extract_stage3_financial_pdf_values_v8 as ext


def read_versions(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _error_kind(value: object) -> str:
    text = str(value or "")
    if not text:
        return "NONE"
    if "404 Client Error" in text or "410 Client Error" in text:
        return "PERMANENT_404_410"
    if any(token in text for token in (
        "NO_VALIDATED_BALANCE_SHEET_BLOCK",
        "BALANCE_SHEET_IDENTITY_MISMATCH",
        "NO_BALANCE",
    )):
        return "PARSER_BALANCE_VALIDATION"
    if "PDF_DECLARES_OTHER_A_SHARE_ISSUER" in text:
        return "PDF_ISSUER_MISMATCH"
    if any(token in text.lower() for token in ("timeout", "connection", "ssl", "http")):
        return "DOWNLOAD_OR_NETWORK"
    return "OTHER_PARSER_OR_SOURCE_ERROR"


def _reason_bucket(value: object) -> str:
    text = str(value or "")
    for token in (
        "canonical PDF is not independently usable",
        "canonical candidate failed",
        "failed tied candidate has a different title",
        "failed tied candidate is not an older announcement id",
        "failed tied candidate is not an official 404/410",
        "surviving candidates do not resolve to canonical",
    ):
        if token in text:
            return token
    return text[:200] if text else "NONE"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shards", default="0,1,7,9")
    args = ap.parse_args()

    target_shards = {int(x.strip()) for x in args.shards.split(",") if x.strip()}
    rows = [
        r for r in read_versions(Path(args.versions))
        if ext.v9.base.stable_shard(r["canonical_announcement_id"], 64) in target_shards
        and int(r.get("same_day_tied_top_count") or "1") > 1
    ]

    session = requests.Session()
    resolution_counts = Counter()
    failure_reason_counts = Counter()
    candidate_error_kind_counts = Counter()
    canonical_error_counts = Counter()
    by_shard = Counter()
    details = []
    diagnostic_errors = []

    for row in rows:
        shard = ext.v9.base.stable_shard(row["canonical_announcement_id"], 64)
        by_shard[shard] += 1
        all_candidates = ext.v9.base.candidate_list(row)
        candidates, excluded = ext.v9.base.filter_candidates_by_issuer(
            all_candidates, row["source_code"], row["canonical_announcement_id"]
        )
        parsed_candidates = []
        for candidate in candidates:
            ev = {"id": candidate["id"], "title": candidate["title"], "url": candidate["url"]}
            try:
                raw = ext.v9.base.get_pdf(session, candidate["url"])
                parsed = ext.parse_pdf_bytes(raw)
                ev.update({
                    "sha256": ext.v9.base.sha(raw),
                    "bytes": len(raw),
                    "parsed": parsed,
                })
                if parsed.get("validation_errors"):
                    ev["error"] = "; ".join(map(str, parsed["validation_errors"]))
            except Exception as exc:
                ev["error"] = repr(exc)
            parsed_candidates.append(ev)

        try:
            chosen, resolution, resolution_error = ext.v9.base.resolve_candidates(
                parsed_candidates, row["canonical_announcement_id"]
            )
        except Exception as exc:
            diagnostic_errors.append(f"{row['canonical_announcement_id']}: resolver exception {type(exc).__name__}: {exc}")
            chosen, resolution, resolution_error = None, "DIAGNOSTIC_RESOLVER_EXCEPTION", repr(exc)

        resolution_counts[resolution] += 1
        if chosen is None:
            failure_reason_counts[_reason_bucket(resolution_error)] += 1

        canonical = next(
            (x for x in parsed_candidates if str(x.get("id")) == str(row["canonical_announcement_id"])),
            None,
        )
        canonical_error = bool(canonical and canonical.get("error"))
        canonical_error_counts["CANONICAL_ERROR" if canonical_error else "CANONICAL_OK"] += 1

        candidate_slim = []
        normalized_titles = set()
        for candidate in parsed_candidates:
            error_kind = _error_kind(candidate.get("error"))
            candidate_error_kind_counts[error_kind] += 1
            normalized_titles.add(ext.v9.base._norm_title(str(candidate.get("title") or "")))
            parsed = candidate.get("parsed") or {}
            candidate_slim.append({
                "id": candidate.get("id"),
                "title": candidate.get("title"),
                "sha256": candidate.get("sha256"),
                "bytes": candidate.get("bytes"),
                "error": candidate.get("error"),
                "error_kind": error_kind,
                "page_count": parsed.get("page_count"),
                "tier1_found": parsed.get("tier1_found"),
                "tier2_found": parsed.get("tier2_found"),
                "balance_sheet_block": parsed.get("balance_sheet_block"),
            })
        for candidate in excluded:
            candidate_slim.append({
                "id": candidate.get("id"),
                "title": candidate.get("title"),
                "excluded_reason": candidate.get("excluded_reason"),
                "error_kind": "TITLE_ISSUER_EXCLUDED",
            })
            candidate_error_kind_counts["TITLE_ISSUER_EXCLUDED"] += 1

        details.append({
            "shard": shard,
            "source_code": row["source_code"],
            "report_family": row["report_family"],
            "economic_date": row["economic_date"],
            "source_published_at": row["source_published_at"],
            "canonical_announcement_id": row["canonical_announcement_id"],
            "canonical_title": row["canonical_title"],
            "tied_top_count": len(all_candidates),
            "all_titles_identical_after_normalization": len(normalized_titles) <= 1,
            "canonical_error": canonical_error,
            "current_resolution": resolution,
            "current_resolution_error": resolution_error,
            "current_chosen_id": chosen.get("id") if chosen else None,
            "candidates": candidate_slim,
        })

    failed = sum(1 for x in details if x["current_chosen_id"] is None)
    report = {
        "gate": "S3G1J_V15_TRUE_SAME_MOMENT_TIE_DIAGNOSTIC",
        "diagnostic_pass": not diagnostic_errors,
        "target_shards": sorted(target_shards),
        "true_tied_moments": len(details),
        "true_tied_candidates": sum(x["tied_top_count"] for x in details),
        "current_resolved_moments": len(details) - failed,
        "current_failed_moments": failed,
        "resolution_counts": dict(sorted(resolution_counts.items())),
        "failure_reason_counts": dict(sorted(failure_reason_counts.items())),
        "candidate_error_kind_counts": dict(sorted(candidate_error_kind_counts.items())),
        "canonical_error_counts": dict(sorted(canonical_error_counts.items())),
        "tied_moments_by_shard": {str(k): by_shard[k] for k in sorted(by_shard)},
        "policy": {
            "diagnostic_only": True,
            "uses_v13_parser_and_current_fail_closed_tie_policy": True,
            "same_v12_1_frozen_version_ledger": True,
            "no_resolution_policy_relaxation": True,
        },
        "rows": details,
        "diagnostic_errors": diagnostic_errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if not diagnostic_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
