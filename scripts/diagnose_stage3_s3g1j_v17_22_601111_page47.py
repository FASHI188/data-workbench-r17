#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import fitz
import requests

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v17_21 as v21
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard
from stage3_financial_pdf_parser_v13 import parse_pdf_bytes

TARGET_ID = "1217717273"
TARGET_CODE = "601111"
TARGET_DATE = "2023-06-30"
TARGET_SHARD = 0
SOURCE_SHA = "79a62493099579ec902383ab3734e1e9289b014c2bfb89d9d15faf85d212c047"
PAGES_1B = tuple(range(44, 51))
EQUITY_HINTS = (
    "权益", "股东", "所有者", "少数股东", "非控制性权益",
    "负债合计", "资产总计", "合计", "总计", "续",
)


def _read_versions(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _download(url: str) -> bytes:
    session = requests.Session()
    last: Exception | None = None
    for attempt in range(6):
        try:
            response = session.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 S3G1J-V17.22-601111-native-structure",
                    "Referer": "https://www.cninfo.com.cn/",
                },
                timeout=120,
            )
            response.raise_for_status()
            raw = response.content
            if not raw.startswith(b"%PDF"):
                raise ValueError(f"not PDF bytes={len(raw)} content_type={response.headers.get('Content-Type')}")
            return raw
        except Exception as exc:
            last = exc
            if attempt < 5:
                time.sleep(min(2 ** attempt, 12))
    raise RuntimeError(repr(last))


def _safe_rects(page: fitz.Page, xref: int) -> list[list[float]]:
    try:
        return [[float(v) for v in rect] for rect in page.get_image_rects(xref)]
    except Exception:
        return []


def _page_structure(page: fitz.Page, page_1b: int) -> dict:
    text = page.get_text("text") or ""
    words = page.get_text("words") or []
    blocks = page.get_text("blocks") or []
    text_dict = page.get_text("dict") or {}
    rows = sorted(v14._rows_from_words(page), key=lambda row: float(row["y"]))

    relevant_rows: list[dict] = []
    numeric_only_rows: list[dict] = []
    for row in rows:
        row_text = str(row.get("text") or "")
        normalized = v14._norm(row_text)
        if any(v14._norm(hint) in normalized for hint in EQUITY_HINTS):
            relevant_rows.append({
                "text": row_text[:1000],
                "y": str(row.get("y")),
                "word_count": len(row.get("words") or []),
            })
        try:
            if v21.v17.v1715._strict_numeric_only_row(row):
                numeric_only_rows.append({
                    "text": row_text[:1000],
                    "y": str(row.get("y")),
                    "word_count": len(row.get("words") or []),
                })
        except Exception:
            pass

    image_blocks: list[dict] = []
    for block in text_dict.get("blocks") or []:
        if int(block.get("type", 0) or 0) != 1:
            continue
        image_blocks.append({
            key: block.get(key)
            for key in ("bbox", "width", "height", "ext", "colorspace", "xres", "yres", "bpc", "size")
            if key in block
        })

    embedded_images: list[dict] = []
    for image in page.get_images(full=True) or []:
        xref = int(image[0])
        embedded_images.append({
            "xref": xref,
            "smask": int(image[1]),
            "width": int(image[2]),
            "height": int(image[3]),
            "bpc": int(image[4]),
            "colorspace": str(image[5]),
            "name": str(image[7]) if len(image) > 7 else "",
            "rects": _safe_rects(page, xref),
        })

    try:
        drawings_count = len(page.get_drawings())
    except Exception:
        drawings_count = -1
    try:
        bboxlog_counts = dict(Counter(str(item[0]) for item in page.get_bboxlog()))
    except Exception:
        bboxlog_counts = {}

    graphics_count = sum(
        count for kind, count in bboxlog_counts.items()
        if kind not in {"fill-text", "stroke-text", "ignore-text"}
    )
    return {
        "page": page_1b,
        "text_chars": len(text.strip()),
        "text_lines": len([line for line in text.splitlines() if line.strip()]),
        "word_count": len(words),
        "block_count": len(blocks),
        "row_count": len(rows),
        "embedded_image_count": len(embedded_images),
        "embedded_images": embedded_images,
        "image_block_count": len(image_blocks),
        "image_blocks": image_blocks,
        "drawings_count": drawings_count,
        "bboxlog_counts": bboxlog_counts,
        "nontext_bboxlog_count": graphics_count,
        "relevant_rows": relevant_rows,
        "numeric_only_rows": numeric_only_rows[:50],
        "low_native_text": len(text.strip()) < 80,
        "has_nontext_graphics": bool(embedded_images or image_blocks or drawings_count > 0 or graphics_count > 0),
    }


def _serialize_candidates(candidates: dict[str, list[dict]]) -> dict:
    out: dict[str, list[dict]] = {}
    for concept in v21.CONCEPTS:
        out[concept] = [v21._serialize(item) for item in candidates.get(concept, [])]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", required=True)
    parser.add_argument("--v17-11-acceptance", required=True)
    parser.add_argument("--v17-21-shard0", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    accepted = json.loads(Path(args.v17_11_acceptance).read_text(encoding="utf-8"))
    source_rows = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if not accepted.get("pass") or len(source_rows) != 82 or TARGET_ID not in source_rows:
        raise ValueError("accepted V17.11 exact-82 source state mismatch")
    if source_rows[TARGET_ID]["sha256"] != SOURCE_SHA:
        raise ValueError("accepted target source SHA mismatch")

    promoted = json.loads(Path(args.v17_21_shard0).read_text(encoding="utf-8"))
    if not promoted.get("pass") or int(promoted.get("shard", -1)) != TARGET_SHARD:
        raise ValueError("V17.21 shard0 production evidence mismatch")
    promoted_rows = {
        str(row["announcement_id"]): row for row in promoted.get("results") or []
    }
    promoted_target = promoted_rows.get(TARGET_ID)
    if promoted_target is None:
        raise ValueError("target absent from V17.21 production shard0 evidence")
    if promoted_target.get("production_balance_sheet_recovered"):
        raise ValueError("target unexpectedly recovered before diagnostic")
    if not promoted_target.get("validation_errors"):
        raise ValueError("target no longer fails closed")
    if promoted_target.get("source_sha256") != SOURCE_SHA:
        raise ValueError("V17.21 target source SHA mismatch")

    versions = [
        row for row in _read_versions(Path(args.versions))
        if row["canonical_announcement_id"] == TARGET_ID
    ]
    if len(versions) != 1:
        raise ValueError(f"expected one frozen target row, got {len(versions)}")
    row = versions[0]
    if row["source_code"] != TARGET_CODE or row["economic_date"] != TARGET_DATE:
        raise ValueError("target frozen identity changed")

    raw = _download(row["canonical_source_url"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE_SHA:
        raise ValueError(f"downloaded source SHA mismatch: {digest}")

    with fitz.open(stream=raw, filetype="pdf") as doc:
        with _mupdf_diagnostic_guard():
            parsed = parse_pdf_bytes(raw, TARGET_DATE)
            production_diagnostic = v21.diagnose_spatial_balance_sheet_v17_21(doc, TARGET_DATE)
            existing, base_funnel = v21.v17.v166._collect_candidates_v16_6(doc, TARGET_DATE)
            bridge, bridge_funnel = v21.v17.v1715._collect_adjacent_bridge_candidates(doc, TARGET_DATE)
            strict_equity, strict_funnel = v21.v17._collect_strict_same_row_equity_candidates(doc, TARGET_DATE)
            reverse_assets, reverse_funnel = v21._collect_reverse_asset_total_candidates(doc, TARGET_DATE)
            merged: dict[str, list[dict]] = defaultdict(list)
            for concept in v21.CONCEPTS:
                merged[concept].extend(existing.get(concept, []))
                merged[concept].extend(bridge.get(concept, []))
            merged["TOTAL_EQUITY"].extend(strict_equity)
            merged["TOTAL_ASSETS"].extend(reverse_assets)
            candidates = v21.v17.v1715._dedupe_candidates(merged)
            events = v21.v17.blocks.formal_statement_events(doc)
            candidate_pages = v14._candidate_pages(doc)
            page_structures = [
                _page_structure(doc[page_1b - 1], page_1b)
                for page_1b in PAGES_1B
                if 1 <= page_1b <= doc.page_count
            ]
            page_count = doc.page_count

    validation_errors = list(parsed.get("validation_errors") or [])
    if parsed.get("balance_sheet_block") is not None or not validation_errors:
        raise ValueError("current V17.21 production parser no longer fails closed")
    if production_diagnostic.get("recovered"):
        raise ValueError("current V17.21 spatial diagnostic unexpectedly recovered target")

    page_map = {int(item["page"]): item for item in page_structures}
    page47 = page_map.get(47)
    if page47 is None:
        raise ValueError("page 47 absent from official PDF")
    native_equity_rows = [
        item for item in page47["relevant_rows"]
        if any(token in v14._norm(item["text"]) for token in (
            v14._norm("权益"), v14._norm("股东"), v14._norm("所有者")
        ))
    ]
    likely_image_only = bool(page47["low_native_text"] and page47["has_nontext_graphics"])
    if native_equity_rows:
        conclusion = "NATIVE_TEXT_EQUITY_ROW_PRESENT_NEEDS_GEOMETRY_REVIEW"
    elif likely_image_only:
        conclusion = "LIKELY_IMAGE_OR_VECTOR_ONLY_BALANCE_SHEET_CONTINUATION_NO_NATIVE_EQUITY_TEXT"
    else:
        conclusion = "NO_DIRECT_NATIVE_EQUITY_ROW_FOUND_ON_PAGE_47"

    report = {
        "gate": "S3G1J_V17_22_601111_PAGE47_NATIVE_STRUCTURE_DIAGNOSTIC",
        "pass": True,
        "diagnostic_only": True,
        "no_parser_change": True,
        "no_ocr": True,
        "no_accounting_inference": True,
        "announcement_id": TARGET_ID,
        "source_code": TARGET_CODE,
        "economic_date": TARGET_DATE,
        "canonical_title": row["canonical_title"],
        "canonical_source_url": row["canonical_source_url"],
        "source_sha256": digest,
        "source_bytes": len(raw),
        "page_count": page_count,
        "production_validation_errors": validation_errors,
        "production_balance_sheet_block": parsed.get("balance_sheet_block"),
        "production_candidate_counts": production_diagnostic.get("candidate_counts"),
        "production_diagnostic": production_diagnostic,
        "candidate_pages": candidate_pages,
        "formal_statement_events": [
            event for event in events
            if 40 <= int(event.get("page", 0) or 0) <= 56
        ],
        "candidate_funnels": {
            "base": base_funnel,
            "adjacent_bridge": bridge_funnel,
            "strict_equity": strict_funnel,
            "reverse_asset": reverse_funnel,
        },
        "candidates": _serialize_candidates(candidates),
        "pages_44_to_50": page_structures,
        "page47_native_equity_rows": native_equity_rows,
        "page47_likely_image_or_vector_only": likely_image_only,
        "diagnostic_conclusion": conclusion,
        "equity_movement_table_not_promoted_to_balance_sheet_authority": True,
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "global_row_tolerance_changed": False,
        "source_policy_changed": False,
        "e_equals_a_minus_l_inference": False,
        "stage4_alpha_locked": True,
        "errors": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "announcement_id": TARGET_ID,
        "candidate_counts": report["production_candidate_counts"],
        "page47_text_chars": page47["text_chars"],
        "page47_images": page47["embedded_image_count"],
        "page47_image_blocks": page47["image_block_count"],
        "page47_drawings": page47["drawings_count"],
        "page47_native_equity_rows": len(native_equity_rows),
        "conclusion": conclusion,
        "pass": True,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
