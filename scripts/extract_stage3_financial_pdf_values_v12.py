#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import time
from pathlib import Path

import requests

import extract_stage3_financial_pdf_values_v10 as v15
from stage3_financial_pdf_parser_v12 import parse_pdf_bytes as v17_17_parse_pdf_bytes

# Importing V15.1 installs the accepted issuer and tied-candidate resolver chain
# on this shared base module. This driver changes only PDF parsing and passes
# the frozen economic_date explicitly for every candidate.
base = v15.v14.v9.base
METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V12_V17_17_STRICT_TOTAL_EQUITY_PAIRED_HEADER_FINAL_FALLBACK"
METHODOLOGY_VERSION = "V3.3.3-V17.17"


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    parsed = dict(v17_17_parse_pdf_bytes(raw, economic_date))
    parsed["declared_a_share_codes"] = v15.v14.v9.declared_a_share_codes(raw)
    return parsed


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_deterministic_csv_gz(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)


def slim_evidence(evidence: list[dict]) -> list[dict]:
    slim: list[dict] = []
    for item in evidence:
        row = {
            key: item.get(key)
            for key in ("id", "title", "url", "sha256", "bytes", "error", "excluded_reason")
            if item.get(key) not in (None, "")
        }
        parsed = item.get("parsed") or {}
        if parsed:
            row.update(
                {
                    "tier1_found": parsed.get("tier1_found"),
                    "tier2_found": parsed.get("tier2_found"),
                    "page_count": parsed.get("page_count"),
                    "parser_version": parsed.get("parser_version"),
                    "validation_errors": list(parsed.get("validation_errors") or []),
                }
            )
        slim.append(row)
    return slim


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.shards <= 0 or args.shard < 0 or args.shard >= args.shards:
        raise ValueError(f"invalid shard geometry shard={args.shard} shards={args.shards}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = [
        row
        for row in base.read_versions(Path(args.versions))
        if base.stable_shard(row["canonical_announcement_id"], args.shards) == args.shard
    ]
    rows.sort(key=lambda row: row["canonical_announcement_id"])

    session = requests.Session()
    numeric: list[dict] = []
    docs: list[dict] = []
    errors: list[str] = []
    download_bytes = 0
    tie_counts: dict[str, int] = {}

    for index, row in enumerate(rows, 1):
        all_candidates = base.candidate_list(row)
        candidates, excluded = base.filter_candidates_by_issuer(
            all_candidates, row["source_code"], row["canonical_announcement_id"]
        )
        parsed_candidates: list[dict] = []
        for candidate in candidates:
            evidence = {
                "id": candidate["id"],
                "title": candidate["title"],
                "url": candidate["url"],
            }
            try:
                raw = base.get_pdf(session, candidate["url"])
                download_bytes += len(raw)
                parsed = parse_pdf_bytes(raw, row["economic_date"])
                evidence.update(
                    {
                        "sha256": base.sha(raw),
                        "bytes": len(raw),
                        "parsed": parsed,
                    }
                )
                if parsed.get("validation_errors"):
                    evidence["error"] = "; ".join(map(str, parsed["validation_errors"]))
            except Exception as exc:
                evidence["error"] = repr(exc)
            parsed_candidates.append(evidence)

        chosen, resolution, resolution_error = base.resolve_candidates(
            parsed_candidates, row["canonical_announcement_id"]
        )
        if excluded:
            resolution += "_AFTER_ISSUER_FILTER"
        tie_counts[resolution] = tie_counts.get(resolution, 0) + 1

        common = {
            "exchange": row["exchange"],
            "source_code": row["source_code"],
            "effective_code": row["effective_code"],
            "issuer_org_id": row["org_id"],
            "report_family": row["report_family"],
            "economic_date": row["economic_date"],
            "announcement_id": row["canonical_announcement_id"],
            "revision_sequence": row["revision_sequence"],
            "source_published_at": row["source_published_at"],
            "effective_session": row["effective_session"],
            "available_at": row["available_at"],
        }
        candidate_evidence = parsed_candidates + excluded

        if chosen is None:
            error = resolution_error or resolution
            errors.append(f"{row['canonical_announcement_id']} {resolution}: {error}")
            docs.append(
                {
                    **common,
                    "canonical_title": row["canonical_title"],
                    "canonical_source_url": row["canonical_source_url"],
                    "selected_source_url": "",
                    "selected_source_sha256": "",
                    "selected_source_bytes": "",
                    "tie_candidate_count": str(len(all_candidates)),
                    "tie_resolution": resolution,
                    "candidate_evidence_json": json.dumps(
                        slim_evidence(candidate_evidence), ensure_ascii=False, default=str
                    ),
                    "tier1_found": "0",
                    "tier2_found": "0",
                    "numeric_observations": "0",
                    "document_status": "ERROR",
                    "document_error": error,
                }
            )
            continue

        parsed = chosen["parsed"]
        found = 0
        for concept, observation in parsed["observations"].items():
            if observation.get("status") != "FOUND":
                continue
            found += 1
            numeric.append(
                {
                    **common,
                    "concept": concept,
                    "raw_value": observation.get("raw_value", ""),
                    "normalized_cny_value": observation.get("normalized_cny_value", ""),
                    "unit": observation.get("unit", ""),
                    "unit_multiplier": observation.get("unit_multiplier", ""),
                    "source_url": chosen["url"],
                    "source_sha256": chosen["sha256"],
                    "source_format": "PDF",
                    "extraction_method": METHOD,
                    "methodology_version": METHODOLOGY_VERSION,
                    "page": observation.get("page", ""),
                    "matched_alias": observation.get("matched_alias", ""),
                    "confidence": observation.get("confidence", ""),
                }
            )

        docs.append(
            {
                **common,
                "canonical_title": row["canonical_title"],
                "canonical_source_url": row["canonical_source_url"],
                "selected_source_url": chosen["url"],
                "selected_source_sha256": chosen["sha256"],
                "selected_source_bytes": str(chosen["bytes"]),
                "tie_candidate_count": str(len(all_candidates)),
                "tie_resolution": resolution,
                "candidate_evidence_json": json.dumps(
                    slim_evidence(candidate_evidence), ensure_ascii=False, default=str
                ),
                "tier1_found": str(parsed["tier1_found"]),
                "tier2_found": str(parsed["tier2_found"]),
                "numeric_observations": str(found),
                "document_status": "PASS",
                "document_error": "",
            }
        )

        if index % 50 == 0 or index == len(rows):
            print(
                f"S3G1J_V17_17 shard={args.shard}/{args.shards} "
                f"{index}/{len(rows)} bytes={download_bytes}",
                flush=True,
            )
        time.sleep(0.02)

    numeric_path = out / f"financial_values_shard{args.shard:02d}.csv.gz"
    documents_path = out / f"financial_documents_shard{args.shard:02d}.csv.gz"
    manifest_path = out / f"financial_extract_shard{args.shard:02d}.manifest.json"

    write_deterministic_csv_gz(numeric_path, base.NUMERIC_FIELDS, numeric)
    write_deterministic_csv_gz(documents_path, base.DOC_FIELDS, docs)

    passed = not errors and len(docs) == len(rows)
    manifest = {
        "gate": "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_17",
        "parser_method": METHOD,
        "methodology_version": METHODOLOGY_VERSION,
        "shard": args.shard,
        "shards": args.shards,
        "selected_versions": len(rows),
        "document_rows": len(docs),
        "numeric_rows": len(numeric),
        "download_bytes": download_bytes,
        "tie_resolution_counts": tie_counts,
        "error_count": len(errors),
        "errors": errors,
        "numeric_sha256": sha_file(numeric_path),
        "documents_sha256": sha_file(documents_path),
        "gzip_header_mtime": 0,
        "gzip_embedded_filename": "",
        "source_format": "PDF",
        "original_pdf_authority": True,
        "current_f10_historical_backfill_used": False,
        "pass": passed,
        "stage4_alpha_locked": True,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
