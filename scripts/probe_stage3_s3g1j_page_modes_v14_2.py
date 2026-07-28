#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import fitz
import requests

import probe_stage3_s3g1j_coordinate_rows_v14 as v14

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/stage3_source_probe_v14/s3g1j_page_modes_v14_2.json"

# Raw V14 coordinate diagnostic non-recoveries only.  The eight raw identity
# candidates are handled by V14.1 role/period gating instead of this probe.
RAW_NONRECOVERED_IDS = {
    "1201726564",  # 603599 2015Q3 - no text trigger
    "1201734718",  # 000686 2015Q3
    "1202600091",  # 600982 2016H1 - no text trigger
    "1202637566",  # 600679 2016H1 - missing equity
    "1202805050",  # 600650 2016Q3
    "1212651259",  # 600808 2021 annual
    "1214924252",  # 601963 2022Q3
    "1219442543",  # 601688 2023 annual
    "1221090309",  # 601390 2024H1
    "1223364547",  # 601668 2025Q1
    "1223385260",  # 603180 2025Q1
    "1225037867",  # 601319 2025 annual
}

ROW_TERMS = (
    "资产总计", "资产合计", "总资产", "负债合计", "总负债",
    "所有者权益", "股东权益", "权益合计", "权益总计",
    "负债和所有者权益", "负债及所有者权益", "负债和股东权益", "负债及股东权益",
    "total assets", "total liabilities", "total equity",
)
TITLE_TERMS = (
    "资产负债表", "财务状况表", "balance sheet", "statement of financial position",
)
UNIT_TERMS = ("单位", "人民币", "rmb", "cny", "yuan")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _download(session: requests.Session, sample: dict) -> bytes:
    response = session.get(
        sample["url"],
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V14.2-page-mode-diagnostic",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=90,
    )
    response.raise_for_status()
    raw = response.content
    actual = hashlib.sha256(raw).hexdigest()
    if actual != sample["sha256"]:
        raise AssertionError(
            f"SHA mismatch {sample['announcement_id']} expected={sample['sha256']} actual={actual}"
        )
    return raw


def _image_coverage(page: fitz.Page) -> tuple[int, float]:
    rect = page.rect
    page_area = max(float(rect.width * rect.height), 1.0)
    total = 0.0
    count = 0
    seen = set()
    for img in page.get_images(full=True) or []:
        xref = int(img[0])
        if xref in seen:
            continue
        seen.add(xref)
        try:
            rects = page.get_image_rects(xref) or []
        except Exception:
            rects = []
        for r in rects:
            count += 1
            total += max(0.0, float(r.width * r.height))
    return count, min(total / page_area, 1.0)


def _keyword_rows(page: fitz.Page) -> list[str]:
    rows = v14._rows_from_words(page)
    hits = []
    for row in rows:
        n = _norm(row["text"])
        if any(_norm(term) in n for term in ROW_TERMS):
            hits.append(row["text"][:900])
    return hits[:80]


def _page_summary(page: fitz.Page, pno: int) -> dict:
    text = page.get_text("text") or ""
    n = _norm(text)
    image_count, image_coverage = _image_coverage(page)
    word_count = len(page.get_text("words") or [])
    drawing_count = len(page.get_drawings() or [])
    title_hits = [term for term in TITLE_TERMS if _norm(term) in n]
    unit_hits = [term for term in UNIT_TERMS if _norm(term) in n]
    rows = _keyword_rows(page)
    return {
        "page": pno + 1,
        "text_chars": len(text.strip()),
        "word_count": word_count,
        "image_count": image_count,
        "image_coverage": image_coverage,
        "drawing_count": drawing_count,
        "title_hits": title_hits,
        "unit_hits": unit_hits,
        "keyword_rows": rows,
    }


def _classify(pages: list[dict]) -> tuple[str, dict]:
    low_text_image_pages = [
        p for p in pages if p["text_chars"] < 120 and p["image_coverage"] >= 0.55
    ]
    explicit_statement_pages = [p for p in pages if p["title_hits"]]
    keyword_pages = [p for p in pages if p["keyword_rows"]]
    vector_heavy_pages = [
        p for p in pages if p["drawing_count"] >= 20 and p["word_count"] >= 20
    ]

    details = {
        "low_text_image_pages": [p["page"] for p in low_text_image_pages],
        "explicit_statement_pages": [p["page"] for p in explicit_statement_pages],
        "keyword_pages": [p["page"] for p in keyword_pages],
        "vector_heavy_pages": [p["page"] for p in vector_heavy_pages],
    }
    if low_text_image_pages and not keyword_pages:
        return "SCAN_OR_IMAGE_TABLE_OCR_CANDIDATE", details
    if keyword_pages and explicit_statement_pages:
        return "NATIVE_TEXT_STATEMENT_ALIAS_OR_ROW_ASSEMBLY", details
    if keyword_pages:
        return "NATIVE_TEXT_STRUCTURAL_DISCOVERY", details
    if vector_heavy_pages:
        return "VECTOR_TABLE_WITHOUT_CURRENT_KEYWORD_ROWS", details
    return "NO_STRONG_PAGE_MODE_SIGNAL", details


def main() -> int:
    spec = json.loads(v14.SAMPLE_PATH.read_text(encoding="utf-8"))
    samples_by_id = {str(x["announcement_id"]): x for x in (spec.get("samples") or [])}
    missing = sorted(RAW_NONRECOVERED_IDS - set(samples_by_id))
    if missing:
        raise ValueError(f"missing frozen samples: {missing}")

    session = requests.Session()
    rows = []
    errors = []
    counts = Counter()

    for aid in sorted(RAW_NONRECOVERED_IDS):
        sample = samples_by_id[aid]
        row = {
            k: sample[k]
            for k in ("shard", "source_code", "report_family", "economic_date", "announcement_id", "url", "sha256", "era")
        }
        try:
            raw = _download(session, sample)
            doc = fitz.open(stream=raw, filetype="pdf")
            summaries = [_page_summary(doc[pno], pno) for pno in range(doc.page_count)]
            mode, details = _classify(summaries)
            counts[mode] += 1

            # Retain only evidence-bearing pages in the artifact; aggregate
            # counts remain document-wide.
            interesting = [
                p for p in summaries
                if p["title_hits"] or p["keyword_rows"] or p["image_coverage"] >= 0.55 or p["drawing_count"] >= 20
            ]
            row.update(
                {
                    "page_count": doc.page_count,
                    "mode": mode,
                    "mode_details": details,
                    "interesting_pages": interesting[:120],
                    "document_stats": {
                        "pages_with_text": sum(p["text_chars"] >= 120 for p in summaries),
                        "pages_with_keyword_rows": sum(bool(p["keyword_rows"]) for p in summaries),
                        "pages_with_statement_title": sum(bool(p["title_hits"]) for p in summaries),
                        "pages_image_coverage_ge_55pct": sum(p["image_coverage"] >= 0.55 for p in summaries),
                        "pages_vector_heavy": sum(p["drawing_count"] >= 20 for p in summaries),
                    },
                }
            )
        except Exception as exc:
            counts["DIAGNOSTIC_ERROR"] += 1
            row.update({"mode": "DIAGNOSTIC_ERROR", "diagnostic_error": f"{type(exc).__name__}: {exc}"})
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        rows.append(row)

    report = {
        "gate": "S3G1J_V14_2_PAGE_MODE_AND_MISSING_ROW_DIAGNOSTIC",
        "diagnostic_pass": not errors,
        "sample_count": len(rows),
        "mode_counts": dict(sorted(counts.items())),
        "policy": {
            "exact_raw_v14_nonrecoveries": True,
            "original_pdf_sha_required": True,
            "no_ocr_executed": True,
            "ocr_is_only_classification_candidate": True,
            "native_words_and_vector_drawings_inspected": True,
            "diagnostic_only": True,
        },
        "rows": rows,
        "errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
