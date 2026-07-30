#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import fitz
import requests

import extract_stage3_financial_pdf_values as input_base
import stage3_financial_pdf_parser as parser_base
import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16 as spatial
import stage3_financial_statement_blocks_v16_5 as blocks
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard
from stage3_financial_spatial_alias_v16_7 import _date_geometries

TARGET_CATEGORY = "NO_FORMAL_GROUP_EVENT"
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
ROLE_TOKENS = {
    "GROUP": ("本集团", "集团"),
    "PARENT": ("本公司", "本行", "母公司", "公司"),
}
TITLE_HINTS = (
    "资产负债表",
    "资产及负债表",
    "财务状况表",
    "balance sheet",
    "statement of financial position",
    "statement of financial condition",
)


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def _download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.3-role-header-geometry",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def _title_like(row_text: str) -> bool:
    n = _norm(row_text)
    return any(_norm(h) in n for h in TITLE_HINTS)


def _role_header_words(page: fitz.Page) -> dict:
    words = page.get_text("words", sort=True) or []
    out = {"GROUP": [], "PARENT": []}
    for word in words:
        if len(word) < 5:
            continue
        text = str(word[4]).strip()
        token = _norm(text)
        if not token:
            continue
        x0, y0, x1, y1 = map(float, word[:4])
        for role, labels in ROLE_TOKENS.items():
            if token in {_norm(label) for label in labels}:
                out[role].append({
                    "text": text,
                    "x0": x0,
                    "x1": x1,
                    "x_center": (x0 + x1) / 2,
                    "y0": y0,
                    "y1": y1,
                })
    for role in out:
        out[role].sort(key=lambda item: (item["y0"], item["x0"]))
    return out


def _role_geometry(page: fitz.Page) -> dict:
    headers = _role_header_words(page)
    groups = headers["GROUP"]
    parents = headers["PARENT"]
    split = v14._page_role_split(page)
    return {
        "group_headers": groups,
        "parent_headers": parents,
        "group_header_count": len(groups),
        "parent_header_count": len(parents),
        "v14_page_role_split": None if split is None else {k: str(v) for k, v in split.items()},
        "has_dual_role_headers": bool(groups and parents and split is not None),
        "has_group_header_only": bool(groups and not parents),
    }


def _alias_rows(page: fitz.Page, pno_1b: int) -> list[dict]:
    concepts = {
        "TOTAL_ASSETS": parser_base.TIER1_ALIASES.get("TOTAL_ASSETS") or [],
        "TOTAL_LIABILITIES": parser_base.TIER2_ALIASES.get("TOTAL_LIABILITIES") or [],
        "TOTAL_EQUITY": parser_base.TIER2_ALIASES.get("TOTAL_EQUITY") or [],
    }
    out = []
    seen = set()
    for row in v14._rows_from_words(page):
        for concept, aliases in concepts.items():
            for alias in aliases:
                for geom in spatial._alias_geometries(row, alias, concept):
                    key = (concept, alias, round(float(geom["x0"]), 2), round(float(row["y"]), 2))
                    if key in seen:
                        continue
                    seen.add(key)
                    nums = [
                        {
                            "raw": str(item.get("raw")),
                            "value": str(item.get("value")),
                            "x0": float(item.get("x0")),
                        }
                        for item in v14._numeric_word_candidates(row)
                    ]
                    out.append({
                        "page": pno_1b,
                        "concept": concept,
                        "alias": alias,
                        "alias_x0": float(geom["x0"]),
                        "alias_x1": float(geom["x1"]),
                        "row_y": float(row["y"]),
                        "row_text": row["text"][:1000],
                        "numeric_candidates": nums[:12],
                    })
    return out


def _page_evidence(doc: fitz.Document, pno: int) -> dict:
    page = doc[pno]
    rows = v14._rows_from_words(page)
    title_rows = []
    date_rows = []
    for row in rows:
        if _title_like(row["text"]):
            role, continuation = blocks.classify_formal_statement_title(row["text"])
            title_rows.append({
                "row_y": float(row["y"]),
                "row_text": row["text"][:1200],
                "string_role": role,
                "continuation": continuation,
                "current_occurrences": blocks._title_occurrences(row),
            })
        dates = _date_geometries(row)
        if dates:
            date_rows.append({
                "row_y": float(row["y"]),
                "row_text": row["text"][:1000],
                "dates": dates,
            })
    unit, mult = parser_base.detect_unit(page.get_text("text") or "")
    aliases = _alias_rows(page, pno + 1)
    geometry = _role_geometry(page)
    split_raw = geometry.get("v14_page_role_split")
    split_x = None
    if split_raw:
        try:
            split_x = float(split_raw["split_x"])
        except (TypeError, ValueError, KeyError):
            split_x = None
    if split_x is not None:
        for item in aliases:
            xs = [float(n["x0"]) for n in item["numeric_candidates"]]
            item["numeric_x_relative_to_split"] = [
                "GROUP_SIDE" if x < split_x else "PARENT_SIDE" for x in xs
            ]
    return {
        "page": pno + 1,
        "title_rows": title_rows,
        "role_geometry": geometry,
        "date_rows": date_rows[:20],
        "detected_unit": unit,
        "detected_unit_multiplier": None if mult is None else str(mult),
        "alias_rows": aliases[:100],
        "alias_concepts": sorted({item["concept"] for item in aliases}),
    }


def _classify(page_records: list[dict], candidate_pages: set[int]) -> str:
    candidate_records = [p for p in page_records if p["page"] in candidate_pages]
    nearby_records = [p for p in page_records if p["page"] not in candidate_pages]

    def has_title(rec: dict) -> bool:
        return bool(rec.get("title_rows"))

    def dual(rec: dict) -> bool:
        return bool((rec.get("role_geometry") or {}).get("has_dual_role_headers"))

    def group_only(rec: dict) -> bool:
        return bool((rec.get("role_geometry") or {}).get("has_group_header_only"))

    if any(has_title(r) and dual(r) for r in candidate_records):
        return "CANDIDATE_GENERIC_TITLE_WITH_DUAL_ROLE_HEADERS"
    if any(has_title(r) and group_only(r) for r in candidate_records):
        return "CANDIDATE_TITLE_WITH_GROUP_HEADER_ONLY"
    if any((not has_title(r)) and dual(r) for r in candidate_records):
        return "CANDIDATE_NO_TITLE_WITH_DUAL_ROLE_HEADERS"
    if any((not has_title(r)) and group_only(r) for r in candidate_records):
        return "CANDIDATE_NO_TITLE_WITH_GROUP_HEADER_ONLY"
    if any(dual(r) for r in nearby_records):
        return "DUAL_ROLE_HEADERS_ONLY_NEAR_CANDIDATE"
    if any(group_only(r) for r in nearby_records):
        return "GROUP_HEADER_ONLY_NEAR_CANDIDATE"
    if any((r.get("role_geometry") or {}).get("group_header_count", 0) or (r.get("role_geometry") or {}).get("parent_header_count", 0) for r in page_records):
        return "ROLE_HEADERS_PRESENT_BUT_GEOMETRY_AMBIGUOUS"
    return "NO_ROLE_HEADER_EVIDENCE"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--v17-summary", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    summary = json.loads(Path(args.v17_summary).read_text(encoding="utf-8"))
    if not summary.get("pass") or int(summary.get("input_residual_count", -1)) != 91:
        raise ValueError("V17 summary is not the accepted exact-91 funnel")
    targets = {
        str(item["announcement_id"]): item
        for item in summary.get("diagnostics") or []
        if item.get("category") == TARGET_CATEGORY
    }
    if len(targets) != 17:
        raise ValueError(f"expected exact 17 NO_FORMAL_GROUP_EVENT targets, got {len(targets)}")

    versions = _read_versions(Path(args.versions))
    missing = sorted(set(targets) - set(versions))
    if missing:
        raise ValueError(f"target ids missing from frozen versions: {missing}")

    session = requests.Session()
    rows = []
    errors = []
    category_counts = Counter()

    for idx, aid in enumerate(sorted(targets), 1):
        version = versions[aid]
        original = targets[aid]
        record = {
            "announcement_id": aid,
            "source_code": version["source_code"],
            "report_family": version["report_family"],
            "economic_date": version["economic_date"],
            "canonical_title": version["canonical_title"],
            "original_v17_category": original["category"],
            "original_candidate_counts": original.get("candidate_counts") or {},
        }
        try:
            raw = _download(session, version["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            with fitz.open(stream=raw, filetype="pdf") as doc:
                with _mupdf_diagnostic_guard():
                    candidate_pages0 = v14._candidate_pages(doc)
                    candidate_pages1 = {p + 1 for p in candidate_pages0}
                    inspect_pages0 = set(candidate_pages0)
                    for pno in candidate_pages0:
                        for q in range(max(0, pno - 2), min(doc.page_count, pno + 3)):
                            inspect_pages0.add(q)
                    page_records = [_page_evidence(doc, pno) for pno in sorted(inspect_pages0)]
                    category = _classify(page_records, candidate_pages1)
                    category_counts[category] += 1
                    record.update({
                        "sha256": digest,
                        "page_count": doc.page_count,
                        "candidate_pages": sorted(candidate_pages1),
                        "inspect_pages": [p["page"] for p in page_records],
                        "geometry_category": category,
                        "pages": page_records,
                    })
        except Exception as exc:
            record["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        rows.append(record)
        print(f"V17_3_ROLE_HEADER_GEOMETRY {idx}/17 aid={aid}", flush=True)

    report = {
        "gate": "S3G1J_V17_3_ROLE_HEADER_GEOMETRY_TRACE",
        "diagnostic_pass": not errors and len(rows) == 17,
        "sample_count": len(rows),
        "target_category": TARGET_CATEGORY,
        "geometry_category_counts": dict(category_counts),
        "rows": rows,
        "policy": {
            "diagnostic_only": True,
            "parser_policy_changed": False,
            "no_ocr": True,
            "same_table_role_header_evidence_only": True,
            "accounting_tolerance_changed": False,
            "stage4_alpha_locked": True,
        },
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "sample_count": len(rows),
        "geometry_category_counts": dict(category_counts),
        "errors": errors,
        "diagnostic_pass": report["diagnostic_pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["diagnostic_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
