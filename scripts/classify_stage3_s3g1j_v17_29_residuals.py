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

SOURCE_RUN = 31389854868
SOURCE_HEAD = "22fa37064eeb8a49ad5292dd2be48bd7b674c673"
SOURCE_ARTIFACT_ID = 9063271903
SOURCE_ARTIFACT = "stage3-s3g1j-v17-29-full-final"
SOURCE_ARTIFACT_DIGEST = "sha256:71a4daa6c8372f3d64080b5fa5b787914292d889da7051de699eb6610189c726"
SOURCE_DOCUMENTS_GZIP_SHA256 = "644bccd1a984fdbc002a139f8ced0313a8cf749124a178e7ace7965472f395af"
SOURCE_DOCUMENTS_PLAINTEXT_SHA256 = "11ecdb2660b22e40d6134cd1b55caaacd18a69af89725b9c6ff0427b083171d4"

PREVIOUS_CLASSIFIER_RUN = 31022605702
PREVIOUS_CLASSIFIER_HEAD = "b997f7b91cb2a5fcbb5d8473f428effd26ed5bf0"
PREVIOUS_CLASSIFIER_ARTIFACT_ID = 8937238672
PREVIOUS_CLASSIFIER_ARTIFACT = "stage3-s3g1j-v17-28-residual-classification-v1"
PREVIOUS_CLASSIFIER_ARTIFACT_DIGEST = "sha256:2c54496b329b719c09f299fe0c2d61ece4b05a0c8859b4a39441012abfb248ad"
PREVIOUS_LEDGER_GZIP_SHA256 = "d1d1c40cf242e93f0a5c8f18eb7335b15238bbf780429cd3e086eb7efe0765cc"
PREVIOUS_LEDGER_PLAINTEXT_SHA256 = "ad4a2372742c653672411194fdda476eae2076c6221f103d14bb9614788c088d"

RECOVERED_EXIT_IDS = (
    "1215186538", "1219426855", "1219792633", "1219840508",
    "1219879687", "1220087244", "1221006100",
)
EXPECTED_P0_IDS = (
    "1202799494", "1204077386", "1205543437", "1209806910",
    "1219834247", "1223347318", "1223407043",
)
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
    "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3": 7,
}
EXPECTED_PRIORITY_COUNTS = {
    "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT": 7,
    "P1_IDENTITY_CONFLICT_TIER2_3": 71,
    "P2_SAFE_PARTIAL_TIER2_2": 119,
    "P3_IDENTITY_CONFLICT_LOWER_EVIDENCE": 12,
    "P3_SAFE_PARTIAL_TIER2_1": 421,
    "P3_SOURCE_COMPLETENESS_REVIEW": 87,
    "P4_ISSUER_AUTHORITY_REVIEW": 83,
    "P4_SAFE_PARTIAL_TIER2_0": 550,
    "P4_SOURCE_VALUE_CONFLICT_REVIEW": 14,
}
EXPECTED_TIE_TAXONOMY = {"TIE_SOURCE_INCOMPLETE": 1267, "TIE_VALUE_CONFLICT": 14}
EXPECTED_OUTPUT_HASHES = {
    "classification_ledger_sha256": "31be1e40330be6b149e4eb630339131258b4212d1639e13bead207feae50afe5",
    "classification_ledger_gzip_sha256": "33744dad2c9d4f160f5f40be4486f703bdeda85c9b2510714874413f450864da",
    "p0_ledger_sha256": "6c5866e3fdbf6381bb0b982b8642aa9c4d5ce9833469a97bcceda6dbea1d5633",
    "p0_ledger_gzip_sha256": "80df0e1ac6ca908e3c4d489edeffdc25a3a3a6c408144e9558bbfbbdf029cbb2",
    "migration_ledger_sha256": "c63b792afc9e3a29c073fa284ba5e7c4059426c16d40c4855bc39c904f29abe4",
    "migration_ledger_gzip_sha256": "5de74df4b0c5e03e4c5b9da2713daa8795b390970634d8e1087e9e5cab757e61",
}

OUTPUT_FIELDS = [
    "exchange", "source_code", "effective_code", "issuer_org_id", "report_family",
    "economic_date", "announcement_id", "revision_sequence", "source_published_at",
    "effective_session", "available_at", "canonical_title", "canonical_source_url",
    "selected_source_url", "selected_source_sha256", "tie_candidate_count",
    "tie_resolution", "candidate_count_actual", "candidate_ids", "candidate_errors",
    "candidate_validation_errors", "candidate_tier1_counts", "candidate_tier2_counts",
    "candidate_page_counts", "document_error", "residual_class", "priority_class",
]
MIGRATION_FIELDS = [
    "announcement_id", "migration_status", "previous_residual_class",
    "current_residual_class", "previous_priority_class", "current_priority_class",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_gzip_plaintext(path: Path) -> str:
    h = hashlib.sha256()
    with gzip.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def deterministic_csv_gz(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
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
        joined = " | ".join(normalize_validation_errors(candidate))
        if IDENTITY in joined:
            priority = "P1_IDENTITY_CONFLICT_TIER2_3" if tier2 == 3 else "P3_IDENTITY_CONFLICT_LOWER_EVIDENCE"
            return f"SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_{tier2}", priority
        if NO_BLOCK not in joined:
            raise ValueError(f"single canonical candidate has unknown validation errors announcement={row.get('announcement_id')} errors={joined}")
        priority = {
            3: "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT",
            2: "P2_SAFE_PARTIAL_TIER2_2",
            1: "P3_SAFE_PARTIAL_TIER2_1",
            0: "P4_SAFE_PARTIAL_TIER2_0",
        }.get(tier2)
        if priority is None:
            raise ValueError(f"unexpected tier2 count announcement={row.get('announcement_id')} tier2={tier2}")
        return f"SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_{tier2}", priority
    if actual < 2:
        raise ValueError(f"empty candidate evidence announcement={row.get('announcement_id')}")
    if tie_resolution == "TIE_VALUE_CONFLICT":
        return "MULTI_CANDIDATE_VALUE_CONFLICT", "P4_SOURCE_VALUE_CONFLICT_REVIEW"
    if tie_resolution == "TIE_SOURCE_INCOMPLETE":
        return f"MULTI_CANDIDATE_SOURCE_INCOMPLETE_{actual}_CANDIDATES", "P3_SOURCE_COMPLETENESS_REVIEW"
    raise ValueError(f"unknown multi-candidate resolution announcement={row.get('announcement_id')} resolution={tie_resolution!r}")


def build_output_row(row: dict, candidates: list[dict], residual_class: str, priority: str) -> dict[str, str]:
    compact = (",", ":")
    return {
        "exchange": row.get("exchange", ""), "source_code": row.get("source_code", ""),
        "effective_code": row.get("effective_code", ""), "issuer_org_id": row.get("issuer_org_id", ""),
        "report_family": row.get("report_family", ""), "economic_date": row.get("economic_date", ""),
        "announcement_id": row.get("announcement_id", ""), "revision_sequence": row.get("revision_sequence", ""),
        "source_published_at": row.get("source_published_at", ""), "effective_session": row.get("effective_session", ""),
        "available_at": row.get("available_at", ""), "canonical_title": row.get("canonical_title", ""),
        "canonical_source_url": row.get("canonical_source_url", ""), "selected_source_url": row.get("selected_source_url", ""),
        "selected_source_sha256": row.get("selected_source_sha256", ""), "tie_candidate_count": row.get("tie_candidate_count", ""),
        "tie_resolution": row.get("tie_resolution", ""), "candidate_count_actual": str(len(candidates)),
        "candidate_ids": json.dumps([str(x.get("id") or "") for x in candidates], ensure_ascii=False, separators=compact),
        "candidate_errors": json.dumps([str(x.get("error") or "") for x in candidates], ensure_ascii=False, separators=compact),
        "candidate_validation_errors": json.dumps([normalize_validation_errors(x) for x in candidates], ensure_ascii=False, separators=compact),
        "candidate_tier1_counts": json.dumps([int(x.get("tier1_found") or 0) for x in candidates], separators=compact),
        "candidate_tier2_counts": json.dumps([int(x.get("tier2_found") or 0) for x in candidates], separators=compact),
        "candidate_page_counts": json.dumps([int(x.get("page_count") or 0) for x in candidates], separators=compact),
        "document_error": row.get("document_error", ""), "residual_class": residual_class, "priority_class": priority,
    }


def read_previous_ledger(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"announcement_id", "residual_class", "priority_class"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"previous ledger missing columns {sorted(missing)}")
        for row in reader:
            aid = row["announcement_id"]
            if aid in out:
                raise ValueError(f"duplicate previous residual {aid}")
            out[aid] = row
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--documents", required=True)
    ap.add_argument("--previous-ledger", required=True)
    ap.add_argument("--out-root", required=True)
    args = ap.parse_args()
    documents = Path(args.documents)
    previous_ledger = Path(args.previous_ledger)
    out_root = Path(args.out_root)

    if sha256_file(documents) != SOURCE_DOCUMENTS_GZIP_SHA256:
        raise ValueError("V17.29 document gzip SHA mismatch")
    if sha256_gzip_plaintext(documents) != SOURCE_DOCUMENTS_PLAINTEXT_SHA256:
        raise ValueError("V17.29 document plaintext SHA mismatch")
    if sha256_file(previous_ledger) != PREVIOUS_LEDGER_GZIP_SHA256:
        raise ValueError("V17.28 previous classification ledger gzip SHA mismatch")
    if sha256_gzip_plaintext(previous_ledger) != PREVIOUS_LEDGER_PLAINTEXT_SHA256:
        raise ValueError("V17.28 previous classification ledger plaintext SHA mismatch")

    previous = read_previous_ledger(previous_ledger)
    residuals: list[dict[str, str]] = []
    current_by_id: dict[str, dict[str, str]] = {}
    tie_taxonomy: Counter[str] = Counter()
    input_rows = pass_rows = 0
    with gzip.open(documents, "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"announcement_id", "candidate_evidence_json", "document_status", "document_error", "tie_candidate_count", "tie_resolution"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"missing document columns {sorted(missing)}")
        for row in reader:
            input_rows += 1
            if row.get("document_status") != "ERROR":
                pass_rows += 1
                continue
            tie_taxonomy[row.get("tie_resolution", "")] += 1
            candidates = json.loads(row.get("candidate_evidence_json") or "[]")
            if int(row.get("tie_candidate_count") or 0) != len(candidates):
                raise ValueError(f"candidate count mismatch announcement={row.get('announcement_id')}")
            residual_class, priority = classify(row, candidates)
            output = build_output_row(row, candidates, residual_class, priority)
            aid = output["announcement_id"]
            if aid in current_by_id:
                raise ValueError(f"duplicate current residual {aid}")
            current_by_id[aid] = output
            residuals.append(output)

    residuals.sort(key=lambda row: (row["priority_class"], row["residual_class"], row["economic_date"], row["announcement_id"]))
    class_counts = Counter(row["residual_class"] for row in residuals)
    priority_counts = Counter(row["priority_class"] for row in residuals)
    family_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in residuals:
        family_counts[row["residual_class"]][row["report_family"]] += 1

    if dict(sorted(class_counts.items())) != EXPECTED_CLASS_COUNTS:
        raise ValueError(f"V17.29 residual class counts changed {dict(sorted(class_counts.items()))}")
    if dict(sorted(priority_counts.items())) != EXPECTED_PRIORITY_COUNTS:
        raise ValueError(f"V17.29 priority counts changed {dict(sorted(priority_counts.items()))}")
    actual_ties = {"TIE_SOURCE_INCOMPLETE": tie_taxonomy["TIE_SOURCE_INCOMPLETE"], "TIE_VALUE_CONFLICT": tie_taxonomy["TIE_VALUE_CONFLICT"]}
    if actual_ties != EXPECTED_TIE_TAXONOMY:
        raise ValueError(f"V17.29 unresolved tie taxonomy changed {actual_ties}")
    if input_rows != 121354 or pass_rows != 119990 or len(residuals) != 1364:
        raise ValueError(f"V17.29 accounting changed input={input_rows} pass={pass_rows} residuals={len(residuals)}")
    if len(previous) != 1371:
        raise ValueError(f"V17.28 previous residual count changed {len(previous)}")

    previous_ids, current_ids = set(previous), set(current_by_id)
    removed, added = sorted(previous_ids - current_ids), sorted(current_ids - previous_ids)
    if removed != list(RECOVERED_EXIT_IDS):
        raise ValueError(f"unexpected recovered exits {removed}")
    if added:
        raise ValueError(f"unexpected new residuals {added}")

    migration_rows: list[dict[str, str]] = []
    reclassified: list[str] = []
    for aid in sorted(previous_ids | current_ids):
        old, new = previous.get(aid), current_by_id.get(aid)
        if old is not None and new is None:
            status = "RECOVERED_EXITED_RESIDUAL"
        elif old is None and new is not None:
            status = "NEW_RESIDUAL"
        else:
            assert old is not None and new is not None
            if old["residual_class"] == new["residual_class"] and old["priority_class"] == new["priority_class"]:
                status = "UNCHANGED"
            else:
                status = "RECLASSIFIED"
                reclassified.append(aid)
        migration_rows.append({
            "announcement_id": aid, "migration_status": status,
            "previous_residual_class": old["residual_class"] if old else "",
            "current_residual_class": new["residual_class"] if new else "",
            "previous_priority_class": old["priority_class"] if old else "",
            "current_priority_class": new["priority_class"] if new else "",
        })
    if reclassified:
        raise ValueError(f"unexpected common residual reclassification {reclassified}")

    p0_rows = [row for row in residuals if row["priority_class"] == "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT"]
    p0_ids = sorted(row["announcement_id"] for row in p0_rows)
    if p0_ids != list(EXPECTED_P0_IDS):
        raise ValueError(f"V17.29 P0 identity set changed {p0_ids}")

    classification_path = out_root / "s3g1j_v17_29_residual_classification.csv.gz"
    p0_path = out_root / "s3g1j_v17_29_p0_safe_near_complete.csv.gz"
    migration_path = out_root / "s3g1j_v17_28_to_v17_29_residual_migration.csv.gz"
    deterministic_csv_gz(classification_path, residuals, OUTPUT_FIELDS)
    deterministic_csv_gz(p0_path, p0_rows, OUTPUT_FIELDS)
    deterministic_csv_gz(migration_path, migration_rows, MIGRATION_FIELDS)
    output_hashes = {
        "classification_ledger_sha256": sha256_gzip_plaintext(classification_path),
        "classification_ledger_gzip_sha256": sha256_file(classification_path),
        "p0_ledger_sha256": sha256_gzip_plaintext(p0_path),
        "p0_ledger_gzip_sha256": sha256_file(p0_path),
        "migration_ledger_sha256": sha256_gzip_plaintext(migration_path),
        "migration_ledger_gzip_sha256": sha256_file(migration_path),
    }
    if output_hashes != EXPECTED_OUTPUT_HASHES:
        raise ValueError(f"deterministic output hash drift {output_hashes}")

    summary = {
        "gate": "S3G1J_V17_29_FULL_BASIS_RESIDUAL_CLASSIFICATION_V1",
        "source_run": SOURCE_RUN, "source_head": SOURCE_HEAD,
        "source_artifact_id": SOURCE_ARTIFACT_ID, "source_artifact": SOURCE_ARTIFACT,
        "source_artifact_digest": SOURCE_ARTIFACT_DIGEST,
        "source_documents_gzip_sha256": SOURCE_DOCUMENTS_GZIP_SHA256,
        "source_documents_plaintext_sha256": SOURCE_DOCUMENTS_PLAINTEXT_SHA256,
        "previous_classifier_run": PREVIOUS_CLASSIFIER_RUN,
        "previous_classifier_head": PREVIOUS_CLASSIFIER_HEAD,
        "previous_classifier_artifact_id": PREVIOUS_CLASSIFIER_ARTIFACT_ID,
        "previous_classifier_artifact": PREVIOUS_CLASSIFIER_ARTIFACT,
        "previous_classifier_artifact_digest": PREVIOUS_CLASSIFIER_ARTIFACT_DIGEST,
        "previous_ledger_gzip_sha256": PREVIOUS_LEDGER_GZIP_SHA256,
        "previous_ledger_plaintext_sha256": PREVIOUS_LEDGER_PLAINTEXT_SHA256,
        "input_document_rows": input_rows, "pass_document_rows": pass_rows,
        "residual_document_rows": len(residuals),
        "class_counts": dict(sorted(class_counts.items())),
        "priority_counts": dict(sorted(priority_counts.items())),
        "report_family_counts_by_class": {key: dict(sorted(value.items())) for key, value in sorted(family_counts.items())},
        "p0_safe_near_complete_count": len(p0_rows), "p0_announcement_ids": p0_ids,
        "tie_taxonomy": actual_ties,
        "migration_counts": dict(sorted(Counter(row["migration_status"] for row in migration_rows).items())),
        "recovered_exit_announcement_ids": removed,
        "common_residual_reclassification_count": len(reclassified), "new_residual_count": len(added),
        **output_hashes,
        "gzip_mtime": 0, "gzip_embedded_filename": "",
        "production_data_changed": False, "parser_changed": False, "runtime_authority_changed": False,
        "stage3_status": "NOT_READY", "stage4_alpha_locked": True, "pass": True, "errors": [],
    }
    (out_root / "s3g1j_v17_29_residual_classification_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
