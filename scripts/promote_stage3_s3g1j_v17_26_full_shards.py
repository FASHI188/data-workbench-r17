#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
from pathlib import Path

NUMERIC_FIELDS = [
    "exchange", "source_code", "effective_code", "issuer_org_id", "report_family",
    "economic_date", "announcement_id", "revision_sequence", "source_published_at",
    "effective_session", "available_at", "concept", "raw_value",
    "normalized_cny_value", "unit", "unit_multiplier", "source_url",
    "source_sha256", "source_format", "extraction_method", "methodology_version",
    "page", "matched_alias", "confidence",
]
DOC_FIELDS = [
    "exchange", "source_code", "effective_code", "issuer_org_id", "report_family",
    "economic_date", "announcement_id", "revision_sequence", "source_published_at",
    "effective_session", "available_at", "canonical_title",
    "canonical_source_url", "selected_source_url", "selected_source_sha256",
    "selected_source_bytes", "tie_candidate_count", "tie_resolution",
    "candidate_evidence_json", "tier1_found", "tier2_found",
    "numeric_observations", "document_status", "document_error",
]

TARGETS = {
    "1207035181": {
        "source_sha256": "320e3a950a4768e73766d57a09bcf34d893d4da949b8ed5a1b2f887852e76229",
        "values": {
            "TOTAL_ASSETS": "760508375.73",
            "TOTAL_LIABILITIES": "176499397.46",
            "TOTAL_EQUITY": "584008978.27",
        },
    },
    "1221568845": {
        "source_sha256": "fa72059d35715f20df620691538528f720fe3ae42581c172c853f26799befb93",
        "values": {
            "TOTAL_ASSETS": "3642768851.01",
            "TOTAL_LIABILITIES": "2382626915.88",
            "TOTAL_EQUITY": "1260141935.13",
        },
    },
}

METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V16_V17_26_EXACT_SOURCE_BALANCE_ONLY_PRODUCTION"
METHODOLOGY = "V3.3.6-V17.26"
GATE = "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_26"
GENERATION = "V17.26"


def read_gz(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_gz(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
        ) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shard_id(path: Path) -> int:
    match = re.search(r"shard(\d+)\.manifest\.json$", path.name)
    if not match:
        raise ValueError(f"cannot parse shard identity from {path}")
    return int(match.group(1))


def load_target_evidence(values_path: Path, docs_path: Path):
    values = read_gz(values_path)
    docs = read_gz(docs_path)
    by_doc = {row["announcement_id"]: row for row in docs}
    if set(by_doc) != set(TARGETS) or len(docs) != len(TARGETS):
        raise ValueError(
            f"V17.26 target document population changed {sorted(by_doc)}"
        )

    by_values: dict[str, list[dict[str, str]]] = {aid: [] for aid in TARGETS}
    for row in values:
        aid = row["announcement_id"]
        if aid not in by_values:
            raise ValueError(f"unexpected V17.26 target numeric row {aid}")
        by_values[aid].append(row)

    for aid, target in TARGETS.items():
        doc = by_doc[aid]
        if doc["document_status"] != "PASS" or doc["document_error"]:
            raise ValueError(f"V17.26 target document did not pass {aid}")
        if doc["selected_source_sha256"] != target["source_sha256"]:
            raise ValueError(f"V17.26 target document source SHA changed {aid}")
        if doc["numeric_observations"] != "3":
            raise ValueError(f"V17.26 target observation count is not three {aid}")
        if doc["tier1_found"] != "0" or doc["tier2_found"] != "3":
            raise ValueError(f"V17.26 target tier counts changed {aid}")

        rows = by_values[aid]
        if len(rows) != 3:
            raise ValueError(f"V17.26 target numeric rows changed {aid}: {len(rows)}")
        by_concept = {row["concept"]: row for row in rows}
        if set(by_concept) != set(target["values"]):
            raise ValueError(
                f"V17.26 target concepts changed {aid}: {sorted(by_concept)}"
            )
        for concept, expected in target["values"].items():
            row = by_concept[concept]
            if row["source_sha256"] != target["source_sha256"]:
                raise ValueError(f"V17.26 target numeric source SHA changed {aid}")
            if row["normalized_cny_value"] != expected:
                raise ValueError(
                    f"V17.26 target value changed {aid} {concept} "
                    f"expected={expected} actual={row['normalized_cny_value']}"
                )
            if row["extraction_method"] != METHOD:
                raise ValueError(f"V17.26 target method changed {aid} {concept}")
            if row["methodology_version"] != METHODOLOGY:
                raise ValueError(f"V17.26 target methodology changed {aid} {concept}")
    return by_doc, by_values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--target-values", required=True)
    parser.add_argument("--target-documents", required=True)
    parser.add_argument("--out-report", required=True)
    parser.add_argument("--source-run", type=int, default=30692117760)
    args = parser.parse_args()

    root = Path(args.root)
    target_docs, target_values = load_target_evidence(
        Path(args.target_values), Path(args.target_documents)
    )

    manifests = sorted(root.rglob("financial_extract_shard*.manifest.json"))
    if len(manifests) != 64:
        raise ValueError(f"expected 64 source manifests, got {len(manifests)}")
    identities = [shard_id(path) for path in manifests]
    if sorted(identities) != list(range(64)) or len(set(identities)) != 64:
        raise ValueError(f"source shard identities changed {identities}")

    target_locations: dict[str, int] = {}
    previous_target_numeric_counts: dict[str, int] = {aid: 0 for aid in TARGETS}
    promoted_numeric_total = 0
    promoted_document_total = 0
    promoted_error_total = 0

    for manifest_path in manifests:
        shard = shard_id(manifest_path)
        directory = manifest_path.parent
        numeric_path = directory / f"financial_values_shard{shard:02d}.csv.gz"
        docs_path = directory / f"financial_documents_shard{shard:02d}.csv.gz"
        if not numeric_path.exists() or not docs_path.exists():
            raise ValueError(f"missing source shard files {shard}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("runtime_generation") != "V17.25":
            raise ValueError(f"source shard generation changed {shard}")
        if manifest.get("gate") != "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_25":
            raise ValueError(f"source shard gate changed {shard}")

        docs = read_gz(docs_path)
        numeric = read_gz(numeric_path)
        if len(docs) != int(manifest["document_rows"]):
            raise ValueError(f"source document count mismatch shard {shard}")
        if len(numeric) != int(manifest["numeric_rows"]):
            raise ValueError(f"source numeric count mismatch shard {shard}")

        found_targets = [row["announcement_id"] for row in docs if row["announcement_id"] in TARGETS]
        for aid in found_targets:
            if aid in target_locations:
                raise ValueError(f"duplicate target document across shards {aid}")
            target_locations[aid] = shard

        for row in numeric:
            aid = row["announcement_id"]
            if aid in previous_target_numeric_counts:
                previous_target_numeric_counts[aid] += 1

        docs = [row for row in docs if row["announcement_id"] not in TARGETS]
        numeric = [row for row in numeric if row["announcement_id"] not in TARGETS]

        for row in numeric:
            row["extraction_method"] = METHOD
            row["methodology_version"] = METHODOLOGY

        for aid, location in target_locations.items():
            if location == shard:
                docs.append(dict(target_docs[aid]))
                numeric.extend(dict(row) for row in target_values[aid])

        docs.sort(key=lambda row: row["announcement_id"])
        numeric.sort(key=lambda row: (row["announcement_id"], row["concept"]))
        write_gz(docs_path, DOC_FIELDS, docs)
        write_gz(numeric_path, NUMERIC_FIELDS, numeric)

        actual_errors = sum(
            row["document_status"] != "PASS" or bool(row["document_error"])
            for row in docs
        )
        if actual_errors != int(manifest["error_count"]):
            raise ValueError(
                f"promoted shard error count drift {shard}: "
                f"{actual_errors} != {manifest['error_count']}"
            )
        if len(list(manifest.get("errors") or [])) != actual_errors:
            raise ValueError(f"source manifest error ledger drift shard {shard}")

        manifest["gate"] = GATE
        manifest["parser_method"] = METHOD
        manifest["methodology_version"] = METHODOLOGY
        manifest["runtime_generation"] = GENERATION
        manifest["document_rows"] = len(docs)
        manifest["numeric_rows"] = len(numeric)
        manifest["numeric_sha256"] = sha256(numeric_path)
        manifest["documents_sha256"] = sha256(docs_path)
        manifest["source_full_run"] = args.source_run
        manifest["exact_source_balance_only_targets"] = sorted(TARGETS)
        manifest["non_balance_values_promoted_for_targets"] = False
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        promoted_numeric_total += len(numeric)
        promoted_document_total += len(docs)
        promoted_error_total += actual_errors

    if set(target_locations) != set(TARGETS):
        raise ValueError(f"target shard population changed {target_locations}")
    if previous_target_numeric_counts != {aid: 9 for aid in TARGETS}:
        raise ValueError(
            f"source target numeric population changed {previous_target_numeric_counts}"
        )
    if promoted_document_total != 121354:
        raise ValueError(f"promoted document total changed {promoted_document_total}")
    if promoted_numeric_total != 1051778:
        raise ValueError(f"promoted numeric total changed {promoted_numeric_total}")
    if promoted_error_total != 1378:
        raise ValueError(f"promoted error total changed {promoted_error_total}")

    report = {
        "gate": "S3G1J_V17_26_FULL_SHARD_EVIDENCE_PROMOTION",
        "pass": True,
        "source_run": args.source_run,
        "source_generation": "V17.25",
        "promoted_generation": GENERATION,
        "shard_count": 64,
        "target_shard_locations": target_locations,
        "previous_target_numeric_counts": previous_target_numeric_counts,
        "promoted_target_numeric_counts": {aid: 3 for aid in TARGETS},
        "document_rows": promoted_document_total,
        "numeric_rows": promoted_numeric_total,
        "document_errors": promoted_error_total,
        "non_target_values_changed": False,
        "non_balance_values_promoted_for_targets": False,
        "errors": [],
    }
    out = Path(args.out_report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
