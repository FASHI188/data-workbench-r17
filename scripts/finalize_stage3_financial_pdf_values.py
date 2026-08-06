#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from collections import Counter, defaultdict
from datetime import date
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
SHARD_GATE_PREFIX = "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def readgz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def write_deterministic_csv_gz(path: Path, fields, rows) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
        ) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)


def _single_nonempty(values: set[str], label: str, errors: list[str]) -> str:
    clean = {str(value) for value in values if value not in (None, "")}
    if len(clean) != 1:
        errors.append(f"mixed or missing {label}: {sorted(clean)}")
        return ""
    return next(iter(clean))


def _validate_shard_manifests(
    manifests: list[Path],
    expected_version_count: int,
    expected_gate: str,
    expected_method: str,
    expected_methodology: str,
    errors: list[str],
) -> tuple[dict[int, dict], dict]:
    manifest_map: dict[int, dict] = {}
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        shard = int(manifest.get("shard", -1))
        if shard in manifest_map:
            errors.append(f"duplicate shard manifest {shard}")
        manifest_map[shard] = manifest
        if manifest.get("pass") is not True:
            errors.append(f"shard {shard} pass is not true")
        if int(manifest.get("shards", -1)) != 64:
            errors.append(f"shard {shard} geometry is not 64")
        if manifest.get("error_count") != 0 or manifest.get("errors"):
            errors.append(
                f"shard {shard} errors={manifest.get('error_count')} "
                f"{list(manifest.get('errors') or [])[:5]}"
            )
        if manifest.get("source_format") != "PDF":
            errors.append(f"shard {shard} source_format is not PDF")
        if manifest.get("original_pdf_authority") is not True:
            errors.append(f"shard {shard} original_pdf_authority is not true")
        if manifest.get("current_f10_historical_backfill_used") is not False:
            errors.append(f"shard {shard} current F10 backfill flag is not false")
        if manifest.get("stage4_alpha_locked") is not True:
            errors.append(f"shard {shard} Stage4/Alpha lock is not true")
        if int(manifest.get("document_rows", -1)) != int(
            manifest.get("selected_versions", -2)
        ):
            errors.append(
                f"shard {shard} document/selected mismatch "
                f"{manifest.get('document_rows')} != {manifest.get('selected_versions')}"
            )

    expected_shards = set(range(64))
    actual_shards = set(manifest_map)
    if actual_shards != expected_shards:
        missing = sorted(expected_shards - actual_shards)
        extra = sorted(actual_shards - expected_shards)
        errors.append(f"shard identity mismatch missing={missing} extra={extra}")

    gate = _single_nonempty(
        {row.get("gate") for row in manifest_map.values()}, "shard gate", errors
    )
    method = _single_nonempty(
        {row.get("parser_method") for row in manifest_map.values()},
        "parser method",
        errors,
    )
    methodology = _single_nonempty(
        {row.get("methodology_version") for row in manifest_map.values()},
        "methodology version",
        errors,
    )
    runtime_generation = _single_nonempty(
        {row.get("runtime_generation") for row in manifest_map.values()},
        "runtime generation",
        errors,
    )

    if gate and not gate.startswith(SHARD_GATE_PREFIX):
        errors.append(f"invalid shard gate {gate}")
    if expected_gate and gate != expected_gate:
        errors.append(f"unexpected shard gate expected={expected_gate} actual={gate}")
    if expected_method and method != expected_method:
        errors.append(
            f"unexpected parser method expected={expected_method} actual={method}"
        )
    if expected_methodology and methodology != expected_methodology:
        errors.append(
            "unexpected methodology version "
            f"expected={expected_methodology} actual={methodology}"
        )

    selected_total = sum(
        int(row.get("selected_versions", 0)) for row in manifest_map.values()
    )
    document_total = sum(
        int(row.get("document_rows", 0)) for row in manifest_map.values()
    )
    numeric_total = sum(
        int(row.get("numeric_rows", 0)) for row in manifest_map.values()
    )
    if selected_total != expected_version_count:
        errors.append(
            f"manifest selected_versions total {selected_total} "
            f"!= expected {expected_version_count}"
        )

    identity = {
        "gate": gate,
        "parser_method": method,
        "methodology_version": methodology,
        "runtime_generation": runtime_generation,
        "selected_versions_total": selected_total,
        "document_rows_total": document_total,
        "numeric_rows_total": numeric_total,
    }
    return manifest_map, identity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--versions", required=True)
    parser.add_argument("--stage2-manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expected-shard-gate", default="")
    parser.add_argument("--expected-parser-method", default="")
    parser.add_argument("--expected-methodology-version", default="")
    args = parser.parse_args()

    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    manifests = sorted(root.rglob("financial_extract_shard*.manifest.json"))
    numeric_files = sorted(root.rglob("financial_values_shard*.csv.gz"))
    document_files = sorted(root.rglob("financial_documents_shard*.csv.gz"))
    if len(manifests) != 64:
        errors.append(f"expected 64 manifests got {len(manifests)}")
    if len(numeric_files) != 64:
        errors.append(f"expected 64 numeric files got {len(numeric_files)}")
    if len(document_files) != 64:
        errors.append(f"expected 64 document files got {len(document_files)}")

    expected_versions: dict[str, dict] = {}
    with gzip.open(args.versions, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            aid = row["canonical_announcement_id"]
            if aid in expected_versions:
                errors.append(f"duplicate canonical version {aid}")
            expected_versions[aid] = row

    stage2 = json.loads(Path(args.stage2_manifest).read_text(encoding="utf-8"))
    if (
        stage2.get("version") != "V3.2.25-stage2-final-freeze"
        or stage2.get("stage2_dataset_fingerprint")
        != "f17f7ab63f4532dda635eb7366e7df7bf5497a5ce814410105312bccb53125bb"
    ):
        errors.append("wrong Stage2 dependency")

    manifest_map, shard_identity = _validate_shard_manifests(
        manifests,
        len(expected_versions),
        args.expected_shard_gate,
        args.expected_parser_method,
        args.expected_methodology_version,
        errors,
    )

    for path in numeric_files:
        shard = int(path.stem.split("shard")[-1].split(".")[0])
        manifest = manifest_map.get(shard)
        if manifest and sha(path) != manifest.get("numeric_sha256"):
            errors.append(f"numeric SHA mismatch shard {shard}")
    for path in document_files:
        shard = int(path.stem.split("shard")[-1].split(".")[0])
        manifest = manifest_map.get(shard)
        if manifest and sha(path) != manifest.get("documents_sha256"):
            errors.append(f"doc SHA mismatch shard {shard}")

    all_docs: list[dict] = []
    all_nums: list[dict] = []
    for path in document_files:
        all_docs.extend(readgz(path))
    for path in numeric_files:
        all_nums.extend(readgz(path))

    if len(all_docs) != shard_identity["document_rows_total"]:
        errors.append(
            f"document rows disagree with manifests "
            f"{len(all_docs)} != {shard_identity['document_rows_total']}"
        )
    if len(all_nums) != shard_identity["numeric_rows_total"]:
        errors.append(
            f"numeric rows disagree with manifests "
            f"{len(all_nums)} != {shard_identity['numeric_rows_total']}"
        )

    numeric_methods = {row.get("extraction_method", "") for row in all_nums}
    numeric_methodologies = {row.get("methodology_version", "") for row in all_nums}
    if all_nums and numeric_methods != {shard_identity["parser_method"]}:
        errors.append(
            f"numeric extraction methods do not match shard parser "
            f"{sorted(numeric_methods)} != {shard_identity['parser_method']}"
        )
    if all_nums and numeric_methodologies != {shard_identity["methodology_version"]}:
        errors.append(
            "numeric methodology versions do not match shard manifests "
            f"{sorted(numeric_methodologies)} "
            f"!= {shard_identity['methodology_version']}"
        )

    doc_by: dict[str, dict] = {}
    duplicate_docs: list[str] = []
    for row in all_docs:
        aid = row["announcement_id"]
        if aid in doc_by:
            duplicate_docs.append(aid)
        doc_by[aid] = row
    if duplicate_docs:
        errors.append(
            f"duplicate document IDs {duplicate_docs[:20]} "
            f"count={len(duplicate_docs)}"
        )

    missing_docs = sorted(set(expected_versions) - set(doc_by))
    extra_docs = sorted(set(doc_by) - set(expected_versions))
    if missing_docs:
        errors.append(
            f"missing version documents {missing_docs[:20]} count={len(missing_docs)}"
        )
    if extra_docs:
        errors.append(
            f"extra version documents {extra_docs[:20]} count={len(extra_docs)}"
        )

    bad_docs = [
        row["announcement_id"]
        for row in all_docs
        if row["document_status"] != "PASS" or not row["selected_source_sha256"]
    ]
    if bad_docs:
        errors.append(
            f"documents not clean PASS {bad_docs[:20]} count={len(bad_docs)}"
        )
    unresolved_ties = [
        row["announcement_id"]
        for row in all_docs
        if row["tie_resolution"]
        in ("TIE_SOURCE_INCOMPLETE", "TIE_VALUE_CONFLICT", "NO_CANDIDATE")
    ]
    if unresolved_ties:
        errors.append(
            f"unresolved tied versions {unresolved_ties[:20]} "
            f"count={len(unresolved_ties)}"
        )

    observation_keys: set[tuple[str, str]] = set()
    duplicate_observations: list[tuple[str, str]] = []
    coverage = Counter()
    by_year = defaultdict(Counter)
    by_family = defaultdict(Counter)
    for row in all_nums:
        key = (row["announcement_id"], row["concept"])
        if key in observation_keys:
            duplicate_observations.append(key)
        observation_keys.add(key)
        document = doc_by.get(row["announcement_id"])
        if not document:
            errors.append(f"numeric row missing document {row['announcement_id']}")
            continue
        if row["source_sha256"] != document["selected_source_sha256"]:
            errors.append(
                f"numeric/document SHA mismatch "
                f"{row['announcement_id']} {row['concept']}"
            )
        if (
            row["source_format"] != "PDF"
            or not row["source_sha256"]
            or not row["normalized_cny_value"]
        ):
            errors.append(
                f"invalid numeric provenance "
                f"{row['announcement_id']} {row['concept']}"
            )
        if (
            row["effective_session"] != document["effective_session"]
            or row["available_at"] != document["available_at"]
        ):
            errors.append(
                f"availability mismatch {row['announcement_id']} {row['concept']}"
            )
        if (
            row["effective_session"]
            and row["source_published_at"]
            and date.fromisoformat(row["effective_session"])
            <= date.fromisoformat(row["source_published_at"])
        ):
            errors.append(f"same-day/backdated availability {row['announcement_id']}")
        coverage[row["concept"]] += 1
        by_year[row["economic_date"][:4]][row["concept"]] += 1
        by_family[row["report_family"]][row["concept"]] += 1
    if duplicate_observations:
        errors.append(
            f"duplicate observation keys {duplicate_observations[:20]} "
            f"count={len(duplicate_observations)}"
        )

    numeric_out = out / "stage3_financial_raw_values.csv.gz"
    document_out = out / "stage3_financial_documents.csv.gz"
    all_nums.sort(
        key=lambda row: (
            row["source_published_at"],
            row["exchange"],
            row["source_code"],
            row["announcement_id"],
            row["concept"],
        )
    )
    all_docs.sort(
        key=lambda row: (
            row["source_published_at"],
            row["exchange"],
            row["source_code"],
            row["announcement_id"],
        )
    )
    write_deterministic_csv_gz(numeric_out, NUMERIC_FIELDS, all_nums)
    write_deterministic_csv_gz(document_out, DOC_FIELDS, all_docs)

    report = {
        "gate": "S3G1J_ORIGINAL_PDF_FINANCIAL_VALUES_FINAL",
        "pass": not errors,
        "stage2_version": stage2.get("version"),
        "stage2_fingerprint": stage2.get("stage2_dataset_fingerprint"),
        "shard_gate": shard_identity["gate"],
        "parser_method": shard_identity["parser_method"],
        "methodology_version": shard_identity["methodology_version"],
        "runtime_generation": shard_identity["runtime_generation"],
        "canonical_version_count": len(expected_versions),
        "document_count": len(all_docs),
        "numeric_observation_count": len(all_nums),
        "concept_coverage": dict(coverage),
        "coverage_by_year": {
            key: dict(value) for key, value in sorted(by_year.items())
        },
        "coverage_by_family": {
            key: dict(value) for key, value in sorted(by_family.items())
        },
        "unresolved_tie_count": len(unresolved_ties),
        "document_error_count": len(bad_docs),
        "financial_values_sha256": sha(numeric_out),
        "financial_documents_sha256": sha(document_out),
        "gzip_header_mtime": 0,
        "gzip_embedded_filename": "",
        "authority": "CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256",
        "historical_current_f10_used_as_truth": False,
        "stage4_alpha_locked": True,
        "errors": errors,
    }
    (out / "stage3_financial_raw_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "gate",
                    "pass",
                    "shard_gate",
                    "parser_method",
                    "methodology_version",
                    "canonical_version_count",
                    "document_count",
                    "numeric_observation_count",
                    "concept_coverage",
                    "unresolved_tie_count",
                    "document_error_count",
                    "errors",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
