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
from stage3_financial_pdf_parser_v11 import parse_pdf_bytes as v17_15_parse_pdf_bytes

# Importing V15.1 installs the accepted issuer and tied-candidate resolver chain
# on this shared base module. This driver changes only PDF parsing and passes
# the frozen economic_date explicitly for every candidate.
base = v15.v14.v9.base
METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V11_V17_15_STRICT_ADJACENT_ROW_FINAL_FALLBACK"


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    parsed = dict(v17_15_parse_pdf_bytes(raw, economic_date))
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
                "raw_value": observation.get("raw_value", ""),
                "normalized_cny_value": observation.get("normalized_cny_value", ""),
                "unit": observation.get("unit", ""),
                "unit_multiplier": observation.get("unit_multiplier", ""),
                "page": observation.get("page", ""),
                "matched_alias": observation.get("matched_alias", ""),
                "extraction_scope": observation.get("extraction_scope", ""),
                "confidence": observation.get("confidence", ""),
                "source_url": chosen["url"],
                "source_sha256": chosen["sha256"],
                "source_bytes": chosen["bytes"],
                "extraction_method": METHOD,
                "parser_version": parsed.get("parser_version", ""),
            })

        docs.append({
            **common,
            "canonical_title": r["canonical_title"],
            "canonical_source_url": r["canonical_source_url"],
            "selected_source_url": chosen["url"],
            "selected_source_sha256": chosen["sha256"],
            "selected_source_bytes": chosen["bytes"],
            "tie_candidate_count": str(len(all_candidates)),
            "tie_resolution": resolution,
            "candidate_evidence_json": json.dumps(evidence, ensure_ascii=False, default=str),
            "tier1_found": str(parsed["tier1_found"]),
            "tier2_found": str(parsed["tier2_found"]),
            "numeric_observations": str(found),
            "document_status": "PASS",
            "document_error": "",
        })

        if idx % 10 == 0 or idx == len(rows):
            print(f"S3G1J_V17_15 shard={a.shard} {idx}/{len(rows)} bytes={download_bytes}", flush=True)
        time.sleep(0.02)

    base.write_gz(out / "financial_raw_values.csv.gz", base.NUMERIC_FIELDS, numeric)
    base.write_gz(out / "financial_documents.csv.gz", base.DOC_FIELDS, docs)
    audit = {
        "gate": "S3G1J_FINANCIAL_PDF_RAW_VALUES_V17_15",
        "parser_method": METHOD,
        "shard": a.shard,
        "shards": a.shards,
        "input_versions": len(rows),
        "documents": len(docs),
        "numeric_observations": len(numeric),
        "download_bytes": download_bytes,
        "tie_resolution_counts": tie_counts,
        "errors": errors,
        "pass": not errors and len(docs) == len(rows),
        "stage4_alpha_locked": True,
    }
    (out / "financial_pdf_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
