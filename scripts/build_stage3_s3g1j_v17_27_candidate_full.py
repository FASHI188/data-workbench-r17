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

import promote_stage3_s3g1j_v17_26_full_shards as common
import stage3_financial_pdf_parser_v19_candidate as parser_candidate

TARGETS_BY_AID = {
    target["announcement_id"]: {"source_sha256": source_sha, **target}
    for source_sha, target in parser_candidate.TARGETS.items()
}
ALLOWED_CONCEPTS = frozenset(parser_candidate.ALLOWED_CONCEPTS)


def read_gz(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_sha(rows: list[dict[str, str]], fields: list[str]) -> str:
    digest = hashlib.sha256()
    for row in sorted(
        rows,
        key=lambda item: (
            item.get("announcement_id", ""),
            item.get("concept", ""),
        ),
    ):
        payload = [row.get(field, "") for field in fields]
        digest.update(
            (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
        )
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


def source_evidence(document: dict[str, str], aid: str) -> dict:
    try:
        rows = json.loads(document.get("candidate_evidence_json") or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"candidate evidence JSON invalid {aid}") from exc
    if not isinstance(rows, list):
        raise ValueError(f"candidate evidence is not a list {aid}")
    exact = [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("id") or "") == aid
        and str(row.get("sha256") or "") == TARGETS_BY_AID[aid]["source_sha256"]
    ]
    if len(exact) != 1:
        raise ValueError(f"expected one exact canonical source {aid}, got {len(exact)}")
    row = dict(exact[0])
    url = str(row.get("url") or "")
    expected_bytes = int(row.get("bytes") or 0)
    if not url.startswith("https://static.cninfo.com.cn/") or expected_bytes <= 0:
        raise ValueError(f"invalid exact source identity {aid}")
    return {
        "url": url,
        "sha256": TARGETS_BY_AID[aid]["source_sha256"],
        "bytes": expected_bytes,
        "candidate": row,
    }


def rewrite_evidence(
    raw_value: str, aid: str, source: dict, parsed: dict
) -> str:
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
        raise ValueError(f"candidate evidence rewrite count changed {aid}: {matches}")
    return json.dumps(rows, ensure_ascii=False, default=str)


def build_target(
    session: requests.Session, source_doc: dict[str, str]
) -> tuple[dict[str, str], list[dict[str, str]], dict]:
    aid = source_doc["announcement_id"]
    target = TARGETS_BY_AID[aid]
    if source_doc.get("document_status") == "PASS" or not source_doc.get(
        "document_error"
    ):
        raise ValueError(f"candidate target is not fail-closed in V17.26 {aid}")
    source = source_evidence(source_doc, aid)
    raw = download(session, source["url"])
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != source["sha256"] or len(raw) != source["bytes"]:
        raise ValueError(f"exact source identity changed {aid}")

    parsed = parser_candidate.parse_pdf_bytes(raw, source_doc["economic_date"])
    if parsed.get("parser_version") != parser_candidate.METHOD:
        raise ValueError(f"candidate parser method changed {aid}")
    if parsed.get("validation_errors"):
        raise ValueError(f"candidate retained validation errors {aid}")
    if parsed.get("tier1_found") != 0 or parsed.get("tier2_found") != 3:
        raise ValueError(f"candidate tier counts changed {aid}")
    block = parsed.get("balance_sheet_block") or {}
    if block.get("candidate_only") is not True:
        raise ValueError(f"candidate-only marker absent {aid}")
    if block.get("exact_source_sha256") != source["sha256"]:
        raise ValueError(f"candidate source SHA binding changed {aid}")
    if block.get("normal_equity_alias") != "所有者权益合计":
        raise ValueError(f"candidate normal-equity alias changed {aid}")
    if block.get("damaged_equity_alias_required") is not False:
        raise ValueError(f"candidate damaged-alias boundary changed {aid}")

    observations = parsed.get("observations") or {}
    found = {
        concept: row
        for concept, row in observations.items()
        if isinstance(row, dict) and row.get("status") == "FOUND"
    }
    if set(found) != ALLOWED_CONCEPTS:
        raise ValueError(f"candidate concept scope changed {aid}: {sorted(found)}")

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
        expected = target["values"][concept]
        actual = str(row.get("normalized_cny_value") or "")
        if actual != expected:
            raise ValueError(
                f"candidate value changed {aid} {concept}: expected={expected} actual={actual}"
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
                "extraction_method": parser_candidate.METHOD,
                "methodology_version": parser_candidate.METHODOLOGY_VERSION,
                "page": str(row.get("page") or ""),
                "matched_alias": str(row.get("matched_alias") or ""),
                "confidence": str(row.get("confidence") or ""),
            }
        )

    document = dict(source_doc)
    document["selected_source_url"] = source["url"]
    document["selected_source_sha256"] = source["sha256"]
    document["selected_source_bytes"] = str(len(raw))
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
        "values": target["values"],
        "selected_pages": block.get("selected_pages"),
        "selected_aliases": block.get("selected_aliases"),
        "identity_relative_error": block.get("identity_relative_error"),
        "identity_residual_cny": block.get("identity_residual_cny"),
        "column_role_gate_pass": block.get("column_role_gate_pass"),
        "candidate_only": True,
    }
    return document, numeric_rows, detail


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("--documents", required=True)
    cli.add_argument("--values", required=True)
    cli.add_argument("--out", required=True)
    args = cli.parse_args()

    source_docs = read_gz(Path(args.documents))
    source_values = read_gz(Path(args.values))
    if len(source_docs) != 121354:
        raise ValueError(f"V17.26 document count changed {len(source_docs)}")
    if len(source_values) != 1051778:
        raise ValueError(f"V17.26 numeric count changed {len(source_values)}")

    source_doc_by_aid = {row["announcement_id"]: row for row in source_docs}
    if len(source_doc_by_aid) != len(source_docs):
        raise ValueError("duplicate V17.26 document identities")
    if not set(TARGETS_BY_AID).issubset(source_doc_by_aid):
        raise ValueError("candidate target population absent from full basis")
    old_target_numeric = [
        row for row in source_values if row["announcement_id"] in TARGETS_BY_AID
    ]
    if old_target_numeric:
        raise ValueError(
            f"candidate targets already contain numeric rows {len(old_target_numeric)}"
        )

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "data-workbench-r17-v17-27-normal-equity-candidate/1.0",
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

    if len(target_docs) != 5 or len(target_values) != 15:
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
    if non_target_source_docs != non_target_candidate_docs:
        raise ValueError("non-target document rows changed")
    if source_values != [
        row for row in candidate_values if row["announcement_id"] not in TARGETS_BY_AID
    ]:
        raise ValueError("non-target numeric rows changed")

    source_errors = sum(
        row["document_status"] != "PASS" or bool(row["document_error"])
        for row in source_docs
    )
    candidate_errors = sum(
        row["document_status"] != "PASS" or bool(row["document_error"])
        for row in candidate_docs
    )
    if source_errors != 1378 or candidate_errors != 1373:
        raise ValueError(
            f"candidate error accounting changed source={source_errors} candidate={candidate_errors}"
        )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    docs_path = out / "stage3_financial_documents_candidate.csv.gz"
    values_path = out / "stage3_financial_values_candidate.csv.gz"
    common.write_gz(docs_path, common.DOC_FIELDS, candidate_docs)
    common.write_gz(values_path, common.NUMERIC_FIELDS, candidate_values)

    report = {
        "gate": "S3G1J_V17_27_NORMAL_EQUITY_IDENTITY_CANDIDATE_SAFETY",
        "candidate_only": True,
        "formal_runtime_generation": "V17.26",
        "candidate_generation": "V17.27",
        "parser_method": parser_candidate.METHOD,
        "methodology_version": parser_candidate.METHODOLOGY_VERSION,
        "target_announcement_ids": sorted(TARGETS_BY_AID),
        "target_count": 5,
        "target_numeric_rows": 15,
        "target_details": details,
        "source_document_rows": len(source_docs),
        "candidate_document_rows": len(candidate_docs),
        "source_numeric_rows": len(source_values),
        "candidate_numeric_rows": len(candidate_values),
        "source_document_errors": source_errors,
        "candidate_document_errors": candidate_errors,
        "document_error_reduction": source_errors - candidate_errors,
        "non_target_document_rows": len(non_target_source_docs),
        "non_target_document_exact_equal": True,
        "non_target_numeric_rows": len(source_values),
        "non_target_numeric_exact_equal": True,
        "source_numeric_semantic_sha256": semantic_sha(
            source_values, common.NUMERIC_FIELDS
        ),
        "candidate_non_target_numeric_semantic_sha256": semantic_sha(
            [
                row
                for row in candidate_values
                if row["announcement_id"] not in TARGETS_BY_AID
            ],
            common.NUMERIC_FIELDS,
        ),
        "candidate_documents_sha256": sha256(docs_path),
        "candidate_values_sha256": sha256(values_path),
        "non_balance_values_promoted": False,
        "source_policy_changed": False,
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "e_equals_a_minus_l_inference": False,
        "production_runtime_changed": False,
        "production_data_changed": False,
        "trained_model_changed": False,
        "final_data_verdict": "FAIL_CLOSED",
        "stage3_status": "NOT_READY",
        "stage4_alpha_locked": True,
        "main_changed": False,
        "pass": True,
        "errors": [],
    }
    if (
        report["source_numeric_semantic_sha256"]
        != report["candidate_non_target_numeric_semantic_sha256"]
    ):
        raise ValueError("candidate non-target numeric semantic SHA changed")
    report_path = out / "stage3_s3g1j_v17_27_candidate_safety.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
