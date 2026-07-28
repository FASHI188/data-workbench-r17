#!/usr/bin/env python3
from __future__ import annotations

import json
from decimal import Decimal

import fitz
import requests

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v2 as v2
from probe_stage3_financial_pdf_parser import ROOT, get_pdf, sha
from stage3_financial_pdf_parser_v3 import parse_pdf_bytes

SAMPLES = [
    ("000017_2014_ANNUAL", "https://static.cninfo.com.cn/finalpage/2015-04-03/1200784431.PDF"),
    ("000911_2014_ANNUAL", "https://static.cninfo.com.cn/finalpage/2015-04-24/1200895880.PDF"),
    ("000680_2015_Q1", "https://static.cninfo.com.cn/finalpage/2015-04-29/1200932369.PDF"),
    ("002662_2017_Q3", "https://static.cninfo.com.cn/finalpage/2017-10-24/1204061131.PDF"),
    ("603421_2017_Q1", "https://static.cninfo.com.cn/finalpage/2017-04-24/1203361946.PDF"),
    ("000416_2017_ANNUAL", "https://static.cninfo.com.cn/finalpage/2018-03-21/1204495399.PDF"),
    ("600011_2022_Q3", "https://static.cninfo.com.cn/finalpage/2022-10-26/1214904541.PDF"),
    ("601988_2024_SEMI", "https://static.cninfo.com.cn/finalpage/2024-08-30/1221055667.PDF"),
    ("603093_2025_SEMI", "https://static.cninfo.com.cn/finalpage/2025-08-19/1224505712.PDF"),
    ("000750_2025_SEMI", "https://static.cninfo.com.cn/finalpage/2025-08-30/1224627276.PDF"),
]


def _d(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _candidate_snapshot(doc: fitz.Document, start: int, priority: int) -> dict:
    pages = list(range(start, min(doc.page_count, start + 5)))
    unit = v2._block_unit(doc, start, pages)
    rec: dict = {
        "start_page": start + 1,
        "priority": priority,
        "pages": [x + 1 for x in pages],
        "unit": unit[0] if unit else None,
        "metrics": {},
    }
    if unit is None:
        rec["candidate_error"] = "NO_BLOCK_UNIT"
        return rec
    block = {}
    for concept in v2.BALANCE_CONCEPTS:
        aliases = base.TIER1_ALIASES.get(concept) or base.TIER2_ALIASES.get(concept) or []
        obs = v2._find_metric_in_block(doc, pages, aliases, concept, unit)
        block[concept] = obs
        rec["metrics"][concept] = {
            "status": obs.status,
            "raw_value": obs.raw_value,
            "normalized_cny_value": obs.normalized_cny_value,
            "page": obs.page,
            "matched_alias": obs.matched_alias,
            "scope": obs.extraction_scope,
        }
    a = _d(block["TOTAL_ASSETS"].normalized_cny_value)
    l = _d(block["TOTAL_LIABILITIES"].normalized_cny_value)
    e = _d(block["TOTAL_EQUITY"].normalized_cny_value)
    if a is None or l is None or e is None:
        rec["identity_relative_error"] = None
        rec["candidate_error"] = "MISSING_A_L_E"
    else:
        rel = abs(a - (l + e)) / max(abs(a), abs(l + e), Decimal("1"))
        rec["identity_relative_error"] = str(rel)
        rec["candidate_error"] = None if rel <= Decimal("0.005") else "BALANCE_SHEET_IDENTITY_MISMATCH"
    return rec


def main() -> int:
    out = ROOT / "data/stage3_source_probe_v5"
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    results = []
    errors: list[str] = []

    for name, url in SAMPLES:
        rec = {"name": name, "url": url}
        try:
            raw = get_pdf(session, url)
            parsed = parse_pdf_bytes(raw)
            doc = fitz.open(stream=raw, filetype="pdf")
            starts = v2._balance_sheet_start_pages(doc)
            rec.update({
                "bytes": len(raw),
                "sha256": sha(raw),
                "page_count": doc.page_count,
                "detected_start_pages": [
                    {"page": p + 1, "priority": pri} for p, pri in starts
                ],
                "candidate_blocks": [_candidate_snapshot(doc, p, pri) for p, pri in starts],
                "selected_balance_sheet_block": parsed.get("balance_sheet_block"),
                "validation_errors": parsed.get("validation_errors") or [],
            })
            if not parsed.get("balance_sheet_block"):
                errors.append(f"{name}: NO_VALIDATED_BALANCE_SHEET_BLOCK")
            if parsed.get("validation_errors"):
                errors.extend(f"{name}: {x}" for x in parsed["validation_errors"])
        except Exception as exc:
            rec["error"] = repr(exc)
            errors.append(f"{name}: {exc!r}")
        results.append(rec)

    report = {
        "gate": "S3G1J_BALANCE_BLOCK_DIAGNOSTICS_V5",
        "pass": not errors,
        "sample_count": len(SAMPLES),
        "authority": "CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256",
        "identity_tolerance": "0.005 relative error",
        "policy": "Diagnostic candidates preserve exact block starts, units, metric pages and A=L+E residuals; no fallback observation can qualify as Stage3 truth.",
        "results": results,
        "errors": errors,
    }
    (out / "balance_block_diagnostics_v5.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
