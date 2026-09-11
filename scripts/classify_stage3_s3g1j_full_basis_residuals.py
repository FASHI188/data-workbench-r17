#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

ISSUER_PREFIX = "PDF_DECLARES_OTHER_A_SHARE_ISSUER"
NO_BLOCK = "NO_VALIDATED_BALANCE_SHEET_BLOCK"
IDENTITY = "BALANCE_SHEET_IDENTITY_MISMATCH"

OUTPUT_FIELDS = [
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
    "canonical_title",
    "canonical_source_url",
    "selected_source_url",
    "selected_source_sha256",
    "tie_candidate_count",
    "tie_resolution",
    "candidate_count_actual",
    "candidate_ids",
    "candidate_errors",
    "candidate_validation_errors",
    "candidate_tier1_counts",
    "candidate_tier2_counts",
    "candidate_page_counts",
    "document_error",
    "residual_class",
    "priority_class",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_gzip_plaintext(path: Path) -> str:
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_csv_gz(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
            writer = csv.DictWriter(
                text, fieldnames=OUTPUT_FIELDS, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
    path.write_bytes(raw.getvalue())


def normalize_validation_errors(candidate: dict) -> list[str]:
    values = candidate.get("validation_errors") or []
    return [str(value) for value in values]


def classify(row: dict, candidates: list[dict]) -> tuple[str, str]:
    document_error = str(row.get("document_error") or "")
    tie_resolution = str(row.get("tie_resolution") or "")
    actual = len(candidates)

    if document_error.startswith(ISSUER_PREFIX):
        return "CANONICAL_PDF_ISSUER_MISMATCH", "P4_ISSUER_AUTHORITY_REVIEW"

    if actual == 1:
        candidate = candidates[0]
        tier2 = int(candidate.get("tier2_found") or 0)
        validation = normalize_validation_errors(candidate)
        joined = " | ".join(validation)
        if IDENTITY in joined:
            priority = (
                "P1_IDENTITY_CONFLICT_TIER2_3"
                if tier2 == 3
                else "P3_IDENTITY_CONFLICT_LOWER_EVIDENCE"
            )
            return f"SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_{tier2}", priority
        if NO_BLOCK not in joined:
            raise ValueError(
                "single canonical candidate has unknown validation errors "
                f"announcement={row.get('announcement_id')} errors={validation}"
            )
        priority = {
            3: "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT",
            2: "P2_SAFE_PARTIAL_TIER2_2",
            1: "P3_SAFE_PARTIAL_TIER2_1",
            0: "P4_SAFE_PARTIAL_TIER2_0",
        }.get(tier2, "P5_UNKNOWN_TIER2")
        return f"SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_{tier2}", priority

    if actual < 2:
        raise ValueError(
            f"empty candidate evidence announcement={row.get('announcement_id')}"
        )
    if tie_resolution == "TIE_VALUE_CONFLICT":
        return "MULTI_CANDIDATE_VALUE_CONFLICT", "P4_SOURCE_VALUE_CONFLICT_REVIEW"
    if tie_resolution == "TIE_SOURCE_INCOMPLETE":
        return (
            f"MULTI_CANDIDATE_SOURCE_INCOMPLETE_{actual}_CANDIDATES",
            "P3_SOURCE_COMPLETENESS_REVIEW",
        )
    raise ValueError(
        "unknown multi-candidate resolution "
        f"announcement={row.get('announcement_id')} "
        f"tie_resolution={tie_resolution!r}"
    )


def build_output_row(
    row: dict,
    candidates: list[dict],
    residual_class: str,
    priority: str,
) -> dict:
    return {
        "exchange": row.get("exchange", ""),
        "source_code": row.get("source_code", ""),
        "effective_code": row.get("effective_code", ""),
        "issuer_org_id": row.get("issuer_org_id", ""),
        "report_family": row.get("report_family", ""),
        "economic_date": row.get("economic_date", ""),
        "announcement_id": row.get("announcement_id", ""),
        "revision_sequence": row.get("revision_sequence", ""),
        "source_published_at": row.get("source_published_at", ""),
        "effective_session": row.get("effective_session", ""),
        "available_at": row.get("available_at", ""),
        "canonical_title": row.get("canonical_title", ""),
        "canonical_source_url": row.get("canonical_source_url", ""),
        "selected_source_url": row.get("selected_source_url", ""),
        "selected_source_sha256": row.get("selected_source_sha256", ""),
        "tie_candidate_count": row.get("tie_candidate_count", ""),
        "tie_resolution": row.get("tie_resolution", ""),
        "candidate_count_actual": str(len(candidates)),
        "candidate_ids": json.dumps(
            [str(item.get("id") or "") for item in candidates],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "candidate_errors": json.dumps(
            [str(item.get("error") or "") for item in candidates],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "candidate_validation_errors": json.dumps(
            [normalize_validation_errors(item) for item in candidates],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "candidate_tier1_counts": json.dumps(
            [int(item.get("tier1_found") or 0) for item in candidates],
            separators=(",", ":"),
        ),
        "candidate_tier2_counts": json.dumps(
            [int(item.get("tier2_found") or 0) for item in candidates],
            separators=(",", ":"),
        ),
        "candidate_page_counts": json.dumps(
            [int(item.get("page_count") or 0) for item in candidates],
            separators=(",", ":"),
        ),
        "document_error": row.get("document_error", ""),
        "residual_class": residual_class,
        "priority_class": priority,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", required=True)
    parser.add_argument("--expected-gzip-sha256", required=True)
    parser.add_argument("--out-root", required=True)
    args = parser.parse_args()

    source = Path(args.documents)
    actual_gzip = sha256_file(source)
    actual_plain = sha256_gzip_plaintext(source)
    if actual_gzip != args.expected_gzip_sha256:
        raise ValueError(
            f"document gzip SHA mismatch expected={args.expected_gzip_sha256} "
            f"actual={actual_gzip}"
        )

    residuals: list[dict] = []
    input_rows = 0
    pass_rows = 0
    with gzip.open(source, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "announcement_id",
            "report_family",
            "candidate_evidence_json",
            "document_status",
            "document_error",
            "tie_candidate_count",
            "tie_resolution",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"missing document columns {sorted(missing)}")
        for row in reader:
            input_rows += 1
            if row.get("document_status") != "ERROR":
                pass_rows += 1
                continue
            candidates = json.loads(row.get("candidate_evidence_json") or "[]")
            if int(row.get("tie_candidate_count") or 0) != len(candidates):
                raise ValueError(
                    "candidate count mismatch "
                    f"announcement={row.get('announcement_id')}"
                )
            residual_class, priority = classify(row, candidates)
            residuals.append(
                build_output_row(row, candidates, residual_class, priority)
            )

    residuals.sort(
        key=lambda row: (
            row["priority_class"],
            row["residual_class"],
            row["economic_date"],
            row["announcement_id"],
        )
    )
    ids = [row["announcement_id"] for row in residuals]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate residual announcement IDs")

    class_counts = Counter(row["residual_class"] for row in residuals)
    priority_counts = Counter(row["priority_class"] for row in residuals)
    family_counts: dict[str, Counter] = defaultdict(Counter)
    for row in residuals:
        family_counts[row["residual_class"]][row["report_family"]] += 1

    expected_classes = {
        "CANONICAL_PDF_ISSUER_MISMATCH": 83,
        "MULTI_CANDIDATE_SOURCE_INCOMPLETE_2_CANDIDATES": 85,
        "MULTI_CANDIDATE_SOURCE_INCOMPLETE_3_CANDIDATES": 2,
        "MULTI_CANDIDATE_VALUE_CONFLICT": 14,
        "SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_2": 12,
        "SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_3": 71,
        "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_0": 550,
        "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_1": 421,
        "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_2": 119,
        "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3": 23,
    }
    if dict(sorted(class_counts.items())) != expected_classes:
        raise ValueError(
            "full-basis residual class counts changed "
            f"actual={dict(sorted(class_counts.items()))}"
        )
    if input_rows != 121354 or pass_rows != 119974 or len(residuals) != 1380:
        raise ValueError(
            f"full-basis accounting changed input={input_rows} "
            f"pass={pass_rows} residuals={len(residuals)}"
        )

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    ledger_path = out_root / "s3g1j_full_basis_residual_classification.csv.gz"
    p0_path = out_root / "s3g1j_full_basis_p0_safe_near_complete.csv.gz"
    deterministic_csv_gz(ledger_path, residuals)
    deterministic_csv_gz(
        p0_path,
        [
            row
            for row in residuals
            if row["priority_class"]
            == "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT"
        ],
    )
    summary = {
        "gate": "S3G1J_FULL_BASIS_RESIDUAL_CLASSIFICATION_V1",
        "source_run": 30649251360,
        "source_artifact": "stage3-s3g1j-v17-21-full-final",
        "source_artifact_digest": "sha256:7faff72949a6e0a98f49088bce99bc2df37c7cbcb0259b39d1b2655fc02f6086",
        "source_documents_plain_sha256": actual_plain,
        "source_documents_gzip_sha256": actual_gzip,
        "input_document_rows": input_rows,
        "pass_document_rows": pass_rows,
        "residual_document_rows": len(residuals),
        "class_counts": dict(sorted(class_counts.items())),
        "priority_counts": dict(sorted(priority_counts.items())),
        "report_family_counts_by_class": {
            key: dict(sorted(value.items()))
            for key, value in sorted(family_counts.items())
        },
        "p0_safe_near_complete_count": priority_counts[
            "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT"
        ],
        "p1_identity_conflict_tier2_3_count": priority_counts[
            "P1_IDENTITY_CONFLICT_TIER2_3"
        ],
        "classification_ledger_sha256": sha256_gzip_plaintext(ledger_path),
        "classification_ledger_gzip_sha256": sha256_file(ledger_path),
        "p0_ledger_sha256": sha256_gzip_plaintext(p0_path),
        "p0_ledger_gzip_sha256": sha256_file(p0_path),
        "gzip_mtime": 0,
        "gzip_embedded_filename": "",
        "production_data_changed": False,
        "parser_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_locked": True,
        "pass": True,
        "errors": [],
    }
    summary_path = (
        out_root / "s3g1j_full_basis_residual_classification_summary.json"
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
