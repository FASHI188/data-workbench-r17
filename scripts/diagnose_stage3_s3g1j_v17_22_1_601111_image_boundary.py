#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import stage3_financial_coordinate_fallback_v14 as v14


def _terminal_equity_rows(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        text = str(row.get("text") or "")
        normalized = v14._norm(text)
        has_equity = any(v14._norm(token) in normalized for token in ("权益", "股东", "所有者"))
        has_total = any(v14._norm(token) in normalized for token in ("合计", "总计"))
        header_only = v14._norm("负债及股东权益") in normalized and not has_total
        if has_equity and has_total and not header_only:
            out.append(row)
    return out


def _single_page_image(page: dict) -> dict:
    images = page.get("embedded_images") or []
    blocks = page.get("image_blocks") or []
    if len(images) != 1 or len(blocks) != 1:
        return {"pass": False, "reason": "not exactly one embedded image and one image block"}
    image = images[0]
    block = blocks[0]
    rects = image.get("rects") or []
    bbox = block.get("bbox") or []
    if len(rects) != 1 or len(rects[0]) != 4 or len(bbox) != 4:
        return {"pass": False, "reason": "missing unique image rectangle"}
    rect = [float(v) for v in rects[0]]
    bb = [float(v) for v in bbox]
    same_bbox = all(abs(a - b) <= 1.0 for a, b in zip(rect, bb))
    starts_at_origin = abs(rect[0]) <= 1.0 and abs(rect[1]) <= 1.0
    return {
        "pass": bool(same_bbox and starts_at_origin),
        "xref": image.get("xref"),
        "pixel_width": image.get("width"),
        "pixel_height": image.get("height"),
        "format": block.get("ext"),
        "rect": rect,
        "block_bbox": bb,
        "starts_at_origin": starts_at_origin,
        "image_rect_matches_block": same_bbox,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", required=True)
    parser.add_argument("--v17-11-acceptance", required=True)
    parser.add_argument("--v17-21-shard0", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        raw_out = Path(tmp) / "raw_v17_22.json"
        subprocess.run(
            [
                sys.executable,
                "scripts/diagnose_stage3_s3g1j_v17_22_601111_page47.py",
                "--versions", args.versions,
                "--v17-11-acceptance", args.v17_11_acceptance,
                "--v17-21-shard0", args.v17_21_shard0,
                "--out", str(raw_out),
            ],
            check=True,
        )
        raw = json.loads(raw_out.read_text(encoding="utf-8"))

    if not raw.get("pass") or raw.get("announcement_id") != "1217717273":
        raise ValueError("base V17.22 diagnostic did not pass")
    pages = {int(row["page"]): row for row in raw.get("pages_44_to_50") or []}
    page47 = pages.get(47)
    page48 = pages.get(48)
    if page47 is None or page48 is None:
        raise ValueError("pages 47/48 missing from source diagnostic")

    terminal_rows = _terminal_equity_rows(page47.get("relevant_rows") or [])
    page48_image = _single_page_image(page48)
    image_only = bool(
        int(page48.get("text_chars", -1)) == 0
        and int(page48.get("word_count", -1)) == 0
        and int(page48.get("row_count", -1)) == 0
        and page48_image.get("pass") is True
    )
    if terminal_rows:
        conclusion = "NATIVE_TERMINAL_EQUITY_ROW_PRESENT_ON_PAGE47_NEEDS_GEOMETRY_REVIEW"
        authority = "FURTHER_NATIVE_TEXT_DIAGNOSTIC_ALLOWED"
    elif image_only:
        conclusion = "GROUP_EQUITY_CONTINUATION_IS_FULL_PAGE_IMAGE_WITHOUT_NATIVE_TEXT"
        authority = "REMAIN_FAIL_CLOSED_UNDER_NO_OCR_POLICY"
    else:
        conclusion = "NO_NATIVE_TERMINAL_EQUITY_ROW_AND_NO_PROVEN_FULL_PAGE_IMAGE"
        authority = "EVIDENCE_INSUFFICIENT_REMAIN_FAIL_CLOSED"

    report = {
        "gate": "S3G1J_V17_22_1_601111_IMAGE_BOUNDARY_DIAGNOSTIC",
        "pass": True,
        "diagnostic_only": True,
        "corrects_prior_header_classification": True,
        "prior_false_positive_row": "负债及股东权益 附注五 6 月 30 日 12 月 31 日",
        "prior_false_positive_reason": "statement header contains equity wording but is not a terminal equity total row",
        "no_parser_change": True,
        "no_ocr": True,
        "no_accounting_inference": True,
        "announcement_id": raw["announcement_id"],
        "source_code": raw["source_code"],
        "economic_date": raw["economic_date"],
        "canonical_title": raw["canonical_title"],
        "canonical_source_url": raw["canonical_source_url"],
        "source_sha256": raw["source_sha256"],
        "production_validation_errors": raw["production_validation_errors"],
        "production_candidate_counts": raw["production_candidate_counts"],
        "page46_asset_total_candidates": raw["candidates"].get("TOTAL_ASSETS"),
        "page47_liability_total_candidates": raw["candidates"].get("TOTAL_LIABILITIES"),
        "page47_terminal_equity_rows": terminal_rows,
        "page47_native_text_chars": page47["text_chars"],
        "page47_native_word_count": page47["word_count"],
        "page48_native_text_chars": page48["text_chars"],
        "page48_native_word_count": page48["word_count"],
        "page48_native_row_count": page48["row_count"],
        "page48_full_page_image": page48_image,
        "page48_image_only": image_only,
        "diagnostic_conclusion": conclusion,
        "production_authority_conclusion": authority,
        "equity_movement_table_not_promoted_to_balance_sheet_authority": True,
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "global_row_tolerance_changed": False,
        "source_policy_changed": False,
        "e_equals_a_minus_l_inference": False,
        "stage4_alpha_locked": True,
        "errors": [],
        "source_diagnostic": raw,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "announcement_id": report["announcement_id"],
        "page47_terminal_equity_rows": len(terminal_rows),
        "page48_image_only": image_only,
        "page48_image": page48_image,
        "conclusion": conclusion,
        "authority": authority,
        "pass": True,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
