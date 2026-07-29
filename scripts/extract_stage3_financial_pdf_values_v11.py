#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
import time
from pathlib import Path

import requests

import extract_stage3_financial_pdf_values_v10 as v15
from stage3_financial_pdf_parser_v10 import parse_pdf_bytes as v16_parse_pdf_bytes

# Importing V15.1 installs the accepted issuer and tied-candidate resolver chain
# on this shared base module. This V16 driver changes only PDF parsing and passes
# the frozen economic_date explicitly for every candidate.
base = v15.v14.v9.base
METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V11_V16_7_CONTEXTUAL_PERIOD_COLUMN_FALLBACK"


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    parsed = dict(v16_parse_pdf_bytes(raw, economic_date))
    parsed["declared_a_share_codes"] = v15.v14.v9.declared_a_share_codes(raw)
    return parsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = [
        r for r in base.read_versions(Path(a.versions))
        if base.stable_shard(r["canonical_announcement_id"], a.shards) == a.shard
    ]
    session = requests.Session()
    numeric: list[dict] = []
    docs: list[dict] = []
    errors: list[str] = []
    download_bytes = 0
    tie_counts: dict[str, int] = {}

    for idx, r in enumerate(rows, 1):
        all_candidates = base.candidate_list(r)
        candidates, excluded = base.filter_candidates_by_issuer(
            all_candidates, r["source_code"], r["canonical_announcement_id"]
        )
        parsed_candidates = []
        for candidate in candidates:
            ev = {"id": candidate["id"], "title": candidate["title"], "url": candidate["url"]}
            try:
                raw = base.get_pdf(session, candidate["url"])
                download_bytes += len(raw)
                parsed = parse_pdf_bytes(raw, r["economic_date"])
                ev.update({"sha256": base.sha(raw), "bytes": len(raw), "parsed": parsed})
                if parsed.get("validation_errors"):
                    ev["error"] = "; ".join(map(str, parsed["validation_errors"]))
            except Exception as exc:
                ev["error"] = repr(exc)
            parsed_candidates.append(ev)

        chosen, resolution, resolution_error = base.resolve_candidates(
            parsed_candidates, r["canonical_announcement_id"]
        )
        if excluded:
            resolution += "_AFTER_ISSUER_FILTER"
        tie_counts[resolution] = tie_counts.get(resolution, 0) + 1

        common = {
            "exchange": r["exchange"],
            "source_code": r["source_code"],
            "effective_code": r["effective_code"],
            "issuer_org_id": r["org_id"],
            "report_family": r["report_family"],
            "economic_date": r["economic_date"],
            "announcement_id": r["canonical_announcement_id"],
            "revision_sequence": r["revision_sequence"],
            "source_published_at": r["source_published_at"],
            "effective_session": r["effective_session"],
            "available_at": r["available_at"],
        }
        evidence = parsed_candidates + excluded

        if chosen is None:
            err = resolution_error or resolution
            errors.append(f"{r['canonical_announcement_id']} {resolution}: {err}")
            docs.append({
                **common,
                "canonical_title": r["canonical_title"],
                "canonical_source_url": r["canonical_source_url"],
                "selected_source_url": "",
                "selected_source_sha256": "",
                "selected_source_bytes": "",
                "tie_candidate_count": str(len(all_candidates)),
                "tie_resolution": resolution,
                "candidate_evidence_json": json.dumps(evidence, ensure_ascii=False, default=str),
                "tier1_found": "0",
                "tier2_found": "0",
                "numeric_observations": "0",
                "document_status": "ERROR",
                "document_error": err,
            })
            continue

        parsed = chosen["parsed"]
        found = 0
        for concept, observation in parsed["observations"].items():
            if observation.get("status") != "FOUND":
                continue
            found += 1
            numeric.append({
                **common,
                "concept": concept,
                "raw_value": observation.get("raw_value") or "",
                "normalized_cny_value": observation.get("normalized_cny_value") or "",
                "unit": observation.get("unit") or "",
                "unit_multiplier": observation.get("unit_multiplier") or "",
                "source_url": chosen["url"],
                "source_sha256": chosen["sha256"],
                "source_format": "PDF",
                "extraction_method": METHOD,
                "methodology_version": "V3.3.2",
                "page": observation.get("page") or "",
                "matched_alias": observation.get("matched_alias") or "",
                "confidence": observation.get("confidence") or "",
            })

        slim = []
        for item in evidence:
            ev = {
                k: item.get(k)
                for k in ("id", "title", "url", "sha256", "bytes", "error", "excluded_reason")
                if item.get(k) not in (None, "")
            }
            if item.get("parsed"):
                ev.update({
                    "tier1_found": item["parsed"]["tier1_found"],
                    "tier2_found": item["parsed"]["tier2_found"],
                    "page_count": item["parsed"].get("page_count"),
                    "balance_sheet_arbitration": (item["parsed"].get("balance_sheet_block") or {}).get("arbitration"),
                })
            slim.append(ev)
        docs.append({
            **common,
            "canonical_title": r["canonical_title"],
            "canonical_source_url": r["canonical_source_url"],
            "selected_source_url": chosen["url"],
            "selected_source_sha256": chosen["sha256"],
            "selected_source_bytes": str(chosen["bytes"]),
            "tie_candidate_count": str(len(all_candidates)),
            "tie_resolution": resolution,
            "candidate_evidence_json": json.dumps(slim, ensure_ascii=False),
            "tier1_found": str(parsed["tier1_found"]),
            "tier2_found": str(parsed["tier2_found"]),
            "numeric_observations": str(found),
            "document_status": "PASS",
            "document_error": "",
        })
        if idx % 50 == 0:
            print(f"shard {a.shard}/{a.shards} {idx}/{len(rows)} docs bytes={download_bytes}", flush=True)
        time.sleep(0.03)

    numeric_path = out / f"financial_values_shard{a.shard:02d}.csv.gz"
    docs_path = out / f"financial_documents_shard{a.shard:02d}.csv.gz"
    with gzip.open(numeric_path, "wt", encoding="utf-8", newline="", compresslevel=9) as handle:
        writer = csv.DictWriter(handle, fieldnames=base.NUMERIC_FIELDS)
        writer.writeheader()
        writer.writerows(numeric)
    with gzip.open(docs_path, "wt", encoding="utf-8", newline="", compresslevel=9) as handle:
        writer = csv.DictWriter(handle, fieldnames=base.DOC_FIELDS)
        writer.writeheader()
        writer.writerows(docs)

    manifest = {
        "gate": "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD",
        "method": METHOD,
        "shard": a.shard,
        "shards": a.shards,
        "selected_versions": len(rows),
        "document_rows": len(docs),
        "numeric_rows": len(numeric),
        "download_bytes": download_bytes,
        "tie_resolution_counts": tie_counts,
        "error_count": len(errors),
        "errors": errors[:200],
        "numeric_file": numeric_path.name,
        "numeric_sha256": base.sha(numeric_path.read_bytes()),
        "documents_file": docs_path.name,
        "documents_sha256": base.sha(docs_path.read_bytes()),
    }
    (out / f"financial_extract_shard{a.shard:02d}.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: manifest[k] for k in (
        "shard", "selected_versions", "numeric_rows", "download_bytes", "tie_resolution_counts", "error_count"
    )}, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
