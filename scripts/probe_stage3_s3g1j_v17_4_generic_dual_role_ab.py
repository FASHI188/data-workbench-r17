#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from contextlib import contextmanager
from pathlib import Path

import fitz
import requests

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_statement_blocks_v16_5 as blocks
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard
from stage3_financial_spatial_alias_v16_7 import diagnose_spatial_balance_sheet_v16_7

TARGET_CATEGORY = "NO_FORMAL_GROUP_EVENT"
GENERIC_PREFIXES = ("", "未经审计")


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def _download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.4-generic-dual-role-ab",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def _is_generic_balance_heading(text: str) -> bool:
    compact = _norm(text)
    compact = re.sub(r"(?:（续）|\(续\)|-续|续)$", "", compact)
    compact = compact.strip("：:、，,。.;；")
    compact = re.sub(r"^20\d{2}年\d{1,2}月\d{1,2}日", "", compact)
    compact = re.sub(r"^(?:\d{1,2}|[一二三四五六七八九十]+)[、.．:：)]", "", compact)
    for prefix in GENERIC_PREFIXES:
        if compact == f"{prefix}资产负债表":
            return True
    return False


def _promotable_events(doc: fitz.Document) -> list[dict]:
    promoted = []
    for pno in range(doc.page_count):
        split = v14._page_role_split(doc[pno])
        if split is None:
            continue
        for row in v14._rows_from_words(doc[pno]):
            if not _is_generic_balance_heading(row["text"]):
                continue
            occurrences = blocks._title_occurrences(row)
            unknown = [o for o in occurrences if o.get("role") == "UNKNOWN_STATEMENT"]
            if not unknown:
                # `未经审计资产负债表` can still expose the exact inner generic
                # phrase through occurrence parsing even when string classification
                # does not accept the decorated row. Fail closed if no occurrence.
                continue
            occurrence = unknown[0]
            promoted.append({
                "page": pno + 1,
                "y": float(row["y"]),
                "x0": float(occurrence["x0"]),
                "x1": float(occurrence["x1"]),
                "x_center": float(occurrence["x_center"]),
                "role": "DUAL_GROUP_PARENT",
                "continuation": bool(re.search(r"(?:（续）|\(续\)|-续|续)\s*$", row["text"])),
                "line": row["text"].strip(),
                "matched_title": "GENERIC_BALANCE_SHEET_WITH_EXPLICIT_DUAL_ROLE_HEADERS",
                "role_header_evidence": {
                    "group_header_x": str(split["group_header_x"]),
                    "parent_header_x": str(split["parent_header_x"]),
                    "split_x": str(split["split_x"]),
                },
            })
    return promoted


def _same_location(a: dict, b: dict) -> bool:
    return (
        int(a["page"]) == int(b["page"])
        and abs(float(a["y"]) - float(b["y"])) <= 0.5
        and abs(float(a.get("x_center", 0)) - float(b.get("x_center", 0))) <= 2.0
    )


def _events_with_promotions(doc: fitz.Document, original_fn) -> tuple[list[dict], list[dict]]:
    original = list(original_fn(doc))
    promoted = _promotable_events(doc)
    if not promoted:
        return original, promoted
    kept = [
        event for event in original
        if not (
            event.get("role") == "UNKNOWN_STATEMENT"
            and any(_same_location(event, p) for p in promoted)
        )
    ]
    kept.extend(promoted)
    kept.sort(key=lambda e: (int(e["page"]), float(e["y"]), float(e["x0"])))
    return kept, promoted


@contextmanager
def _temporary_role_promotion(doc: fitz.Document):
    original_fn = blocks.formal_statement_events
    prepared_events, promoted = _events_with_promotions(doc, original_fn)

    def patched(target_doc: fitz.Document):
        if target_doc is not doc:
            return original_fn(target_doc)
        return prepared_events

    blocks.formal_statement_events = patched
    try:
        yield promoted
    finally:
        blocks.formal_statement_events = original_fn


def _selected_summary(diag: dict) -> dict:
    return {
        concept: {
            "value": item.get("value"),
            "raw_value": item.get("raw_value"),
            "unit": item.get("unit"),
            "page": item.get("page"),
            "alias": item.get("alias"),
            "statement_role": item.get("statement_role"),
            "period_evidence": item.get("period_evidence"),
        }
        for concept, item in (diag.get("selected") or {}).items()
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--v17-summary", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    summary = json.loads(Path(args.v17_summary).read_text(encoding="utf-8"))
    if not summary.get("pass") or int(summary.get("input_residual_count", -1)) != 91:
        raise ValueError("V17 summary is not the accepted exact-91 funnel")
    target_ids = sorted(
        str(item["announcement_id"])
        for item in summary.get("diagnostics") or []
        if item.get("category") == TARGET_CATEGORY
    )
    if len(target_ids) != 17:
        raise ValueError(f"expected exact 17 NO_FORMAL_GROUP_EVENT targets, got {len(target_ids)}")

    versions = _read_versions(Path(args.versions))
    session = requests.Session()
    rows = []
    errors = []
    promoted_doc_count = 0
    recovered_ids = []

    for idx, aid in enumerate(target_ids, 1):
        version = versions[aid]
        record = {
            "announcement_id": aid,
            "source_code": version["source_code"],
            "report_family": version["report_family"],
            "economic_date": version["economic_date"],
            "canonical_title": version["canonical_title"],
        }
        try:
            raw = _download(session, version["canonical_source_url"])
            record["sha256"] = hashlib.sha256(raw).hexdigest()
            with fitz.open(stream=raw, filetype="pdf") as doc:
                with _mupdf_diagnostic_guard():
                    baseline = diagnose_spatial_balance_sheet_v16_7(doc, version["economic_date"])
                    if baseline.get("recovered"):
                        raise AssertionError("accepted V17 residual unexpectedly recovered on baseline")
                    with _temporary_role_promotion(doc) as promotions:
                        promoted = diagnose_spatial_balance_sheet_v16_7(doc, version["economic_date"])
            if promotions:
                promoted_doc_count += 1
            if promoted.get("recovered"):
                recovered_ids.append(aid)
            record.update({
                "promotion_count": len(promotions),
                "promotions": promotions,
                "baseline_candidate_counts": baseline.get("candidate_counts") or {},
                "baseline_funnel": baseline.get("funnel") or {},
                "promoted_recovered": bool(promoted.get("recovered")),
                "promoted_candidate_counts": promoted.get("candidate_counts") or {},
                "promoted_funnel": promoted.get("funnel") or {},
                "promoted_identity": promoted.get("identity"),
                "promoted_selected": _selected_summary(promoted),
                "promoted_column_role_gate": promoted.get("column_role_gate"),
            })
        except Exception as exc:
            record["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        rows.append(record)
        print(f"V17_4_GENERIC_DUAL_ROLE_AB {idx}/17 aid={aid}", flush=True)

    report = {
        "gate": "S3G1J_V17_4_GENERIC_DUAL_ROLE_AB_DIAGNOSTIC",
        "diagnostic_pass": not errors and len(rows) == 17,
        "sample_count": len(rows),
        "promoted_document_count": promoted_doc_count,
        "recovered_count": len(recovered_ids),
        "recovered_ids": recovered_ids,
        "rows": rows,
        "policy": {
            "diagnostic_only": True,
            "parser_policy_changed": False,
            "promotion_rule": "generic or unaudited generic balance-sheet heading plus same-page V14 dual group/parent role-header split",
            "accounting_tolerance_changed": False,
            "period_gate_changed": False,
            "column_gate_changed": False,
            "source_policy_changed": False,
            "stage4_alpha_locked": True,
        },
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "promoted_document_count": promoted_doc_count,
        "recovered_count": len(recovered_ids),
        "recovered_ids": recovered_ids,
        "errors": errors,
        "diagnostic_pass": report["diagnostic_pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["diagnostic_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
