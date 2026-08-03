#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import requests

import compare_stage3_s3g1j_v17_27_full_final as baseline_compare
import promote_stage3_s3g1j_v17_26_full_shards as common
import stage3_financial_pdf_parser_v20_candidate as candidate


SOURCE_DOCUMENTS_SHA256 = (
    "c2abe07baaa76efb80a30cfdd4e762ad07814f6aa795a92b9c0504f7944ab99a"
)
SOURCE_VALUES_SHA256 = (
    "4c518fbca2ece45ed535789d4cf66dd86d2717d6499f872234c5d3ece09280fe"
)
SOURCE_EXISTING_NUMERIC_SEMANTIC_SHA256 = (
    "05b914b03dbcc23d3f6eca560189afbfe6ea427913f9cf1380fa09cdea6aa8d7"
)
SOURCE_DOCUMENT_ROWS = 121354
SOURCE_NUMERIC_ROWS = 1051793
CANDIDATE_NUMERIC_ROWS = 1051799
SOURCE_ERRORS = 1373
CANDIDATE_ERRORS = 1371
SOURCE_UNRESOLVED_TIES = 1290
CANDIDATE_UNRESOLVED_TIES = 1288
TARGET_NUMERIC_ROWS = 6

TARGETS_BY_AID = {
    row["announcement_id"]: {"source_sha256": digest, **row}
    for digest, row in candidate.TARGETS.items()
}
ALLOWED_CONCEPTS = frozenset(candidate.ALLOWED_CONCEPTS)


def read_gz(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(session: requests.Session, url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(1, 7):
        try:
            response = session.get(url, timeout=(30, 180))
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise ValueError(f"download is not PDF {url}")
            return response.content
        except Exception as exc:
            last = exc
            if attempt < 6:
                time.sleep(attempt * 5)
    assert last is not None
    raise last


def canonical_rows(
    rows: list[dict[str, str]], fields: tuple[str, ...], key_fields: tuple[str, ...]
) -> list[tuple[str, ...]]:
    return sorted(tuple(row.get(field, "") for field in fields) for row in rows)


def require_exact_rows(
    label: str,
    source_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
    fields: tuple[str, ...],
) -> None:
    before = canonical_rows(source_rows, fields, ())
    after = canonical_rows(candidate_rows, fields, ())
    if before != after:
        missing = list((Counter(before) - Counter(after)).items())[:3]
        extra = list((Counter(after) - Counter(before)).items())[:3]
        raise ValueError(f"{label} drift missing={missing} extra={extra}")


def source_evidence(document: dict[str, str], aid: str) -> dict:
    try:
        rows = json.loads(document.get("candidate_evidence_json") or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"candidate evidence JSON invalid {aid}") from exc
    target = TARGETS_BY_AID[aid]
    exact = [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("id") or "") == aid
        and str(row.get("sha256") or "") == target["source_sha256"]
    ]
    if len(exact) != 1:
        raise ValueError(f"expected one exact source {aid}, got {len(exact)}")
    row = dict(exact[0])
    url = str(row.get("url") or "")
    source_bytes = int(row.get("bytes") or 0)
    if not url.startswith("https://static.cninfo.com.cn/"):
        raise ValueError(f"invalid CNINFO source URL {aid}")
    if source_bytes != int(target["source_bytes"]):
        raise ValueError(f"source byte identity changed {aid}")
    return {
        "url": url,
        "sha256": target["source_sha256"],
        "bytes": source_bytes,
        "candidate": row,
    }


def rewrite_evidence(raw_value: str, aid: str, source: dict, parsed: dict) -> str:
    rows = json.loads(raw_value or "[]")
    matches = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if (
            str(row.get("id") or "") == aid
            and str(row.get("sha256") or "") == source["sha256"]
        ):
            row["tier1_found"] = 0
            row["tier2_found"] = 3
            row["parser_version"] = parsed["parser_version"]
            row["validation_errors"] = []
            row.pop("error", None)
            matches += 1
    if matches != 1:
        raise ValueError(f"candidate evidence rewrite count {aid}={matches}")
    return json.dumps(rows, ensure_ascii=False, default=str)


def validate_parsed(parsed: dict, aid: str, source: dict) -> dict[str, dict]:
    if parsed.get("parser_version") != candidate.METHOD:
        raise ValueError(f"candidate method changed {aid}")
    if parsed.get("validation_errors"):
        raise ValueError(f"candidate validation errors retained {aid}")
    if parsed.get("tier1_found") != 0 or parsed.get("tier2_found") != 3:
        raise ValueError(f"candidate tier counts changed {aid}")
    observations = parsed.get("observations") or {}
    found = {
        concept: row
        for concept, row in observations.items()
        if isinstance(row, dict) and row.get("status") == "FOUND"
    }
    if set(found) != ALLOWED_CONCEPTS:
        raise ValueError(f"candidate concept scope changed {aid}: {sorted(found)}")
    block = parsed.get("balance_sheet_block") or {}
    if block.get("candidate_only") is not True:
        raise ValueError(f"candidate-only marker absent {aid}")
    if block.get("exact_source_sha256") != source["sha256"]:
        raise ValueError(f"candidate source SHA changed {aid}")
    if block.get("explicit_equity_pdf_text") is not True:
        raise ValueError(f"candidate equity is not explicit PDF text {aid}")
    if block.get("equity_value_inferred_as_assets_minus_liabilities") is not False:
        raise ValueError(f"candidate equity inference enabled {aid}")
    if block.get("column_role_gate_pass") is not True:
        raise ValueError(f"candidate column role gate failed {aid}")
    identity = block.get("dual_column_identity") or {}
    columns = identity.get("columns") or []
    if len(columns) != 2:
        raise ValueError(f"candidate dual identity columns changed {aid}")
    if any(str(row.get("identity_residual_cny")) not in {"0", "0.0", "0.00"} for row in columns):
        raise ValueError(f"candidate identity residual changed {aid}")
    if block.get("non_balance_values_promoted") is not False:
        raise ValueError(f"candidate non-balance promotion changed {aid}")
    return found


def build_target(
    session: requests.Session, source_doc: dict[str, str]
) -> tuple[dict[str, str], list[dict[str, str]], dict]:
    aid = source_doc["announcement_id"]
    target = TARGETS_BY_AID[aid]
    if source_doc.get("document_status") != "ERROR":
        raise ValueError(f"target is no longer ERROR {aid}")
    if source_doc.get("tie_resolution") != "TIE_SOURCE_INCOMPLETE":
        raise ValueError(f"target tie state changed {aid}")
    if source_doc.get("numeric_observations") != "0":
        raise ValueError(f"target already has numeric rows {aid}")
    source = source_evidence(source_doc, aid)
    raw = download(session, source["url"])
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != source["sha256"] or len(raw) != source["bytes"]:
        raise ValueError(f"exact source identity changed {aid}")

    parsed = candidate.parse_pdf_bytes(raw, source_doc["economic_date"])
    found = validate_parsed(parsed, aid, source)
    block = parsed["balance_sheet_block"]

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
        row = found[concept]
        expected = target["values"][concept][0]
        actual = str(row.get("normalized_cny_value") or "")
        if actual != expected:
            raise ValueError(
                f"candidate value changed {aid} {concept} expected={expected} actual={actual}"
            )
        numeric_rows.append(
            {
                **common_fields,
                "concept": concept,
                "raw_value": str(row.get("raw_value") or ""),
                "normalized_cny_value": actual,
                "unit": str(row.get("unit") or ""),
                "unit_multiplier": str(row.get("unit_multiplier") or ""),
                "source_url": source["url"],
                "source_sha256": source["sha256"],
                "source_format": "PDF",
                "extraction_method": candidate.METHOD,
                "methodology_version": candidate.METHODOLOGY_VERSION,
                "page": str(row.get("page") or ""),
                "matched_alias": str(row.get("matched_alias") or ""),
                "confidence": str(row.get("confidence") or ""),
            }
        )

    document = dict(source_doc)
    document["selected_source_url"] = source["url"]
    document["selected_source_sha256"] = source["sha256"]
    document["selected_source_bytes"] = str(len(raw))
    document["tie_resolution"] = "SINGLE_CANONICAL"
    document["candidate_evidence_json"] = rewrite_evidence(
        source_doc.get("candidate_evidence_json", "[]"), aid, source, parsed
    )
    document["tier1_found"] = "0"
    document["tier2_found"] = "3"
    document["numeric_observations"] = "3"
    document["document_status"] = "PASS"
    document["document_error"] = ""

    detail = {
        "announcement_id": aid,
        "source_sha256": source["sha256"],
        "source_bytes": len(raw),
        "parser_version": parsed["parser_version"],
        "values": {concept: target["values"][concept][0] for concept in ALLOWED_CONCEPTS},
        "prior_validation_values": {concept: target["values"][concept][1] for concept in ALLOWED_CONCEPTS},
        "selected_pages": block.get("selected_pages"),
        "selected_aliases": block.get("selected_aliases"),
        "split_equity_pattern": block.get("split_equity_pattern"),
        "column_alignment": block.get("column_alignment"),
        "dual_column_identity": block.get("dual_column_identity"),
        "explicit_equity_pdf_text": block.get("explicit_equity_pdf_text"),
        "equity_value_inferred_as_assets_minus_liabilities": block.get(
            "equity_value_inferred_as_assets_minus_liabilities"
        ),
        "candidate_only": True,
    }
    return document, numeric_rows, detail


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("--documents", required=True)
    cli.add_argument("--values", required=True)
    cli.add_argument("--out", required=True)
    args = cli.parse_args()

    documents_path = Path(args.documents)
    values_path = Path(args.values)
    if sha256(documents_path) != SOURCE_DOCUMENTS_SHA256:
        raise ValueError("accepted V17.27 document ledger SHA changed")
    if sha256(values_path) != SOURCE_VALUES_SHA256:
        raise ValueError("accepted V17.27 value ledger SHA changed")
    source_docs = read_gz(documents_path)
    source_values = read_gz(values_path)
    if len(source_docs) != SOURCE_DOCUMENT_ROWS:
        raise ValueError(f"source document count changed {len(source_docs)}")
    if len(source_values) != SOURCE_NUMERIC_ROWS:
        raise ValueError(f"source numeric count changed {len(source_values)}")

    source_doc_by_aid = {row["announcement_id"]: row for row in source_docs}
    if len(source_doc_by_aid) != len(source_docs):
        raise ValueError("duplicate source document identity")
    if not set(TARGETS_BY_AID).issubset(source_doc_by_aid):
        raise ValueError("candidate target population absent")
    if any(row["announcement_id"] in TARGETS_BY_AID for row in source_values):
        raise ValueError("candidate targets already contain numeric rows")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "data-workbench-r17-v17-28-split-equity-candidate/1.0",
            "Accept": "application/pdf,*/*;q=0.8",
        }
    )
    target_docs: dict[str, dict[str, str]] = {}
    target_values: list[dict[str, str]] = []
    details: list[dict] = []
    for aid in sorted(TARGETS_BY_AID):
        document, numeric, detail = build_target(session, source_doc_by_aid[aid])
        target_docs[aid] = document
        target_values.extend(numeric)
        details.append(detail)

    if len(target_docs) != 2 or len(target_values) != TARGET_NUMERIC_ROWS:
        raise ValueError(
            f"candidate target output changed docs={len(target_docs)} values={len(target_values)}"
        )
    if Counter(row["announcement_id"] for row in target_values) != Counter(
        {aid: 3 for aid in TARGETS_BY_AID}
    ):
        raise ValueError("candidate target numeric distribution changed")

    candidate_docs = [
        dict(target_docs.get(row["announcement_id"], row)) for row in source_docs
    ]
    candidate_values = [dict(row) for row in source_values] + [
        dict(row) for row in target_values
    ]
    candidate_docs.sort(key=lambda row: row["announcement_id"])
    candidate_values.sort(key=lambda row: (row["announcement_id"], row["concept"]))

    non_target_source_docs = [
        row for row in source_docs if row["announcement_id"] not in TARGETS_BY_AID
    ]
    non_target_candidate_docs = [
        row for row in candidate_docs if row["announcement_id"] not in TARGETS_BY_AID
    ]
    require_exact_rows(
        "non-target document",
        non_target_source_docs,
        non_target_candidate_docs,
        tuple(common.DOC_FIELDS),
    )

    existing_candidate_values = [
        row for row in candidate_values if row["announcement_id"] not in TARGETS_BY_AID
    ]
    require_exact_rows(
        "existing numeric",
        source_values,
        existing_candidate_values,
        tuple(common.NUMERIC_FIELDS),
    )

    source_errors = sum(
        row["document_status"] != "PASS" or bool(row["document_error"])
        for row in source_docs
    )
    candidate_errors = sum(
        row["document_status"] != "PASS" or bool(row["document_error"])
        for row in candidate_docs
    )
    source_ties = sum(
        row.get("tie_resolution") == "TIE_SOURCE_INCOMPLETE" for row in source_docs
    )
    candidate_ties = sum(
        row.get("tie_resolution") == "TIE_SOURCE_INCOMPLETE" for row in candidate_docs
    )
    if (source_errors, candidate_errors) != (SOURCE_ERRORS, CANDIDATE_ERRORS):
        raise ValueError(
            f"candidate error accounting source={source_errors} candidate={candidate_errors}"
        )
    if (source_ties, candidate_ties) != (
        SOURCE_UNRESOLVED_TIES,
        CANDIDATE_UNRESOLVED_TIES,
    ):
        raise ValueError(
            f"candidate tie accounting source={source_ties} candidate={candidate_ties}"
        )
    if len(candidate_values) != CANDIDATE_NUMERIC_ROWS:
        raise ValueError(f"candidate numeric count changed {len(candidate_values)}")

    source_counter = Counter(
        baseline_compare._numeric_tuple(row) for row in source_values
    )
    existing_counter = Counter(
        baseline_compare._numeric_tuple(row) for row in existing_candidate_values
    )
    source_semantic_sha = baseline_compare.semantic_multiset_sha(source_counter)
    candidate_existing_semantic_sha = baseline_compare.semantic_multiset_sha(
        existing_counter
    )
    if source_counter != existing_counter:
        raise ValueError("existing numeric 22-field multiset changed")
    if source_semantic_sha != SOURCE_EXISTING_NUMERIC_SEMANTIC_SHA256:
        raise ValueError(f"source semantic SHA changed {source_semantic_sha}")
    if candidate_existing_semantic_sha != source_semantic_sha:
        raise ValueError("candidate existing numeric semantic SHA changed")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    docs_out = out / "stage3_financial_documents_v17_28_candidate.csv.gz"
    values_out = out / "stage3_financial_values_v17_28_candidate.csv.gz"
    common.write_gz(docs_out, common.DOC_FIELDS, candidate_docs)
    common.write_gz(values_out, common.NUMERIC_FIELDS, candidate_values)

    report = {
        "gate": "S3G1J_V17_28_SPLIT_GROUP_EQUITY_CANDIDATE_SAFETY",
        "candidate_only": True,
        "formal_runtime_generation": "V17.27",
        "candidate_generation": "V17.28",
        "parser_method": candidate.METHOD,
        "methodology_version": candidate.METHODOLOGY_VERSION,
        "target_announcement_ids": sorted(TARGETS_BY_AID),
        "target_count": 2,
        "target_numeric_rows": TARGET_NUMERIC_ROWS,
        "target_details": details,
        "source_document_rows": len(source_docs),
        "candidate_document_rows": len(candidate_docs),
        "source_numeric_rows": len(source_values),
        "candidate_numeric_rows": len(candidate_values),
        "source_document_errors": source_errors,
        "candidate_document_errors": candidate_errors,
        "document_error_reduction": source_errors - candidate_errors,
        "source_unresolved_ties": source_ties,
        "candidate_unresolved_ties": candidate_ties,
        "unresolved_tie_reduction": source_ties - candidate_ties,
        "non_target_document_rows": len(non_target_source_docs),
        "non_target_document_exact_equal": True,
        "existing_numeric_rows": len(source_values),
        "existing_numeric_exact_equal": True,
        "stable_numeric_field_count": len(baseline_compare.STABLE_NUMERIC_FIELDS),
        "source_existing_numeric_semantic_sha256": source_semantic_sha,
        "candidate_existing_numeric_semantic_sha256": candidate_existing_semantic_sha,
        "candidate_documents_sha256": sha256(docs_out),
        "candidate_values_sha256": sha256(values_out),
        "non_balance_values_promoted": False,
        "source_policy_changed": False,
        "point_in_time_policy_changed": False,
        "issuer_gate_changed": False,
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "ocr_enabled": False,
        "fuzzy_alias_matching_enabled": False,
        "e_equals_a_minus_l_inference": False,
        "production_runtime_changed": False,
        "production_data_changed": False,
        "trained_model_changed": False,
        "candidate_promotion_authorized": False,
        "final_data_verdict": "FAIL_CLOSED",
        "stage3_status": "NOT_READY",
        "stage4_alpha_live_locked": True,
        "main_changed": False,
        "pass": True,
        "errors": [],
    }
    report_path = out / "stage3_s3g1j_v17_28_candidate_safety.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
