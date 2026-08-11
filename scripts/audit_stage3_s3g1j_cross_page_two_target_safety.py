#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import fitz
import requests

import stage3_financial_pdf_parser_v21 as formal
import stage3_financial_pdf_parser_v21_promotion_safety as prior_safety
import stage3_financial_statement_blocks_v16_5 as blocks

METHOD = "V17_29_TWO_TARGET_CROSS_PAGE_EQUITY_CANDIDATE_SAFETY_DIAGNOSTIC"
FULL_EQUITY_ALIAS = "所有者权益（或股东权益）合计"
IDENTITY_TOLERANCE = Decimal("0.005")

SOURCE_RUN = 31389854868
SOURCE_ARTIFACT_ID = 9063271903
SOURCE_ARTIFACT_DIGEST = "sha256:71a4daa6c8372f3d64080b5fa5b787914292d889da7051de699eb6610189c726"
SOURCE_DOCUMENTS_GZIP_SHA256 = "644bccd1a984fdbc002a139f8ced0313a8cf749124a178e7ace7965472f395af"
SOURCE_DOCUMENTS_PLAINTEXT_SHA256 = "11ecdb2660b22e40d6134cd1b55caaacd18a69af89725b9c6ff0427b083171d4"

TARGETS: dict[str, dict[str, Any]] = {
    "1223347318": {
        "source_code": "605289",
        "economic_date": "2025-03-31",
        "economic_date_cn": "2025年3月31日",
        "source_url": "https://static.cninfo.com.cn/finalpage/2025-04-28/1223347318.PDF",
        "source_sha256": "d765c94532cd41a496d147da72cbff392bce4ff776b41b88d95dcf3f1fb697c8",
        "source_bytes": 492929,
        "equity_label_prefix": "所有者权益（或股东权益）合",
        "next_page_suffix": "计",
        "expected_next_page_head": [
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
        "equity_label_prefix": "所有者权益（或股东权",
        "next_page_suffix": "益）合计",
        "expected_next_page_head": [
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


def _norm(text: str) -> str:
    return prior_safety._normalize(text or "")


def _source_identity_from_row(row: dict[str, str]) -> tuple[str, int, str]:
    candidates = json.loads(row.get("candidate_evidence_json") or "[]")
    if row.get("document_status") == "ERROR" and row.get("tie_candidate_count") == "1" and len(candidates) == 1:
        candidate = candidates[0]
        return (
            str(candidate.get("sha256") or ""),
            int(candidate.get("bytes") or 0),
            str(candidate.get("url") or ""),
        )
    return (
        str(row.get("selected_source_sha256") or ""),
        int(row.get("selected_source_bytes") or 0),
        str(row.get("selected_source_url") or ""),
    )


def is_exact_target(announcement_id: str, economic_date: str, source_sha256: str, source_bytes: int) -> bool:
    target = TARGETS.get(str(announcement_id))
    if target is None:
        return False
    return (
        str(economic_date) == target["economic_date"]
        and str(source_sha256) == target["source_sha256"]
        and int(source_bytes) == int(target["source_bytes"])
    )


def build_full_population_routing(documents: Path) -> dict[str, Any]:
    if sha256_file(documents) != SOURCE_DOCUMENTS_GZIP_SHA256:
        raise ValueError("accepted V17.29 documents gzip SHA drift")
    if sha256_gzip_plaintext(documents) != SOURCE_DOCUMENTS_PLAINTEXT_SHA256:
        raise ValueError("accepted V17.29 documents plaintext SHA drift")

    input_rows = 0
    candidate_rows: list[dict[str, Any]] = []
    with gzip.open(documents, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            input_rows += 1
            aid = str(row.get("announcement_id") or "")
            sha, size, url = _source_identity_from_row(row)
            if is_exact_target(aid, str(row.get("economic_date") or ""), sha, size):
                candidate_rows.append({
                    "announcement_id": aid,
                    "economic_date": str(row.get("economic_date") or ""),
                    "source_sha256": sha,
                    "source_bytes": size,
                    "source_url": url,
                    "document_status": str(row.get("document_status") or ""),
                    "document_error": str(row.get("document_error") or ""),
                })

    candidate_rows.sort(key=lambda x: x["announcement_id"])
    if input_rows != 121354:
        raise ValueError(f"accepted V17.29 document population changed {input_rows}")
    if [x["announcement_id"] for x in candidate_rows] != sorted(TARGETS):
        raise ValueError(f"exact target routing drift {candidate_rows}")
    if any(x["source_url"] != TARGETS[x["announcement_id"]]["source_url"] for x in candidate_rows):
        raise ValueError("target source URL drift")
    if any(x["document_status"] != "ERROR" or "NO_VALIDATED_BALANCE_SHEET_BLOCK" not in x["document_error"] for x in candidate_rows):
        raise ValueError("target is no longer the expected fail-closed residual")

    return {
        "input_document_rows": input_rows,
        "candidate_route_count": len(candidate_rows),
        "formal_v17_29_delegate_count": input_rows - len(candidate_rows),
        "candidate_route_announcement_ids": [x["announcement_id"] for x in candidate_rows],
        "candidate_rows": candidate_rows,
    }


def fetch_exact_pdf(target: dict[str, Any]) -> bytes:
    response = requests.get(target["source_url"], timeout=45, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    raw = response.content
    if len(raw) != int(target["source_bytes"]):
        raise ValueError(f"exact source byte drift expected={target['source_bytes']} actual={len(raw)}")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != target["source_sha256"]:
        raise ValueError(f"exact source SHA drift expected={target['source_sha256']} actual={digest}")
    if not raw.startswith(b"%PDF"):
        raise ValueError("exact source is not a PDF")
    return raw


def _event_key(event: dict[str, Any]) -> tuple[int, str, str]:
    return (int(event.get("page") or 0), str(event.get("role") or ""), str(event.get("line") or ""))


def _find_cross_page_equity(
    rows_by_page: dict[int, list[dict[str, Any]]],
    events: list[dict[str, Any]],
    target: dict[str, Any],
) -> dict[str, Any]:
    prefix = _norm(target["equity_label_prefix"])
    suffix = _norm(target["next_page_suffix"])
    full = _norm(FULL_EQUITY_ALIAS)
    if prefix + suffix != full:
        raise ValueError("configured prefix+suffix is not exact full equity alias")

    matches: list[dict[str, Any]] = []
    for page, rows in rows_by_page.items():
        for row in rows:
            pair = prior_safety._amount_pair(row, target["values"]["TOTAL_EQUITY"])
            if pair is None:
                continue
            text = _norm(str(row.get("text") or ""))
            if not text.startswith(prefix):
                continue
            event = prior_safety._bind(events, page, row)
            if not event or event.get("role") != "GROUP" or "合并资产负债表" not in str(event.get("line") or ""):
                continue
            header = prior_safety._validate_header(rows_by_page, event, target)
            next_rows = rows_by_page.get(page + 1, [])
            actual_head = [str(x.get("text") or "") for x in next_rows[: len(target["expected_next_page_head"])]]
            if [_norm(x) for x in actual_head] != [_norm(x) for x in target["expected_next_page_head"]]:
                continue
            if _norm(actual_head[1]) != suffix:
                continue
            if _norm(str(row.get("text") or "")).find(prefix) != 0:
                continue
            if _norm(actual_head[1]) + "" == "":
                continue
            matches.append({
                "page": page,
                "next_page": page + 1,
                "row": row,
                "pair": pair,
                "event": event,
                "header": header,
                "equity_label_prefix": target["equity_label_prefix"],
                "next_page_exact_suffix": target["next_page_suffix"],
                "completed_equity_alias": FULL_EQUITY_ALIAS,
                "next_page_head": actual_head,
                "next_statement_title": target["next_statement_title"],
            })
    if len(matches) != 1:
        raise ValueError(f"cross-page exact equity sequence expected=1 actual={len(matches)}")
    match = matches[0]
    next_text = [_norm(x) for x in match["next_page_head"]]
    if not any(_norm(target["next_statement_title"]) in x for x in [_norm(str(r.get("text") or "")) for r in rows_by_page.get(match["next_page"], [])[:12]]):
        raise ValueError("expected next statement boundary missing from next-page head")
    return match


def recover_exact_target(raw: bytes, target: dict[str, Any]) -> dict[str, Any]:
    current = formal.parse_pdf_bytes(raw, target["economic_date"])
    validation = list(current.get("validation_errors") or [])
    if int(current.get("tier2_found") or 0) != 3 or "NO_VALIDATED_BALANCE_SHEET_BLOCK" not in validation:
        raise ValueError("formal V17.29 no longer fails closed as expected")

    with fitz.open(stream=raw, filetype="pdf") as doc:
        events = blocks.formal_statement_events(doc)
        rows_by_page = prior_safety._rows_by_page(doc)
        found = {
            "TOTAL_ASSETS": prior_safety._find_exact_labeled(rows_by_page, events, target, "TOTAL_ASSETS"),
            "TOTAL_LIABILITIES": prior_safety._find_exact_labeled(rows_by_page, events, target, "TOTAL_LIABILITIES"),
            "TOTAL_EQUITY": _find_cross_page_equity(rows_by_page, events, target),
        }
        keys = {_event_key(found[c]["event"]) for c in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")}
        if len(keys) != 1:
            raise ValueError(f"A/L/E do not bind to one GROUP event {keys}")
        alignment = prior_safety._validate_alignment(found)
        identity = prior_safety._validate_identity(target)

    if any(Decimal(x["identity_residual_cny"]) != 0 for x in identity["columns"]):
        raise ValueError("candidate requires exact zero dual-column identity")

    observations: dict[str, Any] = {}
    for concept in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"):
        row = found[concept]
        observations[concept] = {
            "status": "FOUND",
            "normalized_cny_value": target["values"][concept][0],
            "prior_cny_value": target["values"][concept][1],
            "page": int(row["page"]),
            "matched_alias": FULL_EQUITY_ALIAS if concept == "TOTAL_EQUITY" else prior_safety.TARGET_ALIASES[concept],
            "exact_source_only": True,
        }

    return {
        "formal_v17_29_snapshot": {
            "parser_version": current.get("parser_version"),
            "tier1_found": current.get("tier1_found"),
            "tier2_found": current.get("tier2_found"),
            "validation_errors": validation,
            "balance_sheet_block": current.get("balance_sheet_block"),
        },
        "candidate_recovery": {
            "method": METHOD,
            "observations": observations,
            "statement_event": found["TOTAL_EQUITY"]["event"],
            "header_context": found["TOTAL_EQUITY"]["header"],
            "column_alignment": alignment,
            "dual_column_identity": identity,
            "cross_page_pattern": {
                "equity_amount_page": int(found["TOTAL_EQUITY"]["page"]),
                "suffix_page": int(found["TOTAL_EQUITY"]["next_page"]),
                "equity_label_prefix": found["TOTAL_EQUITY"]["equity_label_prefix"],
                "next_page_exact_suffix": found["TOTAL_EQUITY"]["next_page_exact_suffix"],
                "completed_equity_alias": found["TOTAL_EQUITY"]["completed_equity_alias"],
                "next_page_head": found["TOTAL_EQUITY"]["next_page_head"],
                "next_statement_title": found["TOTAL_EQUITY"]["next_statement_title"],
            },
            "candidate_only": True,
            "formal_parser_changed": False,
            "runtime_authority_changed": False,
            "production_data_changed": False,
            "candidate_parser_promotion_authorized": False,
            "ocr_used": False,
            "fuzzy_alias_matching_used": False,
            "equity_inferred_as_assets_minus_liabilities": False,
            "accounting_tolerance_relaxed": False,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--documents", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    eligible = evidence["cross_page_exact_source_candidates"]
    if [x["announcement_id"] for x in eligible] != sorted(TARGETS):
        raise ValueError("governance eligible target set drift")
    if evidence["classification_result"]["candidate_parser_implementation_authorized"] is not False:
        raise ValueError("governance unexpectedly authorizes parser implementation")

    routing = build_full_population_routing(Path(args.documents))
    recoveries: list[dict[str, Any]] = []
    for aid in sorted(TARGETS):
        target = TARGETS[aid]
        raw = fetch_exact_pdf(target)
        recovered = recover_exact_target(raw, target)
        recoveries.append({
            "announcement_id": aid,
            "source_code": target["source_code"],
            "economic_date": target["economic_date"],
            "source_url": target["source_url"],
            "source_sha256": target["source_sha256"],
            "source_bytes": target["source_bytes"],
            **recovered,
        })

    mutation_checks = []
    for aid, target in sorted(TARGETS.items()):
        mutation_checks.append({
            "announcement_id": aid,
            "wrong_sha_delegates": not is_exact_target(aid, target["economic_date"], "0" * 64, target["source_bytes"]),
            "wrong_bytes_delegates": not is_exact_target(aid, target["economic_date"], target["source_sha256"], target["source_bytes"] + 1),
            "wrong_date_delegates": not is_exact_target(aid, "1900-01-01", target["source_sha256"], target["source_bytes"]),
        })
    if not all(all(row[k] for k in ("wrong_sha_delegates", "wrong_bytes_delegates", "wrong_date_delegates")) for row in mutation_checks):
        raise ValueError("mutated target identity did not delegate")

    report = {
        "gate": "S3G1J_V17_29_TWO_TARGET_CROSS_PAGE_CANDIDATE_SAFETY_V1",
        "method": METHOD,
        "source_run": SOURCE_RUN,
        "source_artifact_id": SOURCE_ARTIFACT_ID,
        "source_artifact_digest": SOURCE_ARTIFACT_DIGEST,
        "routing": routing,
        "recoveries": recoveries,
        "mutation_delegation_checks": mutation_checks,
        "candidate_experiment_pass": True,
        "candidate_parser_implementation_authorized": False,
        "candidate_parser_promotion_authorized": False,
        "formal_parser_changed": False,
        "runtime_authority_changed": False,
        "production_data_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_live_locked": True,
        "main_changed": False,
        "errors": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "gate": report["gate"],
        "routing": routing,
        "recoveries": [
            {
                "announcement_id": x["announcement_id"],
                "formal_validation_errors": x["formal_v17_29_snapshot"]["validation_errors"],
                "cross_page_pattern": x["candidate_recovery"]["cross_page_pattern"],
                "dual_column_identity": x["candidate_recovery"]["dual_column_identity"],
            }
            for x in recoveries
        ],
        "candidate_experiment_pass": True,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
