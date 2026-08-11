#!/usr/bin/env python3
from __future__ import annotations

import argparse
import binascii
import csv
import gzip
import hashlib
import io
import json
import struct
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

import fitz
import requests

import stage3_financial_pdf_parser_v21 as formal
import stage3_financial_pdf_parser_v21_promotion_safety as geom
import stage3_financial_statement_blocks_v16_5 as blocks

METHOD = "V17_29_CROSS_PAGE_EQUITY_PRODUCTION_PROMOTION_SAFETY"
EXTRACTION_METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V19_V17_29_CROSS_PAGE_EQUITY_PRODUCTION_PROMOTION_SAFETY"
METHODOLOGY_VERSION = "V3.3.13-V17.29-CROSS-PAGE-PROMOTION-SAFETY"
FULL_EQUITY_ALIAS = "所有者权益（或股东权益）合计"
ALLOWED_CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")

SOURCE_DOCUMENTS_GZIP_SHA256 = "644bccd1a984fdbc002a139f8ced0313a8cf749124a178e7ace7965472f395af"
SOURCE_VALUES_GZIP_SHA256 = "5ce9ac74a3cd028fab6ccb862eb825cc957e6c545c06d7fac6b882a6ccca1afa"
SOURCE_DOCUMENT_ROWS = 121354
SOURCE_NUMERIC_ROWS = 1051820
SOURCE_ERRORS = 1364
SOURCE_SOURCE_INCOMPLETE = 1267
SOURCE_VALUE_CONFLICT = 14
SOURCE_UNRESOLVED_TIES = 1281
TARGET_NUMERIC_ROWS = 6

TARGETS: dict[str, dict[str, Any]] = {
    "1223347318": {
        "source_code": "605289",
        "economic_date": "2025-03-31",
        "economic_date_cn": "2025年3月31日",
        "source_url": "https://static.cninfo.com.cn/finalpage/2025-04-28/1223347318.PDF",
        "source_sha256": "d765c94532cd41a496d147da72cbff392bce4ff776b41b88d95dcf3f1fb697c8",
        "source_bytes": 492929,
        "equity_prefix": "所有者权益（或股东权益）合",
        "equity_suffix": "计",
        "next_page_head": [
            "上海罗曼科技股份有限公司2025 年第一季度报告",
            "计",
            "负债和所有者权益（或股东",
            "2,250,857,154.79 2,237,673,819.93",
            "权益）总计",
        ],
        "next_statement_title": "合并利润表",
        "values": {
            "TOTAL_ASSETS": ["2250857154.79", "2237673819.93"],
            "TOTAL_LIABILITIES": ["954370096.74", "961178424.14"],
            "TOTAL_EQUITY": ["1296487058.05", "1276495395.79"],
        },
    },
    "1223407043": {
        "source_code": "605162",
        "economic_date": "2024-12-31",
        "economic_date_cn": "2024年12月31日",
        "source_url": "https://static.cninfo.com.cn/finalpage/2025-04-30/1223407043.PDF",
        "source_sha256": "7540a56179783625ac256726480ef32faf85a893549057fe9e6546abfd6ee903",
        "source_bytes": 1367714,
        "equity_prefix": "所有者权益（或股东权",
        "equity_suffix": "益）合计",
        "next_page_head": [
            "浙江新中港热电股份有限公司2024 年年度报告",
            "益）合计",
            "负债和所有者权益（或",
            "1,885,230,514.78 1,750,850,622.44",
            "股东权益）总计",
        ],
        "next_statement_title": "母公司资产负债表",
        "values": {
            "TOTAL_ASSETS": ["1885230514.78", "1750850622.44"],
            "TOTAL_LIABILITIES": ["564752701.93", "490942613.17"],
            "TOTAL_EQUITY": ["1320477812.85", "1259908009.27"],
        },
    },
}
TARGET_IDS = tuple(sorted(TARGETS))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_gz(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def _stored_deflate(raw: bytes) -> bytes:
    out = bytearray()
    pos = 0
    if not raw:
        return b"\x01\x00\x00\xff\xff"
    while pos < len(raw):
        chunk = raw[pos : pos + 65535]
        pos += len(chunk)
        final = 1 if pos == len(raw) else 0
        out.append(final)
        n = len(chunk)
        out.extend(struct.pack("<H", n))
        out.extend(struct.pack("<H", 0xFFFF ^ n))
        out.extend(chunk)
    return bytes(out)


def deterministic_gzip(raw: bytes) -> bytes:
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"
    trailer = struct.pack("<II", binascii.crc32(raw) & 0xFFFFFFFF, len(raw) & 0xFFFFFFFF)
    return header + _stored_deflate(raw) + trailer


def write_csv_gz(path: Path, fields: list[str], rows: list[dict[str, str]]) -> tuple[str, str]:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    raw = buf.getvalue().encode("utf-8")
    gz = deterministic_gzip(raw)
    path.write_bytes(gz)
    return sha256_bytes(raw), sha256_bytes(gz)


def row_counter(rows: list[dict[str, str]], fields: list[str]) -> Counter[tuple[str, ...]]:
    return Counter(tuple(row.get(field, "") for field in fields) for row in rows)


def tie_taxonomy(rows: list[dict[str, str]]) -> dict[str, int]:
    counts = Counter(row.get("tie_resolution", "") for row in rows)
    return {
        "TIE_SOURCE_INCOMPLETE": counts["TIE_SOURCE_INCOMPLETE"],
        "TIE_VALUE_CONFLICT": counts["TIE_VALUE_CONFLICT"],
    }


def semantic_sha(rows: list[dict[str, str]], fields: list[str], excluded: set[str] | None = None) -> str:
    excluded = excluded or set()
    projected = Counter(tuple(row.get(field, "") for field in fields if field not in excluded) for row in rows)
    h = hashlib.sha256()
    for key, count in sorted(projected.items()):
        h.update(json.dumps([list(key), count], ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def source_identity(row: dict[str, str], target: dict[str, Any]) -> dict[str, Any]:
    if row.get("document_status") != "ERROR" or row.get("tie_candidate_count") != "1" or row.get("tie_resolution") != "TIE_SOURCE_INCOMPLETE":
        raise ValueError(f"{row.get('announcement_id')}: target is not expected single-canonical residual")
    evidence = json.loads(row.get("candidate_evidence_json") or "[]")
    if len(evidence) != 1:
        raise ValueError(f"{row.get('announcement_id')}: candidate evidence count != 1")
    candidate = evidence[0]
    validation = [str(x) for x in (candidate.get("validation_errors") or [])]
    if int(candidate.get("tier2_found") or 0) != 3 or "NO_VALIDATED_BALANCE_SHEET_BLOCK" not in validation:
        raise ValueError(f"{row.get('announcement_id')}: expected candidate fail-closed evidence missing")
    if str(candidate.get("id") or "") != str(row.get("announcement_id") or ""):
        raise ValueError("candidate announcement identity drift")
    if str(candidate.get("sha256") or "") != target["source_sha256"]:
        raise ValueError("candidate source SHA drift")
    if int(candidate.get("bytes") or 0) != int(target["source_bytes"]):
        raise ValueError("candidate source bytes drift")
    if str(candidate.get("url") or "") != target["source_url"]:
        raise ValueError("candidate source URL drift")
    if str(row.get("economic_date") or "") != target["economic_date"]:
        raise ValueError("candidate economic date drift")
    return candidate


def download_exact(session: requests.Session, target: dict[str, Any]) -> bytes:
    last: Exception | None = None
    for attempt in range(1, 5):
        try:
            response = session.get(target["source_url"], timeout=(30, 180), headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            raw = response.content
            if not raw.startswith(b"%PDF"):
                raise ValueError("not PDF")
            if len(raw) != int(target["source_bytes"]) or hashlib.sha256(raw).hexdigest() != target["source_sha256"]:
                raise ValueError("source identity mismatch")
            return raw
        except Exception as exc:
            last = exc
            if attempt < 4:
                time.sleep(attempt * 3)
    raise RuntimeError(f"exact PDF download failed: {last}")


def _norm(text: str) -> str:
    return geom._normalize(text or "")


def _find_cross_page_equity(rows_by_page: dict[int, list[dict[str, Any]]], events: list[dict[str, Any]], target: dict[str, Any]) -> dict[str, Any]:
    prefix = _norm(target["equity_prefix"])
    suffix = _norm(target["equity_suffix"])
    if prefix + suffix != _norm(FULL_EQUITY_ALIAS):
        raise ValueError("configured equity fragments do not exactly complete alias")
    matches: list[dict[str, Any]] = []
    for page, rows in rows_by_page.items():
        for row in rows:
            pair = geom._amount_pair(row, target["values"]["TOTAL_EQUITY"])
            if pair is None:
                continue
            if not _norm(str(row.get("text") or "")).startswith(prefix):
                continue
            event = geom._bind(events, page, row)
            if not event or event.get("role") != "GROUP" or "合并资产负债表" not in str(event.get("line") or ""):
                continue
            header = geom._validate_header(rows_by_page, event, target)
            next_rows = rows_by_page.get(page + 1, [])
            head = [str(x.get("text") or "") for x in next_rows[: len(target["next_page_head"])]]
            if [_norm(x) for x in head] != [_norm(x) for x in target["next_page_head"]]:
                continue
            if _norm(head[1]) != suffix:
                continue
            boundary_rows = [_norm(str(x.get("text") or "")) for x in next_rows[:12]]
            if not any(_norm(target["next_statement_title"]) in x for x in boundary_rows):
                continue
            matches.append({
                "page": page,
                "pair": pair,
                "row": row,
                "event": event,
                "header": header,
                "suffix_page": page + 1,
                "next_page_head": head,
            })
    if len(matches) != 1:
        raise ValueError(f"cross-page exact equity candidate count expected=1 actual={len(matches)}")
    return matches[0]


def recover(raw: bytes, target: dict[str, Any]) -> dict[str, Any]:
    formal_snapshot = formal.parse_pdf_bytes(raw, target["economic_date"])
    if int(formal_snapshot.get("tier2_found") or 0) != 3 or "NO_VALIDATED_BALANCE_SHEET_BLOCK" not in list(formal_snapshot.get("validation_errors") or []):
        raise ValueError("formal V17.29 no longer fails closed on target")
    with fitz.open(stream=raw, filetype="pdf") as doc:
        events = blocks.formal_statement_events(doc)
        rows_by_page = geom._rows_by_page(doc)
        found = {
            "TOTAL_ASSETS": geom._find_exact_labeled(rows_by_page, events, target, "TOTAL_ASSETS"),
            "TOTAL_LIABILITIES": geom._find_exact_labeled(rows_by_page, events, target, "TOTAL_LIABILITIES"),
            "TOTAL_EQUITY": _find_cross_page_equity(rows_by_page, events, target),
        }
        keys = {geom._event_key(found[c]["event"]) for c in ALLOWED_CONCEPTS}
        if len(keys) != 1:
            raise ValueError("A/L/E are not bound to exactly one GROUP event")
        alignment = geom._validate_alignment(found)
        identity = geom._validate_identity(target)
    if any(Decimal(str(x.get("identity_residual_cny"))) != 0 for x in identity["columns"]):
        raise ValueError("dual-column identity is not exact zero")
    observations: dict[str, dict[str, Any]] = {}
    for concept in ALLOWED_CONCEPTS:
        item = found[concept]
        current = target["values"][concept][0]
        observations[concept] = {
            "status": "FOUND",
            "raw_value": f"{Decimal(current):,.2f}",
            "normalized_cny_value": current,
            "page": int(item["page"]),
            "matched_alias": FULL_EQUITY_ALIAS if concept == "TOTAL_EQUITY" else geom.TARGET_ALIASES[concept],
            "confidence": "HIGH",
        }
    return {
        "formal_snapshot": formal_snapshot,
        "observations": observations,
        "alignment": alignment,
        "identity": identity,
        "cross_page": {
            "equity_amount_page": int(found["TOTAL_EQUITY"]["page"]),
            "suffix_page": int(found["TOTAL_EQUITY"]["suffix_page"]),
            "equity_prefix": target["equity_prefix"],
            "equity_suffix": target["equity_suffix"],
            "completed_alias": FULL_EQUITY_ALIAS,
            "next_page_head": found["TOTAL_EQUITY"]["next_page_head"],
        },
    }


def value_row(doc: dict[str, str], target: dict[str, Any], concept: str, observation: dict[str, Any]) -> dict[str, str]:
    return {
        "exchange": doc["exchange"],
        "source_code": doc["source_code"],
        "effective_code": doc["effective_code"],
        "issuer_org_id": doc["issuer_org_id"],
        "report_family": doc["report_family"],
        "economic_date": doc["economic_date"],
        "announcement_id": doc["announcement_id"],
        "revision_sequence": doc["revision_sequence"],
        "source_published_at": doc["source_published_at"],
        "effective_session": doc["effective_session"],
        "available_at": doc["available_at"],
        "concept": concept,
        "raw_value": str(observation["raw_value"]),
        "normalized_cny_value": str(observation["normalized_cny_value"]),
        "unit": "元",
        "unit_multiplier": "1",
        "source_url": target["source_url"],
        "source_sha256": target["source_sha256"],
        "source_format": "PDF",
        "extraction_method": EXTRACTION_METHOD,
        "methodology_version": METHODOLOGY_VERSION,
        "page": str(observation["page"]),
        "matched_alias": str(observation["matched_alias"]),
        "confidence": str(observation["confidence"]),
    }


def safety_gold(path: Path) -> dict[str, dict[str, Any]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("gate") != "S3G1J_V17_29_TWO_TARGET_CROSS_PAGE_CANDIDATE_SAFETY_V1" or report.get("candidate_experiment_pass") is not True:
        raise ValueError("accepted candidate-safety gold is invalid")
    rows = {str(x["announcement_id"]): x for x in report["recoveries"]}
    if set(rows) != set(TARGET_IDS):
        raise ValueError("accepted candidate-safety target set drift")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--documents", required=True)
    ap.add_argument("--values", required=True)
    ap.add_argument("--safety-report", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    documents = Path(args.documents)
    values = Path(args.values)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if sha256_file(documents) != SOURCE_DOCUMENTS_GZIP_SHA256:
        raise ValueError("accepted V17.29 documents hash drift")
    if sha256_file(values) != SOURCE_VALUES_GZIP_SHA256:
        raise ValueError("accepted V17.29 values hash drift")
    gold = safety_gold(Path(args.safety_report))
    doc_fields, source_docs = read_gz(documents)
    value_fields, source_values = read_gz(values)
    if len(source_docs) != SOURCE_DOCUMENT_ROWS or len(source_values) != SOURCE_NUMERIC_ROWS:
        raise ValueError("accepted V17.29 source population drift")

    session = requests.Session()
    promotion_docs: list[dict[str, str]] = []
    promotion_added: list[dict[str, str]] = []
    target_reports: list[dict[str, Any]] = []

    for row in source_docs:
        aid = row["announcement_id"]
        if aid not in TARGETS:
            promotion_docs.append(dict(row))
            continue
        target = TARGETS[aid]
        candidate = source_identity(row, target)
        raw = download_exact(session, target)
        recovered = recover(raw, target)
        gold_row = gold[aid]
        for concept in ALLOWED_CONCEPTS:
            obs = recovered["observations"][concept]
            if str(obs["normalized_cny_value"]) != str(gold_row["candidate_recovery"]["observations"][concept]["normalized_cny_value"]):
                raise ValueError(f"{aid} {concept}: value differs from accepted safety gold")
            if int(obs["page"]) != int(gold_row["candidate_recovery"]["observations"][concept]["page"]):
                raise ValueError(f"{aid} {concept}: page differs from accepted safety gold")
            if str(obs["matched_alias"]) != str(gold_row["candidate_recovery"]["observations"][concept]["matched_alias"]):
                raise ValueError(f"{aid} {concept}: alias differs from accepted safety gold")
            promotion_added.append(value_row(row, target, concept, obs))
        if recovered["cross_page"]["equity_amount_page"] != int(gold_row["candidate_recovery"]["cross_page_pattern"]["equity_amount_page"]):
            raise ValueError(f"{aid}: equity page differs from accepted safety gold")
        if recovered["cross_page"]["suffix_page"] != int(gold_row["candidate_recovery"]["cross_page_pattern"]["suffix_page"]):
            raise ValueError(f"{aid}: suffix page differs from accepted safety gold")
        if recovered["cross_page"]["completed_alias"] != FULL_EQUITY_ALIAS:
            raise ValueError(f"{aid}: completed equity alias drift")

        new = dict(row)
        new["selected_source_url"] = target["source_url"]
        new["selected_source_sha256"] = target["source_sha256"]
        new["selected_source_bytes"] = str(target["source_bytes"])
        new["tie_resolution"] = "SINGLE_CANONICAL"
        new["tier1_found"] = "0"
        new["tier2_found"] = "3"
        new["numeric_observations"] = "3"
        new["document_status"] = "PASS"
        new["document_error"] = ""
        ev = dict(candidate)
        ev.pop("error", None)
        ev.update({
            "tier1_found": 0,
            "tier2_found": 3,
            "parser_version": METHOD,
            "validation_errors": [],
            "production_promotion_safety_only": True,
            "runtime_promotion_authorized": False,
            "cross_page_equity_pattern": "ONE_PAGE_EXACT_ALIAS_CONTINUATION",
        })
        new["candidate_evidence_json"] = json.dumps([ev], ensure_ascii=False, separators=(",", ":"))
        promotion_docs.append(new)
        target_reports.append({
            "announcement_id": aid,
            "source_sha256": target["source_sha256"],
            "source_bytes": target["source_bytes"],
            "economic_date": target["economic_date"],
            "selected_pages": {c: recovered["observations"][c]["page"] for c in ALLOWED_CONCEPTS},
            "cross_page": recovered["cross_page"],
            "identity": recovered["identity"],
        })

    promotion_added.sort(key=lambda row: (row["announcement_id"], row["concept"]))
    promotion_values = source_values + promotion_added
    if len(promotion_docs) != SOURCE_DOCUMENT_ROWS or len(promotion_added) != TARGET_NUMERIC_ROWS or len(promotion_values) != SOURCE_NUMERIC_ROWS + TARGET_NUMERIC_ROWS:
        raise ValueError("promotion population mismatch")

    source_non = [r for r in source_docs if r["announcement_id"] not in TARGET_IDS]
    promotion_non = [r for r in promotion_docs if r["announcement_id"] not in TARGET_IDS]
    non_target_exact = row_counter(source_non, doc_fields) == row_counter(promotion_non, doc_fields)
    existing_numeric_exact = row_counter(source_values, value_fields) == row_counter(promotion_values[:SOURCE_NUMERIC_ROWS], value_fields)
    if not non_target_exact or not existing_numeric_exact:
        raise ValueError("non-target document or existing numeric drift")

    source_errors = sum(r["document_status"] == "ERROR" for r in source_docs)
    promotion_errors = sum(r["document_status"] == "ERROR" for r in promotion_docs)
    source_ties = tie_taxonomy(source_docs)
    promotion_ties = tie_taxonomy(promotion_docs)
    if source_errors != SOURCE_ERRORS or source_ties != {"TIE_SOURCE_INCOMPLETE": SOURCE_SOURCE_INCOMPLETE, "TIE_VALUE_CONFLICT": SOURCE_VALUE_CONFLICT}:
        raise ValueError("accepted V17.29 residual baseline drift")
    if promotion_errors != source_errors - 2:
        raise ValueError(f"promotion error reduction must be exactly 2, got {source_errors}->{promotion_errors}")
    if promotion_ties != {"TIE_SOURCE_INCOMPLETE": SOURCE_SOURCE_INCOMPLETE - 2, "TIE_VALUE_CONFLICT": SOURCE_VALUE_CONFLICT}:
        raise ValueError(f"promotion tie taxonomy unexpected {promotion_ties}")
    if sum(source_ties.values()) != SOURCE_UNRESOLVED_TIES or sum(promotion_ties.values()) != SOURCE_UNRESOLVED_TIES - 2:
        raise ValueError("promotion unresolved tie reduction must be exactly 2")
    distribution = Counter(r["announcement_id"] for r in promotion_added)
    if distribution != Counter({aid: 3 for aid in TARGET_IDS}):
        raise ValueError(f"target numeric distribution drift {distribution}")

    docs_out = out / "stage3_financial_documents_v17_29_cross_page_promotion_safety.csv.gz"
    values_out = out / "stage3_financial_values_v17_29_cross_page_promotion_safety.csv.gz"
    docs_plain_sha, docs_gz_sha = write_csv_gz(docs_out, doc_fields, promotion_docs)
    values_plain_sha, values_gz_sha = write_csv_gz(values_out, value_fields, promotion_values)

    source_target_docs = [r for r in source_docs if r["announcement_id"] in TARGET_IDS]
    promotion_target_docs = [r for r in promotion_docs if r["announcement_id"] in TARGET_IDS]
    target_values = [r for r in promotion_added]
    report = {
        "gate": "S3G1J_V17_29_CROSS_PAGE_PRODUCTION_PROMOTION_SAFETY_V1",
        "production_promotion_safety_only": True,
        "formal_runtime_generation": "V17.29",
        "proposed_runtime_generation": "V17.30_NOT_AUTHORIZED",
        "target_announcement_ids": list(TARGET_IDS),
        "source_document_rows": len(source_docs),
        "promotion_document_rows": len(promotion_docs),
        "source_numeric_rows": len(source_values),
        "promotion_numeric_rows": len(promotion_values),
        "source_document_errors": source_errors,
        "promotion_document_errors": promotion_errors,
        "source_unresolved_tie_taxonomy": source_ties,
        "promotion_unresolved_tie_taxonomy": promotion_ties,
        "source_unresolved_ties": sum(source_ties.values()),
        "promotion_unresolved_ties": sum(promotion_ties.values()),
        "non_target_document_rows": len(source_non),
        "non_target_document_exact_equal": non_target_exact,
        "existing_numeric_rows": len(source_values),
        "existing_numeric_exact_equal": existing_numeric_exact,
        "target_numeric_rows_added": len(promotion_added),
        "target_numeric_distribution": dict(sorted(distribution.items())),
        "target_reports": sorted(target_reports, key=lambda x: x["announcement_id"]),
        "source_target_document_semantic_sha256": semantic_sha(source_target_docs, doc_fields),
        "promotion_target_document_semantic_sha256": semantic_sha(promotion_target_docs, doc_fields),
        "promotion_target_numeric_semantic_sha256": semantic_sha(target_values, value_fields, {"extraction_method", "methodology_version"}),
        "promotion_documents_plaintext_sha256": docs_plain_sha,
        "promotion_documents_gzip_sha256": docs_gz_sha,
        "promotion_values_plaintext_sha256": values_plain_sha,
        "promotion_values_gzip_sha256": values_gz_sha,
        "accounting_tolerance": "0.005",
        "observed_identity_residuals_exact_zero": True,
        "ocr_enabled": False,
        "fuzzy_alias_matching_enabled": False,
        "equity_inferred_as_assets_minus_liabilities": False,
        "source_policy_relaxed": False,
        "point_in_time_policy_relaxed": False,
        "issuer_gate_relaxed": False,
        "accounting_tolerance_relaxed": False,
        "formal_parser_changed": False,
        "runtime_authority_changed": False,
        "production_data_changed": False,
        "runtime_promotion_authorized": False,
        "full_basis_execution_authorized": False,
        "stage3_status": "NOT_READY",
        "final_data_verdict": "FAIL_CLOSED",
        "stage4_alpha_live_locked": True,
        "main_changed": False,
        "pass": True,
        "errors": [],
    }
    report_path = out / "stage3_s3g1j_v17_29_cross_page_production_promotion_safety.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_hashes = {
        docs_out.name: sha256_file(docs_out),
        values_out.name: sha256_file(values_out),
        report_path.name: sha256_file(report_path),
    }
    (out / "output_sha256.json").write_text(json.dumps(output_hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "source_document_rows": source_errors,
        "promotion_numeric_rows": len(promotion_values),
        "source_document_errors": source_errors,
        "promotion_document_errors": promotion_errors,
        "source_unresolved_ties": sum(source_ties.values()),
        "promotion_unresolved_ties": sum(promotion_ties.values()),
        "non_target_document_exact_equal": non_target_exact,
        "existing_numeric_exact_equal": existing_numeric_exact,
        "target_numeric_rows_added": len(promotion_added),
        "pass": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
