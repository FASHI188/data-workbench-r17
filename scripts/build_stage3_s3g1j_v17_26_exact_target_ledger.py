#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

import requests

import extract_stage3_financial_pdf_values_v16 as extractor
import promote_stage3_s3g1j_v17_26_full_shards as common

TARGETS = common.TARGETS
ALLOWED_CONCEPTS = frozenset(("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"))


def _read_gz(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _find_source_rows(root: Path) -> tuple[dict[str, dict[str, str]], dict[str, list[dict[str, str]]]]:
    docs: dict[str, dict[str, str]] = {}
    values: dict[str, list[dict[str, str]]] = {aid: [] for aid in TARGETS}

    for path in root.rglob("financial_documents_shard*.csv.gz"):
        for row in _read_gz(path):
            aid = row.get("announcement_id", "")
            if aid not in TARGETS:
                continue
            if aid in docs:
                raise ValueError(f"duplicate source target document {aid}")
            docs[aid] = row

    for path in root.rglob("financial_values_shard*.csv.gz"):
        for row in _read_gz(path):
            aid = row.get("announcement_id", "")
            if aid in values:
                values[aid].append(row)

    if set(docs) != set(TARGETS):
        raise ValueError(f"source target document population changed {sorted(docs)}")
    for aid, rows in values.items():
        if len(rows) != 9:
            raise ValueError(f"source V17.25 target numeric count changed {aid}: {len(rows)}")
    return docs, values


def _rewrite_candidate_evidence(raw_value: str, selected_url: str, selected_sha: str, parser_version: str) -> str:
    try:
        evidence = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("source candidate evidence is not valid JSON") from exc
    if not isinstance(evidence, list):
        raise ValueError("source candidate evidence is not a list")

    matches = 0
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if item.get("url") == selected_url and item.get("sha256") == selected_sha:
            item["tier1_found"] = 0
            item["tier2_found"] = 3
            item["parser_version"] = parser_version
            item["validation_errors"] = []
            item.pop("error", None)
            matches += 1
    if matches < 1:
        raise ValueError("selected source missing from candidate evidence")
    return json.dumps(evidence, ensure_ascii=False, default=str)


def _build_target(
    session: requests.Session,
    source_doc: dict[str, str],
) -> tuple[dict[str, str], list[dict[str, str]], int]:
    aid = source_doc["announcement_id"]
    target = TARGETS[aid]
    selected_url = source_doc.get("selected_source_url", "")
    selected_sha = source_doc.get("selected_source_sha256", "")

    if source_doc.get("document_status") != "PASS" or source_doc.get("document_error"):
        raise ValueError(f"source V17.25 target document is not PASS {aid}")
    if not selected_url:
        raise ValueError(f"source V17.25 target missing selected URL {aid}")
    if selected_sha != target["source_sha256"]:
        raise ValueError(
            f"source V17.25 selected SHA changed {aid} "
            f"expected={target['source_sha256']} actual={selected_sha}"
        )

    raw = extractor.base.get_pdf(session, selected_url)
    actual_sha = _sha256_bytes(raw)
    if actual_sha != target["source_sha256"]:
        raise ValueError(
            f"downloaded selected source SHA mismatch {aid} "
            f"expected={target['source_sha256']} actual={actual_sha}"
        )

    parsed = extractor.parse_pdf_bytes(raw, source_doc["economic_date"])
    if parsed.get("validation_errors"):
        raise ValueError(f"V17.26 retained validation errors {aid}: {parsed['validation_errors']}")
    if parsed.get("tier1_found") != 0 or parsed.get("tier2_found") != 3:
        raise ValueError(
            f"V17.26 target tier counts changed {aid}: "
            f"{parsed.get('tier1_found')}/{parsed.get('tier2_found')}"
        )

    observations = parsed.get("observations") or {}
    found = {
        concept: observation
        for concept, observation in observations.items()
        if isinstance(observation, dict) and observation.get("status") == "FOUND"
    }
    if set(found) != ALLOWED_CONCEPTS:
        raise ValueError(f"V17.26 target concept scope changed {aid}: {sorted(found)}")

    common_fields = {
        key: source_doc[key]
        for key in (
            "exchange",
            "source_code",
            "effective_code",
            "issuer_org_id",
            "report_family",
            "economic_date",
            "announcement_id",
            "revision_sequence",
            "source_published_at",
            "effective_session",
            "available_at",
        )
    }
    numeric_rows: list[dict[str, str]] = []
    for concept in sorted(ALLOWED_CONCEPTS):
        observation = found[concept]
        expected_value = target["values"][concept]
        actual_value = str(observation.get("normalized_cny_value", ""))
        if actual_value != expected_value:
            raise ValueError(
                f"V17.26 target value changed {aid} {concept} "
                f"expected={expected_value} actual={actual_value}"
            )
        numeric_rows.append(
            {
                **common_fields,
                "concept": concept,
                "raw_value": str(observation.get("raw_value", "")),
                "normalized_cny_value": actual_value,
                "unit": str(observation.get("unit", "")),
                "unit_multiplier": str(observation.get("unit_multiplier", "")),
                "source_url": selected_url,
                "source_sha256": selected_sha,
                "source_format": "PDF",
                "extraction_method": extractor.METHOD,
                "methodology_version": extractor.METHODOLOGY_VERSION,
                "page": str(observation.get("page", "")),
                "matched_alias": str(observation.get("matched_alias", "")),
                "confidence": str(observation.get("confidence", "")),
            }
        )

    document = dict(source_doc)
    document["selected_source_bytes"] = str(len(raw))
    document["candidate_evidence_json"] = _rewrite_candidate_evidence(
        source_doc.get("candidate_evidence_json", "[]"),
        selected_url,
        selected_sha,
        str(parsed.get("parser_version", "")),
    )
    document["tier1_found"] = "0"
    document["tier2_found"] = "3"
    document["numeric_observations"] = "3"
    document["document_status"] = "PASS"
    document["document_error"] = ""
    return document, numeric_rows, len(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run", type=int, default=30692117760)
    args = parser.parse_args()

    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    source_docs, source_values = _find_source_rows(root)
    session = requests.Session()
    documents: list[dict[str, str]] = []
    numeric: list[dict[str, str]] = []
    download_bytes = 0
    tie_counts: Counter[str] = Counter()

    for aid in sorted(TARGETS):
        document, rows, byte_count = _build_target(session, source_docs[aid])
        documents.append(document)
        numeric.extend(rows)
        download_bytes += byte_count
        tie_counts[document.get("tie_resolution", "")] += 1

    if len(documents) != 2 or len(numeric) != 6:
        raise ValueError(
            f"V17.26 exact target ledger size changed docs={len(documents)} values={len(numeric)}"
        )
    if {row["announcement_id"] for row in documents} != set(TARGETS):
        raise ValueError("V17.26 exact target document identities changed")
    by_aid = Counter(row["announcement_id"] for row in numeric)
    if by_aid != Counter({aid: 3 for aid in TARGETS}):
        raise ValueError(f"V17.26 exact target numeric distribution changed {dict(by_aid)}")

    documents.sort(key=lambda row: row["announcement_id"])
    numeric.sort(key=lambda row: (row["announcement_id"], row["concept"]))

    numeric_path = out / "financial_values_shard00.csv.gz"
    documents_path = out / "financial_documents_shard00.csv.gz"
    manifest_path = out / "financial_extract_shard00.manifest.json"
    common.write_gz(numeric_path, common.NUMERIC_FIELDS, numeric)
    common.write_gz(documents_path, common.DOC_FIELDS, documents)

    manifest = {
        "gate": "S3G1J_V17_26_EXACT_SELECTED_SOURCE_TARGET_LEDGER",
        "parser_method": extractor.METHOD,
        "methodology_version": extractor.METHODOLOGY_VERSION,
        "runtime_generation": extractor.RUNTIME_GENERATION,
        "source_full_run": args.source_run,
        "source_target_numeric_counts": {aid: len(source_values[aid]) for aid in sorted(TARGETS)},
        "shard": 0,
        "shards": 1,
        "selected_versions": 2,
        "document_rows": 2,
        "numeric_rows": 6,
        "download_bytes": download_bytes,
        "tie_resolution_counts": dict(tie_counts),
        "error_count": 0,
        "errors": [],
        "numeric_sha256": common.sha256(numeric_path),
        "documents_sha256": common.sha256(documents_path),
        "gzip_header_mtime": 0,
        "gzip_embedded_filename": "",
        "source_format": "PDF",
        "original_pdf_authority": True,
        "current_f10_historical_backfill_used": False,
        "exact_selected_source_only": True,
        "candidate_resolver_reused": False,
        "non_balance_values_promoted": False,
        "pass": True,
        "stage4_alpha_locked": True,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
