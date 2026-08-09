#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import time
from collections import Counter
from pathlib import Path

import requests

import stage3_financial_pdf_parser_v21_production_candidate as production

SOURCE_DOCUMENTS_SHA256 = "7589750684ec26280c095d4b3a2d21b114c6bb77a882f4633c2ea128de5f38f3"
SOURCE_VALUES_SHA256 = "2c6e6255be58e86a0b24b889a67e8dccb43835eb9770ca690dde7429b477bbf7"
CANDIDATE_DOCUMENTS_SHA256 = "343ef55dc8bcf0eb53e8eda2d77f58ddfc48c5c6d13011d02a12d00bd836179e"
CANDIDATE_VALUES_SHA256 = "31479f232fa2708b411730aa0e0513892a0e42359f0a0e80f4325af3f8b9de2a"
SOURCE_DOCUMENT_ROWS = 121354
SOURCE_NUMERIC_ROWS = 1051799
PROMOTION_DOCUMENT_ROWS = 121354
PROMOTION_NUMERIC_ROWS = 1051820
SOURCE_ERRORS = 1371
PROMOTION_ERRORS = 1364
SOURCE_TIES = 1288
PROMOTION_TIES = 1281
TARGET_IDS = tuple(sorted(target["announcement_id"] for target in production.TARGETS.values()))
TARGETS_BY_AID = {
    target["announcement_id"]: {"source_sha256": digest, **target}
    for digest, target in production.TARGETS.items()
}
CANDIDATE_METHOD = "V17_29_EXACT_SOURCE_SPLIT_GROUP_EQUITY_CANDIDATE_V2"
DOC_ALLOWED_PROMOTION_FIELDS = {"candidate_evidence_json"}
VALUE_ALLOWED_PROMOTION_FIELDS = {"extraction_method", "methodology_version"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_gz(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_gz(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    raw = buf.getvalue().encode("utf-8")
    with path.open("wb") as handle:
        with gzip.GzipFile(fileobj=handle, mode="wb", mtime=0, filename="") as gz:
            gz.write(raw)


def counter(rows: list[dict[str, str]], fields: list[str]) -> Counter[tuple[str, ...]]:
    return Counter(tuple(row.get(field, "") for field in fields) for row in rows)


def projection(row: dict[str, str], fields: list[str], excluded: set[str]) -> tuple[str, ...]:
    return tuple(row.get(field, "") for field in fields if field not in excluded)


def semantic_sha(rows: list[dict[str, str]], fields: list[str], excluded: set[str] | None = None) -> str:
    excluded = excluded or set()
    projected = Counter(projection(row, fields, excluded) for row in rows)
    h = hashlib.sha256()
    for key, count in sorted(projected.items()):
        h.update(json.dumps([list(key), count], ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def tie_taxonomy(rows: list[dict[str, str]]) -> dict[str, int]:
    counts = Counter(row.get("tie_resolution", "") for row in rows)
    return {
        "TIE_SOURCE_INCOMPLETE": counts["TIE_SOURCE_INCOMPLETE"],
        "TIE_VALUE_CONFLICT": counts["TIE_VALUE_CONFLICT"],
    }


def download(session: requests.Session, target: dict) -> bytes:
    last: Exception | None = None
    for attempt in range(1, 7):
        try:
            response = session.get(target["source_url"], timeout=(30, 180))
            response.raise_for_status()
            raw = response.content
            if not raw.startswith(b"%PDF"):
                raise ValueError("not PDF")
            digest = hashlib.sha256(raw).hexdigest()
            if digest != target["source_sha256"] or len(raw) != int(target["source_bytes"]):
                raise ValueError("source identity mismatch")
            return raw
        except Exception as exc:
            last = exc
            if attempt < 6:
                time.sleep(attempt * 5)
    raise RuntimeError(f"download failed {target['announcement_id']}: {last}")


def candidate_added_values(candidate_values: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = [
        row for row in candidate_values
        if row.get("announcement_id") in TARGET_IDS
        and row.get("extraction_method") == CANDIDATE_METHOD
        and row.get("concept") in production.ALLOWED_CONCEPTS
    ]
    if len(rows) != 21:
        raise ValueError(f"accepted candidate target numeric count={len(rows)}")
    return sorted(rows, key=lambda row: (row["announcement_id"], row["concept"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-documents", required=True)
    parser.add_argument("--source-values", required=True)
    parser.add_argument("--candidate-documents", required=True)
    parser.add_argument("--candidate-values", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    source_documents_path = Path(args.source_documents)
    source_values_path = Path(args.source_values)
    candidate_documents_path = Path(args.candidate_documents)
    candidate_values_path = Path(args.candidate_values)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    expected_hashes = {
        source_documents_path: SOURCE_DOCUMENTS_SHA256,
        source_values_path: SOURCE_VALUES_SHA256,
        candidate_documents_path: CANDIDATE_DOCUMENTS_SHA256,
        candidate_values_path: CANDIDATE_VALUES_SHA256,
    }
    for path, expected in expected_hashes.items():
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"input hash mismatch {path.name}: {actual}")

    doc_fields, source_docs = read_gz(source_documents_path)
    value_fields, source_values = read_gz(source_values_path)
    candidate_doc_fields, candidate_docs = read_gz(candidate_documents_path)
    candidate_value_fields, candidate_values = read_gz(candidate_values_path)
    if doc_fields != candidate_doc_fields or value_fields != candidate_value_fields:
        raise ValueError("accepted candidate schema drift")
    if len(source_docs) != SOURCE_DOCUMENT_ROWS or len(source_values) != SOURCE_NUMERIC_ROWS:
        raise ValueError("source population mismatch")
    if len(candidate_docs) != PROMOTION_DOCUMENT_ROWS or len(candidate_values) != PROMOTION_NUMERIC_ROWS:
        raise ValueError("accepted candidate population mismatch")

    source_by_aid = {row["announcement_id"]: row for row in source_docs}
    candidate_by_aid = {row["announcement_id"]: row for row in candidate_docs}
    candidate_added = candidate_added_values(candidate_values)
    candidate_added_by_key = {
        (row["announcement_id"], row["concept"]): row for row in candidate_added
    }

    session = requests.Session()
    promotion_docs: list[dict[str, str]] = []
    promotion_added: list[dict[str, str]] = []
    target_reports: list[dict] = []

    for source_row in source_docs:
        aid = source_row["announcement_id"]
        if aid not in TARGETS_BY_AID:
            promotion_docs.append(dict(source_row))
            continue

        target = TARGETS_BY_AID[aid]
        candidate_row = candidate_by_aid[aid]
        raw = download(session, target)
        parsed = production.parse_pdf_bytes(raw, target["economic_date"])
        if parsed.get("parser_version") != production.METHOD:
            raise ValueError(f"{aid} production experiment parser identity failed")
        if parsed.get("validation_errors"):
            raise ValueError(f"{aid} production experiment validation errors")
        block = parsed.get("balance_sheet_block") or {}
        if block.get("production_promotion_experiment_only") is not True:
            raise ValueError(f"{aid} experiment marker missing")
        if block.get("runtime_promotion_authorized") is not False:
            raise ValueError(f"{aid} runtime promotion boundary changed")
        if block.get("exact_source_sha256") != target["source_sha256"]:
            raise ValueError(f"{aid} source binding changed")
        if block.get("split_equity_pattern") != "SPLIT_LABEL_1_BEFORE_1_AFTER_AMOUNT":
            raise ValueError(f"{aid} split pattern changed")
        if block.get("equity_value_inferred_as_assets_minus_liabilities") is not False:
            raise ValueError(f"{aid} equity inference enabled")
        if block.get("ocr_enabled") is not False or block.get("fuzzy_alias_matching_enabled") is not False:
            raise ValueError(f"{aid} prohibited extraction relaxation")
        identity = (block.get("dual_column_identity") or {}).get("columns") or []
        if len(identity) != 2 or any(str(row.get("identity_residual_cny")) != "0.00" for row in identity):
            raise ValueError(f"{aid} identity residual drift")

        observations = parsed.get("observations") or {}
        for concept in production.ALLOWED_CONCEPTS:
            observation = observations.get(concept) or {}
            accepted_row = candidate_added_by_key[(aid, concept)]
            if observation.get("status") != "FOUND":
                raise ValueError(f"{aid} {concept} not found")
            if str(observation.get("normalized_cny_value")) != accepted_row["normalized_cny_value"]:
                raise ValueError(f"{aid} {concept} value differs from accepted candidate")
            if str(observation.get("page")) != accepted_row["page"]:
                raise ValueError(f"{aid} {concept} page differs from accepted candidate")
            if str(observation.get("matched_alias")) != accepted_row["matched_alias"]:
                raise ValueError(f"{aid} {concept} alias differs from accepted candidate")
            promoted = dict(accepted_row)
            promoted["extraction_method"] = production.METHOD
            promoted["methodology_version"] = production.METHODOLOGY_VERSION
            promotion_added.append(promoted)

        promoted_doc = dict(candidate_row)
        evidence = json.loads(promoted_doc["candidate_evidence_json"])
        if not isinstance(evidence, list) or len(evidence) != 1:
            raise ValueError(f"{aid} candidate evidence population changed")
        ev = dict(evidence[0])
        ev.update({
            "parser_version": production.METHOD,
            "candidate_only": False,
            "production_promotion_experiment_only": True,
            "runtime_promotion_authorized": False,
            "accepted_candidate_run": production.ACCEPTED_CANDIDATE_RUN,
            "accepted_candidate_artifact_id": production.ACCEPTED_CANDIDATE_ARTIFACT_ID,
        })
        promoted_doc["candidate_evidence_json"] = json.dumps([ev], ensure_ascii=False, separators=(",", ":"))
        promotion_docs.append(promoted_doc)
        target_reports.append({
            "announcement_id": aid,
            "source_sha256": target["source_sha256"],
            "economic_date": target["economic_date"],
            "selected_pages": block["selected_pages"],
            "split_equity_pattern": block["split_equity_pattern"],
            "identity": block["dual_column_identity"],
        })

    promotion_added.sort(key=lambda row: (row["announcement_id"], row["concept"]))
    promotion_values = source_values + promotion_added
    if len(promotion_docs) != PROMOTION_DOCUMENT_ROWS or len(promotion_values) != PROMOTION_NUMERIC_ROWS:
        raise ValueError("promotion population mismatch")

    source_non = [row for row in source_docs if row["announcement_id"] not in TARGET_IDS]
    promotion_non = [row for row in promotion_docs if row["announcement_id"] not in TARGET_IDS]
    non_target_docs_exact = counter(source_non, doc_fields) == counter(promotion_non, doc_fields)
    existing_numeric_exact = counter(source_values, value_fields) == counter(
        promotion_values[:SOURCE_NUMERIC_ROWS], value_fields
    )

    candidate_target_docs = [candidate_by_aid[aid] for aid in TARGET_IDS]
    promotion_target_docs = [
        next(row for row in promotion_docs if row["announcement_id"] == aid)
        for aid in TARGET_IDS
    ]
    candidate_target_doc_semantic = Counter(
        projection(row, doc_fields, DOC_ALLOWED_PROMOTION_FIELDS)
        for row in candidate_target_docs
    )
    promotion_target_doc_semantic = Counter(
        projection(row, doc_fields, DOC_ALLOWED_PROMOTION_FIELDS)
        for row in promotion_target_docs
    )
    target_doc_semantic_equal = candidate_target_doc_semantic == promotion_target_doc_semantic

    candidate_target_value_semantic = Counter(
        projection(row, value_fields, VALUE_ALLOWED_PROMOTION_FIELDS)
        for row in candidate_added
    )
    promotion_target_value_semantic = Counter(
        projection(row, value_fields, VALUE_ALLOWED_PROMOTION_FIELDS)
        for row in promotion_added
    )
    target_value_semantic_equal = (
        candidate_target_value_semantic == promotion_target_value_semantic
    )

    source_taxonomy = tie_taxonomy(source_docs)
    promotion_taxonomy = tie_taxonomy(promotion_docs)
    source_errors = sum(row["document_status"] == "ERROR" for row in source_docs)
    promotion_errors = sum(row["document_status"] == "ERROR" for row in promotion_docs)
    source_ties = sum(source_taxonomy.values())
    promotion_ties = sum(promotion_taxonomy.values())

    if source_errors != SOURCE_ERRORS or promotion_errors != PROMOTION_ERRORS:
        raise ValueError(f"document error count mismatch {source_errors}->{promotion_errors}")
    if source_ties != SOURCE_TIES or promotion_ties != PROMOTION_TIES:
        raise ValueError(f"tie count mismatch {source_ties}->{promotion_ties}")
    if source_taxonomy != {"TIE_SOURCE_INCOMPLETE": 1274, "TIE_VALUE_CONFLICT": 14}:
        raise ValueError(f"source tie taxonomy mismatch {source_taxonomy}")
    if promotion_taxonomy != {"TIE_SOURCE_INCOMPLETE": 1267, "TIE_VALUE_CONFLICT": 14}:
        raise ValueError(f"promotion tie taxonomy mismatch {promotion_taxonomy}")
    if not non_target_docs_exact or not existing_numeric_exact:
        raise ValueError("non-target or existing numeric drift")
    if not target_doc_semantic_equal or not target_value_semantic_equal:
        raise ValueError("production wrapper semantic mismatch vs accepted candidate")
    if Counter(row["announcement_id"] for row in promotion_added) != Counter({aid: 3 for aid in TARGET_IDS}):
        raise ValueError("target numeric distribution mismatch")

    docs_out = out / "stage3_financial_documents_v17_29_production_promotion_safety.csv.gz"
    values_out = out / "stage3_financial_values_v17_29_production_promotion_safety.csv.gz"
    write_gz(docs_out, doc_fields, promotion_docs)
    write_gz(values_out, value_fields, promotion_values)

    report = {
        "gate": "S3G1J_V17_29_PRODUCTION_PROMOTION_SAFETY_V1",
        "production_promotion_experiment_only": True,
        "formal_runtime_generation": "V17.28",
        "proposed_runtime_generation": "V17.29",
        "accepted_candidate_run": production.ACCEPTED_CANDIDATE_RUN,
        "accepted_candidate_artifact_id": production.ACCEPTED_CANDIDATE_ARTIFACT_ID,
        "accepted_candidate_artifact_digest": production.ACCEPTED_CANDIDATE_ARTIFACT_DIGEST,
        "target_announcement_ids": list(TARGET_IDS),
        "source_document_rows": len(source_docs),
        "promotion_document_rows": len(promotion_docs),
        "source_numeric_rows": len(source_values),
        "promotion_numeric_rows": len(promotion_values),
        "source_document_errors": source_errors,
        "promotion_document_errors": promotion_errors,
        "source_unresolved_tie_taxonomy": source_taxonomy,
        "promotion_unresolved_tie_taxonomy": promotion_taxonomy,
        "source_unresolved_ties": source_ties,
        "promotion_unresolved_ties": promotion_ties,
        "non_target_document_rows": len(source_non),
        "non_target_document_exact_equal": non_target_docs_exact,
        "existing_numeric_rows": len(source_values),
        "existing_numeric_exact_equal": existing_numeric_exact,
        "candidate_target_document_semantic_equal": target_doc_semantic_equal,
        "candidate_target_numeric_semantic_equal": target_value_semantic_equal,
        "candidate_target_document_semantic_sha256": semantic_sha(candidate_target_docs, doc_fields, DOC_ALLOWED_PROMOTION_FIELDS),
        "promotion_target_document_semantic_sha256": semantic_sha(promotion_target_docs, doc_fields, DOC_ALLOWED_PROMOTION_FIELDS),
        "candidate_target_numeric_semantic_sha256": semantic_sha(candidate_added, value_fields, VALUE_ALLOWED_PROMOTION_FIELDS),
        "promotion_target_numeric_semantic_sha256": semantic_sha(promotion_added, value_fields, VALUE_ALLOWED_PROMOTION_FIELDS),
        "target_numeric_distribution": dict(sorted(Counter(row["announcement_id"] for row in promotion_added).items())),
        "target_reports": sorted(target_reports, key=lambda row: row["announcement_id"]),
        "accounting_tolerance": "0.005",
        "ocr_enabled": False,
        "e_equals_a_minus_l_inference": False,
        "fuzzy_alias_matching_enabled": False,
        "source_policy_relaxed": False,
        "point_in_time_policy_relaxed": False,
        "issuer_gate_relaxed": False,
        "formal_runtime_changed": False,
        "runtime_authority_changed": False,
        "production_data_changed": False,
        "runtime_promotion_authorized": False,
        "stage3_status": "NOT_READY",
        "final_data_verdict": "FAIL_CLOSED",
        "stage4_alpha_live_locked": True,
        "main_changed": False,
        "pass": True,
        "errors": [],
    }
    report_path = out / "stage3_s3g1j_v17_29_production_promotion_safety.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    identities = {path.name: sha256(path) for path in (docs_out, values_out, report_path)}
    (out / "output_sha256.json").write_text(
        json.dumps(identities, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "promotion_document_rows": report["promotion_document_rows"],
        "promotion_numeric_rows": report["promotion_numeric_rows"],
        "promotion_document_errors": report["promotion_document_errors"],
        "promotion_unresolved_ties": report["promotion_unresolved_ties"],
        "non_target_document_exact_equal": report["non_target_document_exact_equal"],
        "existing_numeric_exact_equal": report["existing_numeric_exact_equal"],
        "candidate_target_document_semantic_equal": report["candidate_target_document_semantic_equal"],
        "candidate_target_numeric_semantic_equal": report["candidate_target_numeric_semantic_equal"],
        "pass": report["pass"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
