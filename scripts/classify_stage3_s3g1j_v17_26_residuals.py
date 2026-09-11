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

SOURCE_RUN = 30733013665
SOURCE_ARTIFACT = "stage3-s3g1j-v17-26-full-final"
SOURCE_ARTIFACT_DIGEST = (
    "sha256:7f2e707e9192af527ff0444b48caf6bebfbfa1ef7559ec2810b6f47b1790567b"
)
SOURCE_DOCUMENTS_GZIP_SHA256 = (
    "891d6e10b92e13e3aea604ab9e22bd8dd0ea66764cc485a68abdc50eb8742d68"
)
SOURCE_DOCUMENTS_PLAINTEXT_SHA256 = (
    "98cd05e8ea3569e779080c76c3bbde55174bd919d66cbfcda84a99315be71108"
)
PREVIOUS_CLASSIFIER_RUN = 30687393120
PREVIOUS_CLASSIFIER_ARTIFACT = (
    "stage3-s3g1j-full-basis-residual-classification-v1"
)
PREVIOUS_CLASSIFIER_ARTIFACT_DIGEST = (
    "sha256:3451a94bb70758bbb93d3be4600ad7e0d8d65de618928b1c635f8a29686f7052"
)
PREVIOUS_LEDGER_GZIP_SHA256 = (
    "11ef25f4bc3b08b20b55ac7cfa47d2e9495f4383415b66191f61217ca3cee49e"
)
PREVIOUS_LEDGER_PLAINTEXT_SHA256 = (
    "c7625542e4aada5cc90b0316f5ab71beb4534e752628dbc611749da704f08558"
)
RECOVERED_EXIT_IDS = ("1207035181", "1221568845")

EXPECTED_CLASS_COUNTS = {
    "CANONICAL_PDF_ISSUER_MISMATCH": 83,
    "MULTI_CANDIDATE_SOURCE_INCOMPLETE_2_CANDIDATES": 85,
    "MULTI_CANDIDATE_SOURCE_INCOMPLETE_3_CANDIDATES": 2,
    "MULTI_CANDIDATE_VALUE_CONFLICT": 14,
    "SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_2": 12,
    "SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_3": 71,
    "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_0": 550,
    "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_1": 421,
    "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_2": 119,
    "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3": 21,
}
EXPECTED_PRIORITY_COUNTS = {
    "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT": 21,
    "P1_IDENTITY_CONFLICT_TIER2_3": 71,
    "P2_SAFE_PARTIAL_TIER2_2": 119,
    "P3_IDENTITY_CONFLICT_LOWER_EVIDENCE": 12,
    "P3_SAFE_PARTIAL_TIER2_1": 421,
    "P3_SOURCE_COMPLETENESS_REVIEW": 87,
    "P4_ISSUER_AUTHORITY_REVIEW": 83,
    "P4_SAFE_PARTIAL_TIER2_0": 550,
    "P4_SOURCE_VALUE_CONFLICT_REVIEW": 14,
}

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
MIGRATION_FIELDS = [
    "announcement_id",
    "migration_status",
    "previous_residual_class",
    "current_residual_class",
    "previous_priority_class",
    "current_priority_class",
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


def deterministic_csv_gz(
    path: Path, rows: list[dict[str, str]], fields: list[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
        ) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(
                    text, fieldnames=fields, lineterminator="\n"
                )
                writer.writeheader()
                writer.writerows(rows)


def normalize_validation_errors(candidate: dict) -> list[str]:
    return [str(value) for value in (candidate.get("validation_errors") or [])]


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
) -> dict[str, str]:
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


def read_previous_ledger(path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"announcement_id", "residual_class", "priority_class"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"previous ledger missing columns {sorted(missing)}")
        for row in reader:
            aid = row["announcement_id"]
            if aid in rows:
                raise ValueError(f"duplicate previous residual {aid}")
            rows[aid] = row
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", required=True)
    parser.add_argument("--previous-ledger", required=True)
    parser.add_argument("--out-root", required=True)
    args = parser.parse_args()

    documents = Path(args.documents)
    previous_ledger = Path(args.previous_ledger)
    if sha256_file(documents) != SOURCE_DOCUMENTS_GZIP_SHA256:
        raise ValueError("V17.26 document gzip SHA mismatch")
    if sha256_gzip_plaintext(documents) != SOURCE_DOCUMENTS_PLAINTEXT_SHA256:
        raise ValueError("V17.26 document plaintext SHA mismatch")
    if sha256_file(previous_ledger) != PREVIOUS_LEDGER_GZIP_SHA256:
        raise ValueError("previous classifier ledger gzip SHA mismatch")
    if sha256_gzip_plaintext(previous_ledger) != PREVIOUS_LEDGER_PLAINTEXT_SHA256:
        raise ValueError("previous classifier ledger plaintext SHA mismatch")

    previous = read_previous_ledger(previous_ledger)
    residuals: list[dict[str, str]] = []
    current_by_id: dict[str, dict[str, str]] = {}
    input_rows = 0
    pass_rows = 0
    with gzip.open(documents, "rt", encoding="utf-8", newline="") as handle:
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
            output = build_output_row(row, candidates, residual_class, priority)
            aid = output["announcement_id"]
            if aid in current_by_id:
                raise ValueError(f"duplicate current residual {aid}")
            current_by_id[aid] = output
            residuals.append(output)

    residuals.sort(
        key=lambda row: (
            row["priority_class"],
            row["residual_class"],
            row["economic_date"],
            row["announcement_id"],
        )
    )
    class_counts = Counter(row["residual_class"] for row in residuals)
    priority_counts = Counter(row["priority_class"] for row in residuals)
    family_counts: dict[str, Counter] = defaultdict(Counter)
    for row in residuals:
        family_counts[row["residual_class"]][row["report_family"]] += 1

    if dict(sorted(class_counts.items())) != EXPECTED_CLASS_COUNTS:
        raise ValueError(
            "V17.26 residual class counts changed "
            f"actual={dict(sorted(class_counts.items()))}"
        )
    if dict(sorted(priority_counts.items())) != EXPECTED_PRIORITY_COUNTS:
        raise ValueError(
            "V17.26 residual priority counts changed "
            f"actual={dict(sorted(priority_counts.items()))}"
        )
    if input_rows != 121354 or pass_rows != 119976 or len(residuals) != 1378:
        raise ValueError(
            f"V17.26 accounting changed input={input_rows} "
            f"pass={pass_rows} residuals={len(residuals)}"
        )
    if len(previous) != 1380:
        raise ValueError(f"previous residual count changed {len(previous)}")

    previous_ids = set(previous)
    current_ids = set(current_by_id)
    removed = sorted(previous_ids - current_ids)
    added = sorted(current_ids - previous_ids)
    if removed != list(RECOVERED_EXIT_IDS):
        raise ValueError(f"unexpected recovered residual exits {removed}")
    if added:
        raise ValueError(f"unexpected new residuals {added}")

    migration_rows: list[dict[str, str]] = []
    reclassified: list[str] = []
    for aid in sorted(previous_ids | current_ids):
        old = previous.get(aid)
        new = current_by_id.get(aid)
        if old is not None and new is None:
            status = "RECOVERED_EXITED_RESIDUAL"
        elif old is None and new is not None:
            status = "NEW_RESIDUAL"
        else:
            assert old is not None and new is not None
            unchanged = (
                old["residual_class"] == new["residual_class"]
                and old["priority_class"] == new["priority_class"]
            )
            status = "UNCHANGED" if unchanged else "RECLASSIFIED"
            if not unchanged:
                reclassified.append(aid)
        migration_rows.append(
            {
                "announcement_id": aid,
                "migration_status": status,
                "previous_residual_class": "" if old is None else old["residual_class"],
                "current_residual_class": "" if new is None else new["residual_class"],
                "previous_priority_class": "" if old is None else old["priority_class"],
                "current_priority_class": "" if new is None else new["priority_class"],
            }
        )
    migration_counts = Counter(row["migration_status"] for row in migration_rows)
    if dict(sorted(migration_counts.items())) != {
        "RECOVERED_EXITED_RESIDUAL": 2,
        "UNCHANGED": 1378,
    }:
        raise ValueError(f"migration counts changed {dict(migration_counts)}")
    if reclassified:
        raise ValueError(f"common residuals reclassified {reclassified[:20]}")
    for aid in RECOVERED_EXIT_IDS:
        old = previous[aid]
        if (
            old["residual_class"]
            != "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3"
            or old["priority_class"]
            != "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT"
        ):
            raise ValueError(f"recovered residual source class changed {aid}")

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    ledger_path = out_root / "s3g1j_v17_26_residual_classification.csv.gz"
    p0_path = out_root / "s3g1j_v17_26_p0_safe_near_complete.csv.gz"
    migration_path = out_root / "s3g1j_v17_21_to_v17_26_residual_migration.csv.gz"
    deterministic_csv_gz(ledger_path, residuals, OUTPUT_FIELDS)
    deterministic_csv_gz(
        p0_path,
        [
            row
            for row in residuals
            if row["priority_class"]
            == "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT"
        ],
        OUTPUT_FIELDS,
    )
    deterministic_csv_gz(migration_path, migration_rows, MIGRATION_FIELDS)

    summary = {
        "gate": "S3G1J_V17_26_FULL_BASIS_RESIDUAL_CLASSIFICATION_V2",
        "source_run": SOURCE_RUN,
        "source_artifact": SOURCE_ARTIFACT,
        "source_artifact_digest": SOURCE_ARTIFACT_DIGEST,
        "source_documents_gzip_sha256": SOURCE_DOCUMENTS_GZIP_SHA256,
        "source_documents_plaintext_sha256": SOURCE_DOCUMENTS_PLAINTEXT_SHA256,
        "previous_classifier_run": PREVIOUS_CLASSIFIER_RUN,
        "previous_classifier_artifact": PREVIOUS_CLASSIFIER_ARTIFACT,
        "previous_classifier_artifact_digest": PREVIOUS_CLASSIFIER_ARTIFACT_DIGEST,
        "previous_ledger_gzip_sha256": PREVIOUS_LEDGER_GZIP_SHA256,
        "previous_ledger_plaintext_sha256": PREVIOUS_LEDGER_PLAINTEXT_SHA256,
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
        "migration_counts": dict(sorted(migration_counts.items())),
        "recovered_exit_announcement_ids": removed,
        "common_residual_reclassification_count": len(reclassified),
        "new_residual_count": len(added),
        "classification_ledger_sha256": sha256_gzip_plaintext(ledger_path),
        "classification_ledger_gzip_sha256": sha256_file(ledger_path),
        "p0_ledger_sha256": sha256_gzip_plaintext(p0_path),
        "p0_ledger_gzip_sha256": sha256_file(p0_path),
        "migration_ledger_sha256": sha256_gzip_plaintext(migration_path),
        "migration_ledger_gzip_sha256": sha256_file(migration_path),
        "gzip_mtime": 0,
        "gzip_embedded_filename": "",
        "production_data_changed": False,
        "parser_changed": False,
        "runtime_authority_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_locked": True,
        "pass": True,
        "errors": [],
    }
    expected_hashes = {
        "classification_ledger_sha256": "d685467918213b5b5b333dd7f893d633aebce9dd0d7d738082241e74a3519009",
        "classification_ledger_gzip_sha256": "e39fdc8dea8639bf00d56f80a00cfba842c6194a787736bdcf40b2ab1accea89",
        "p0_ledger_sha256": "3500694439fc4573b1546c001b647ecb0bee6804691df8306727255debbeef49",
        "p0_ledger_gzip_sha256": "75f41b4576fc843b93bca6ac98f12a12e72475daaa0f00473e2a6edae5fdcf90",
        "migration_ledger_sha256": "275e8a25490d324bfe69e76e9945f5193199697f5661e3555aa3ed8c305319f4",
        "migration_ledger_gzip_sha256": "88fc642649f2c6448edcc9d5b8ae09753042b4b5086b43ca9af8677aabf7aa38",
    }
    for key, expected in expected_hashes.items():
        if summary[key] != expected:
            raise ValueError(f"deterministic output hash changed {key}")

    summary_path = out_root / "s3g1j_v17_26_residual_classification_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
