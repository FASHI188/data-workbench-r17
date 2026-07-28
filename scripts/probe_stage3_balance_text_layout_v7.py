#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict

import fitz
import requests

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v2 as v2
from probe_stage3_financial_pdf_parser import ROOT, get_pdf, sha

SAMPLES = [
    ("000680_2015_Q1", "https://static.cninfo.com.cn/finalpage/2015-04-29/1200932369.PDF"),
    ("000416_2017_ANNUAL", "https://static.cninfo.com.cn/finalpage/2018-03-21/1204495399.PDF"),
    ("601988_2024_SEMI", "https://static.cninfo.com.cn/finalpage/2024-08-30/1221055667.PDF"),
    ("603093_2025_SEMI", "https://static.cninfo.com.cn/finalpage/2025-08-19/1224505712.PDF"),
    ("000750_2025_SEMI", "https://static.cninfo.com.cn/finalpage/2025-08-30/1224627276.PDF"),
]

KEYWORDS = (
    "资产负债表",
    "资产总计",
    "总资产",
    "负债合计",
    "归属于母公司所有者权益合计",
    "归属于母公司股东权益合计",
    "所有者权益合计",
    "股东权益合计",
    "负债和所有者权益总计",
    "负债和股东权益总计",
    "编制单位",
    "单位：",
    "单位:",
)


def _line_context(lines: list[str], idx: int, radius: int = 2) -> list[str]:
    lo = max(0, idx - radius)
    hi = min(len(lines), idx + radius + 1)
    return lines[lo:hi]


def _visual_rows(page: fitz.Page, tolerance: float = 2.5) -> list[dict]:
    words = page.get_text("words", sort=True) or []
    bands: list[dict] = []
    for w in words:
        x0, y0, x1, y1, text = float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])
        target = None
        for band in bands[-8:]:
            if abs(y0 - band["y_anchor"]) <= tolerance:
                target = band
                break
        if target is None:
            target = {"y_anchor": y0, "words": []}
            bands.append(target)
        target["words"].append((x0, y0, x1, y1, text))
        n = len(target["words"])
        target["y_anchor"] = ((target["y_anchor"] * (n - 1)) + y0) / n
    out = []
    for band in bands:
        ordered = sorted(band["words"], key=lambda z: (z[0], z[1]))
        text = " ".join(z[4] for z in ordered)
        compact = base.norm(text)
        if any(base.norm(k) in compact for k in KEYWORDS):
            out.append({
                "y": round(float(band["y_anchor"]), 2),
                "text": text,
                "words": [
                    {"x0": round(z[0], 2), "x1": round(z[2], 2), "text": z[4]}
                    for z in ordered
                ],
            })
    return out


def _page_probe(doc: fitz.Document, pno: int) -> dict | None:
    text = doc[pno].get_text("text") or ""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    compact = base.norm(text)
    keyword_hits = [k for k in KEYWORDS if base.norm(k) in compact]
    unit, mult = base.detect_unit(text)
    contexts = []
    seen = set()
    for i, line in enumerate(lines):
        nline = base.norm(line)
        if any(base.norm(k) in nline for k in KEYWORDS):
            key = tuple(_line_context(lines, i))
            if key not in seen:
                seen.add(key)
                contexts.append({"line_index": i, "context": list(key)})
    visual = _visual_rows(doc[pno])
    if not keyword_hits and not unit and not visual:
        return None
    return {
        "page": pno + 1,
        "keyword_hits": keyword_hits,
        "detected_unit": unit,
        "unit_multiplier": str(mult) if mult is not None else None,
        "line_contexts": contexts[:30],
        "visual_rows": visual[:30],
    }


def main() -> int:
    out = ROOT / "data/stage3_source_probe_v7"
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    results = []
    errors = []

    for name, url in SAMPLES:
        rec = {"name": name, "url": url}
        try:
            raw = get_pdf(session, url)
            doc = fitz.open(stream=raw, filetype="pdf")
            pages = []
            for pno in range(doc.page_count):
                probe = _page_probe(doc, pno)
                if probe is not None:
                    pages.append(probe)
            rec.update({
                "bytes": len(raw),
                "sha256": sha(raw),
                "page_count": doc.page_count,
                "v6_detected_starts": [
                    {"page": p + 1, "priority": pri}
                    for p, pri in v2._balance_sheet_start_pages(doc)
                ],
                "pages_with_balance_evidence": pages,
            })
            if not pages:
                errors.append(f"{name}: NO_TEXT_BALANCE_EVIDENCE")
        except Exception as exc:
            rec["error"] = repr(exc)
            errors.append(f"{name}: {exc!r}")
        results.append(rec)

    report = {
        "gate": "S3G1J_BALANCE_TEXT_LAYOUT_DIAGNOSTIC_V7",
        "pass": not errors,
        "sample_count": len(SAMPLES),
        "authority": "CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256",
        "purpose": "Expose PyMuPDF text-line and coordinate-row evidence for the five residual V6 failures before changing parser logic.",
        "results": results,
        "errors": errors,
    }
    path = out / "balance_text_layout_diagnostic_v7.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
