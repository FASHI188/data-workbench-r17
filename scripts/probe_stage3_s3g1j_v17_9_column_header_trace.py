#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from pathlib import Path

import fitz
import requests

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16_3 as v166
import stage3_financial_spatial_alias_v16_7 as v167
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard

TARGET_CATEGORY = "COLUMN_ROLE_GATE"
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.9-column-header-trace",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def canonical_expected_cn(expected: str) -> str:
    y, m, d = v166._canonical_economic_date(expected).split("-")
    return f"{int(y)}年{int(m)}月{int(d)}日"


def row_header_diagnostic(row: dict, expected: str, alias_x1: float) -> dict:
    dates_all = v167._date_geometries(row)
    dates_right = [d for d in dates_all if float(d["x_center"]) >= float(alias_x1) - 5.0]
    compact = re.sub(r"\s+", "", row.get("text") or "")
    expected_canonical = v166._canonical_economic_date(expected)
    expected_cn = canonical_expected_cn(expected)
    blockers = [token for token in v167.HEADER_BLOCKERS if token in compact]
    structural_tokens = [token for token in v167.HEADER_TOKENS if token in compact]
    structural = bool(len(dates_right) >= 2 or compact == expected_cn or structural_tokens)
    expected_all = [d for d in dates_all if d["date"] == expected_canonical]
    expected_right = [d for d in dates_right if d["date"] == expected_canonical]
    qualified = v167._qualified_header_row(row, expected_canonical, alias_x1)
    return {
        "row_y": float(row["y"]),
        "row_text": row["text"][:1200],
        "compact_text": compact[:1200],
        "dates_all": dates_all,
        "dates_right_of_alias": dates_right,
        "expected_date_anywhere": bool(expected_all),
        "expected_date_right_of_alias": bool(expected_right),
        "expected_date_geometries": expected_all,
        "header_blockers": blockers,
        "structural_tokens": structural_tokens,
        "structural_rule_pass": structural,
        "qualified_by_current_rule": qualified is not None,
        "qualified_expected_column_index": None if qualified is None else int(qualified[1]),
    }


def page_contains_expected(page: fitz.Page, expected: str) -> bool:
    compact = re.sub(r"\s+", "", page.get_text("text") or "")
    return canonical_expected_cn(expected) in compact


def candidate_trace(
    doc: fitz.Document,
    rows_by_page: dict[int, list[dict]],
    expected_pages: list[int],
    concept: str,
    candidate: dict,
    expected: str,
) -> dict:
    current_page = int(candidate["page"])
    anchor_page = int(candidate["statement_anchor_page"])
    unit_evidence = candidate.get("unit_evidence") or {}
    root_page = int(unit_evidence.get("root_page") or anchor_page)
    alias_x1 = float(candidate["alias_x1"])
    scan_start = max(1, root_page)
    scan_end = current_page

    found = v167._find_candidate_row(doc, candidate)
    candidate_row = None
    if found is not None:
        candidate_row = {
            "row_y": float(found["row"]["y"]),
            "row_text": found["row"]["text"][:1600],
            "alias_geometry": {"x0": float(found["geom"]["x0"]), "x1": float(found["geom"]["x1"])},
            "amounts_after_alias": [
                {"raw": str(a["raw"]), "value": str(a["value"]), "x0": float(a["x0"])}
                for a in (found.get("amounts") or [])
            ],
        }

    current_column_evidence = v167.column_role_evidence(doc, candidate, expected)
    current_header = v167._find_header_column_evidence(doc, candidate, expected)
    inspection_pages = set(expected_pages)
    start = max(1, min(root_page, anchor_page) - 3)
    end = min(doc.page_count, current_page + 2)
    inspection_pages.update(range(start, end + 1))

    page_rows = []
    outside = []
    for page_1b in sorted(inspection_pages):
        diagnostics = []
        for row in rows_by_page.get(page_1b, []):
            d = row_header_diagnostic(row, expected, alias_x1)
            if not d["dates_all"]:
                continue
            diagnostics.append(d)
            if d["expected_date_anywhere"] and not (scan_start <= page_1b <= scan_end):
                outside.append({"page": page_1b, **d})
        if diagnostics:
            page_rows.append({
                "page": page_1b,
                "inside_current_header_scan_range": scan_start <= page_1b <= scan_end,
                "rows_with_dates": diagnostics,
            })

    return {
        "concept": concept,
        "candidate": {
            "value": candidate.get("value"),
            "raw_value": candidate.get("raw_value"),
            "unit": candidate.get("unit"),
            "page": current_page,
            "alias": candidate.get("alias"),
            "alias_x0": candidate.get("alias_x0"),
            "alias_x1": candidate.get("alias_x1"),
            "value_x": candidate.get("value_x"),
            "statement_anchor_page": anchor_page,
            "statement_anchor_y": candidate.get("statement_anchor_y"),
            "statement_anchor_x": candidate.get("statement_anchor_x"),
            "statement_role": candidate.get("statement_role"),
            "statement_title": candidate.get("statement_title"),
            "statement_title_line": candidate.get("statement_title_line"),
            "unit_evidence": unit_evidence,
            "period_evidence": candidate.get("period_evidence"),
            "row_text": candidate.get("row_text"),
        },
        "current_header_scan_range": {"start_page": scan_start, "end_page": scan_end},
        "candidate_row_reconstruction": candidate_row,
        "current_header_evidence": current_header,
        "current_column_role_evidence": current_column_evidence,
        "expected_date_pages_in_document": expected_pages,
        "page_date_diagnostics": page_rows,
        "expected_date_rows_outside_current_scan_range": outside[:100],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--v17-8-summary", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    summary = json.loads(Path(args.v17_8_summary).read_text(encoding="utf-8"))
    if not summary.get("pass") or int(summary.get("input_residual_count", -1)) != 88:
        raise ValueError("V17.8 summary is not the accepted exact-88 diagnostic")
    if int(summary.get("accepted_v17_7_recovery_count", -1)) != 25:
        raise ValueError("V17.8 is not anchored to accepted V17.7=25")
    if summary.get("stage4_alpha_locked") is not True:
        raise ValueError("Stage4/Alpha lock missing")

    targets = {
        str(item["announcement_id"]): item
        for item in summary.get("diagnostics") or []
        if item.get("category") == TARGET_CATEGORY
    }
    if len(targets) != 6:
        raise ValueError(f"expected exact 6 COLUMN_ROLE_GATE residuals, got {len(targets)}")

    versions = read_versions(Path(args.versions))
    missing = sorted(set(targets) - set(versions))
    if missing:
        raise ValueError(f"target ids missing from frozen versions: {missing}")

    session = requests.Session()
    records = []
    errors = []

    for idx, aid in enumerate(sorted(targets), 1):
        version = versions[aid]
        record = {
            "announcement_id": aid,
            "source_code": version["source_code"],
            "report_family": version["report_family"],
            "economic_date": version["economic_date"],
            "canonical_title": version["canonical_title"],
            "v17_8_category": targets[aid]["category"],
            "v17_8_candidate_counts": targets[aid].get("candidate_counts") or {},
        }
        try:
            raw = download(session, version["canonical_source_url"])
            record["sha256"] = hashlib.sha256(raw).hexdigest()
            with fitz.open(stream=raw, filetype="pdf") as doc:
                with _mupdf_diagnostic_guard():
                    page_count = doc.page_count
                    parsed_v166 = v166.diagnose_spatial_balance_sheet_v16_6(doc, version["economic_date"])
                    if not parsed_v166.get("recovered"):
                        raise AssertionError("COLUMN_ROLE_GATE target no longer reaches V16.6 recovery")
                    selected = parsed_v166.get("selected") or {}
                    if set(selected) != set(CONCEPTS):
                        raise AssertionError(f"selected concepts mismatch: {sorted(selected)}")

                    expected_pages = [
                        page_1b for page_1b in range(1, page_count + 1)
                        if page_contains_expected(doc[page_1b - 1], version["economic_date"])
                    ]
                    inspection_pages = set(expected_pages)
                    for candidate in selected.values():
                        current = int(candidate["page"])
                        anchor = int(candidate["statement_anchor_page"])
                        root = int((candidate.get("unit_evidence") or {}).get("root_page") or anchor)
                        inspection_pages.update(
                            range(max(1, min(root, anchor) - 3), min(page_count, current + 2) + 1)
                        )
                    rows_by_page = {
                        page_1b: v14._rows_from_words(doc[page_1b - 1])
                        for page_1b in sorted(inspection_pages)
                    }
                    concept_traces = {
                        concept: candidate_trace(
                            doc, rows_by_page, expected_pages, concept, selected[concept], version["economic_date"]
                        )
                        for concept in CONCEPTS
                    }
                    current_v167 = v167.diagnose_spatial_balance_sheet_v16_7(doc, version["economic_date"])
                    if current_v167.get("recovered"):
                        raise AssertionError("accepted V17.8 COLUMN_ROLE_GATE residual unexpectedly recovered")
                    record.update({
                        "page_count": page_count,
                        "v16_6_identity": parsed_v166.get("identity"),
                        "v16_6_funnel": parsed_v166.get("funnel") or {},
                        "expected_date_pages_in_document": expected_pages,
                        "concept_traces": concept_traces,
                        "current_v16_7_column_role_gate": current_v167.get("column_role_gate"),
                    })
        except Exception as exc:
            record["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        records.append(record)
        print(f"V17_9_COLUMN_HEADER_TRACE {idx}/6 aid={aid}", flush=True)

    report = {
        "gate": "S3G1J_V17_9_EXACT6_COLUMN_HEADER_TRACE",
        "diagnostic_pass": not errors and len(records) == 6,
        "sample_count": len(records),
        "accepted_v17_7_recovery_count": 25,
        "v17_8_remaining_count": 88,
        "target_category": TARGET_CATEGORY,
        "records": records,
        "policy": {
            "diagnostic_only": True,
            "parser_policy_changed": False,
            "column_gate_changed": False,
            "accounting_tolerance_changed": False,
            "source_policy_changed": False,
            "stage4_alpha_locked": True,
        },
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "sample_count": len(records),
        "errors": errors,
        "diagnostic_pass": report["diagnostic_pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["diagnostic_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
