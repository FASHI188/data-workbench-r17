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

import extract_stage3_financial_pdf_values as base
import stage3_financial_pdf_parser as parser_base
import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_pdf_parser_v8 as v13
import stage3_financial_spatial_alias_v16 as spatial
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard

TARGET_IDS = {"1212731093", "1217717273", "1225153907", "1219411922"}
CONCEPTS = {
    "TOTAL_ASSETS": parser_base.TIER1_ALIASES.get("TOTAL_ASSETS") or [],
    "TOTAL_LIABILITIES": parser_base.TIER2_ALIASES.get("TOTAL_LIABILITIES") or [],
    "TOTAL_EQUITY": parser_base.TIER2_ALIASES.get("TOTAL_EQUITY") or [],
}
Y_TOLERANCES = (2.0, 4.0, 8.0, 12.0, 20.0)


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.14-adjacent-row-diagnostic",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def page_word_dicts(page: fitz.Page) -> list[dict]:
    out = []
    for item in page.get_text("words") or []:
        x0, y0, x1, y1, text = item[:5]
        out.append({
            "x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1),
            "text": str(text), "y_center": (float(y0) + float(y1)) / 2,
        })
    return out


def numeric_records(row: dict) -> list[dict]:
    return [
        {"raw": str(x.get("raw")), "value": str(x.get("value")), "x0": str(x.get("x0")), "x1": str(x.get("x1"))}
        for x in sorted(v14._numeric_word_candidates(row), key=lambda x: x["x0"])
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--announcement-id", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    aid = str(args.announcement_id)
    if aid not in TARGET_IDS:
        raise ValueError(f"diagnostic frozen to {sorted(TARGET_IDS)}")
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    upstream = {str(x["announcement_id"]): x for x in summary.get("diagnostics") or []}
    target_set = {x for x, row in upstream.items() if row.get("category") == "MISSING_CONCEPT_NO_RIGHT_AMOUNT"}
    if not summary.get("pass") or target_set != TARGET_IDS:
        raise ValueError("not the accepted exact-four no-right-amount state")
    versions = read_versions(Path(args.versions))
    version = versions[aid]
    expected = upstream[aid]
    missing = sorted(c for c, stage in expected["concept_stage"].items() if stage == "NO_RIGHT_AMOUNT")

    raw = download(requests.Session(), version["canonical_source_url"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected["sha256"]:
        raise ValueError(f"source SHA changed {aid}")

    alias_records: list[dict] = []
    with _mupdf_diagnostic_guard():
        with fitz.open(stream=raw, filetype="pdf") as doc:
            events = v14._statement_events(doc)
            for pno in range(doc.page_count):
                rows = sorted(v14._rows_from_words(doc[pno]), key=lambda x: float(x["y"]))
                raw_words = page_word_dicts(doc[pno])
                for row_index, row in enumerate(rows):
                    role = v14._nearest_statement_event(events, pno + 1)
                    if role is None or role.get("role") not in ("GROUP", "DUAL_GROUP_PARENT"):
                        continue
                    unit, mult, unit_page = spatial._role_unit_context(doc, role, pno)
                    for concept in missing:
                        geometries = []
                        for alias in CONCEPTS[concept]:
                            for geom in spatial._alias_geometries(row, alias, concept):
                                geometries.append((alias, geom))
                        geometries.sort(key=lambda x: (-v13._alias_strength(concept, x[0]), -len(v14._norm(x[0])), x[1]["x0"]))
                        for alias, geom in geometries:
                            current_after = [x for x in v14._numeric_word_candidates(row) if x["x0"] >= geom["x1"] - 1]
                            if current_after:
                                continue
                            neighbors = []
                            for idx in range(max(0, row_index - 5), min(len(rows), row_index + 6)):
                                nrow = rows[idx]
                                nums = numeric_records(nrow)
                                nums_right = [x for x in nums if float(x["x0"]) >= float(geom["x1"]) - 1]
                                neighbors.append({
                                    "row_index": idx,
                                    "row_offset": idx - row_index,
                                    "y": float(nrow["y"]),
                                    "y_delta": float(nrow["y"]) - float(row["y"]),
                                    "text": nrow["text"][:1200],
                                    "numeric_candidates": nums,
                                    "numeric_candidates_right_of_alias": nums_right,
                                })
                            tolerance_evidence = {}
                            for tolerance in Y_TOLERANCES:
                                words = [
                                    w for w in raw_words
                                    if abs(float(w["y_center"]) - float(row["y"])) <= tolerance
                                ]
                                words.sort(key=lambda w: (w["x0"], w["y_center"]))
                                synthetic = {
                                    "words": words,
                                    "text": " ".join(w["text"] for w in words),
                                    "y": float(row["y"]),
                                }
                                nums = numeric_records(synthetic) if words else []
                                tolerance_evidence[str(tolerance)] = {
                                    "word_count": len(words),
                                    "synthetic_text": synthetic["text"][:1600],
                                    "numeric_candidates": nums,
                                    "numeric_candidates_right_of_alias": [x for x in nums if float(x["x0"]) >= float(geom["x1"]) - 1],
                                }
                            alias_records.append({
                                "concept": concept,
                                "page": pno + 1,
                                "row_index": row_index,
                                "row_y": float(row["y"]),
                                "row_text": row["text"][:1200],
                                "alias": alias,
                                "alias_strength": v13._alias_strength(concept, alias),
                                "alias_x0": str(geom["x0"]),
                                "alias_x1": str(geom["x1"]),
                                "statement_role": role,
                                "unit": unit,
                                "unit_multiplier": str(mult) if mult is not None else None,
                                "unit_source_page": unit_page,
                                "neighbor_rows": neighbors,
                                "y_tolerance_evidence": tolerance_evidence,
                            })

    counts = {concept: sum(1 for x in alias_records if x["concept"] == concept) for concept in missing}
    recoverable_by_tolerance = {}
    for tolerance in Y_TOLERANCES:
        key = str(tolerance)
        recoverable_by_tolerance[key] = sum(
            1 for record in alias_records
            if record["y_tolerance_evidence"][key]["numeric_candidates_right_of_alias"]
        )
    errors = [f"no eligible zero-right-amount alias rows for {c}" for c, count in counts.items() if count == 0]
    report = {
        "gate": "S3G1J_V17_14_EXACT_FOUR_ADJACENT_AMOUNT_ROWS",
        "diagnostic_only": True,
        "no_parser_change": True,
        "no_value_acceptance": True,
        "no_tolerance_change": True,
        "announcement_id": aid,
        "source_code": version["source_code"],
        "report_family": version["report_family"],
        "economic_date": version["economic_date"],
        "canonical_title": version["canonical_title"],
        "canonical_source_url": version["canonical_source_url"],
        "source_sha256": digest,
        "missing_concepts": missing,
        "eligible_alias_record_count": len(alias_records),
        "per_concept_alias_record_count": counts,
        "records_with_right_amount_by_diagnostic_y_tolerance": recoverable_by_tolerance,
        "alias_records": alias_records,
        "pass": not errors,
        "stage4_alpha_locked": True,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "announcement_id", "missing_concepts", "eligible_alias_record_count",
        "per_concept_alias_record_count", "records_with_right_amount_by_diagnostic_y_tolerance", "pass", "errors",
    )}, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
