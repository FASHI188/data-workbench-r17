#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

import fitz
import requests

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16_3 as v166
import stage3_financial_spatial_alias_v16_7 as v167
import stage3_financial_spatial_alias_v17_15 as v1715
import stage3_financial_spatial_alias_v17_17 as v1717
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard

TARGET_ID = "1212731093"


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def download(url: str) -> bytes:
    response = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.17-header-geometry-diagnostic",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def num_rows(row: dict) -> list[dict]:
    return [
        {"raw": str(x.get("raw")), "value": str(x.get("value")), "x0": str(x.get("x0"))}
        for x in v14._numeric_word_candidates(row)
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--acceptance", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    accepted = json.loads(Path(args.acceptance).read_text(encoding="utf-8"))
    accepted_rows = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if not accepted.get("pass") or TARGET_ID not in accepted_rows:
        raise ValueError("not the accepted V17.11 source state")
    version = read_versions(Path(args.versions))[TARGET_ID]
    raw = download(version["canonical_source_url"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != accepted_rows[TARGET_ID]["sha256"]:
        raise ValueError("source SHA changed")

    errors: list[str] = []
    pages: list[dict] = []
    candidates: list[dict] = []
    with _mupdf_diagnostic_guard():
        with fitz.open(stream=raw, filetype="pdf") as doc:
            existing, _ = v166._collect_candidates_v16_6(doc, version["economic_date"])
            bridge, _ = v1715._collect_adjacent_bridge_candidates(doc, version["economic_date"])
            strict, strict_funnel = v1717._collect_strict_same_row_equity_candidates(
                doc, version["economic_date"]
            )
            by_concept = {
                "TOTAL_ASSETS": list(existing.get("TOTAL_ASSETS", [])) + list(bridge.get("TOTAL_ASSETS", [])),
                "TOTAL_LIABILITIES": list(existing.get("TOTAL_LIABILITIES", [])) + list(bridge.get("TOTAL_LIABILITIES", [])),
                "TOTAL_EQUITY": strict,
            }
            for concept, rows in by_concept.items():
                for candidate in rows:
                    direct = v1715._direct_column_evidence(doc, candidate, version["economic_date"])
                    candidates.append({
                        "concept": concept,
                        "page": candidate.get("page"),
                        "alias": candidate.get("alias"),
                        "alias_x0": str(candidate.get("alias_x0")),
                        "alias_x1": str(candidate.get("alias_x1")),
                        "value_x": str(candidate.get("value_x")),
                        "raw_value": str(candidate.get("raw_value")),
                        "statement_anchor_page": candidate.get("statement_anchor_page"),
                        "statement_role": candidate.get("statement_role"),
                        "row_text": candidate.get("row_text"),
                        "period_evidence": candidate.get("period_evidence"),
                        "direct_column_evidence": direct,
                    })
            relevant_pages = sorted({
                int(candidate.get("page") or 0) for rows in by_concept.values() for candidate in rows
            } | {
                int(candidate.get("statement_anchor_page") or 0) for rows in by_concept.values() for candidate in rows
            })
            relevant_pages = [p for p in relevant_pages if p > 0]
            scan_pages = list(range(max(1, min(relevant_pages) - 1), min(doc.page_count, max(relevant_pages) + 1) + 1))
            for page_1b in scan_pages:
                page = doc[page_1b - 1]
                row_records = []
                for index, row in enumerate(v14._rows_from_words(page)):
                    row_records.append({
                        "row_index": index,
                        "y": float(row["y"]),
                        "text": str(row.get("text") or "")[:1600],
                        "date_geometries": v167._date_geometries(row),
                        "numeric_candidates": num_rows(row),
                    })
                pages.append({
                    "page": page_1b,
                    "text_chars": len((page.get_text("text") or "").strip()),
                    "word_count": len(page.get_text("words") or []),
                    "rows": row_records,
                })

    report = {
        "gate": "S3G1J_V17_17_EXACT_ONE_HEADER_GEOMETRY_DIAGNOSTIC",
        "pass": not errors,
        "diagnostic_only": True,
        "no_parser_change": True,
        "no_value_acceptance": True,
        "no_column_gate_bypass": True,
        "announcement_id": TARGET_ID,
        "source_code": version["source_code"],
        "economic_date": version["economic_date"],
        "source_sha256": digest,
        "strict_funnel": strict_funnel,
        "candidates": candidates,
        "pages": pages,
        "accounting_tolerance_changed": False,
        "source_policy_changed": False,
        "stage4_alpha_locked": True,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "announcement_id": TARGET_ID,
        "candidate_count": len(candidates),
        "scan_pages": [row["page"] for row in pages],
        "pass": report["pass"],
        "errors": errors,
    }, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
