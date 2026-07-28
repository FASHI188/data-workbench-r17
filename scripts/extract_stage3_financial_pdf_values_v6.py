#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
from pathlib import Path

import fitz

import extract_stage3_financial_pdf_values_v2  # noqa: F401
import extract_stage3_financial_pdf_values as base
from stage3_financial_pdf_parser_v5 import parse_pdf_bytes as v8_parse_pdf_bytes

ROOT = Path(__file__).resolve().parents[1]
METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V6_PDF_ISSUER_GATE"
CODE_LABEL_RE = re.compile(r"(?:证券代码|股票代码|公司代码)\s*[:：]?\s*([0-9]{6})")


def _load_known_a_share_codes() -> set[str]:
    path = ROOT / "data/security_lifecycle/security_intervals.csv"
    out: set[str] = set()
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            code = str(r.get("code") or "")
            if len(code) == 6 and code.isdigit():
                out.add(code)
    return out


KNOWN_A_SHARE_CODES = _load_known_a_share_codes()
EXPECTED_BY_CANONICAL_ID: dict[str, set[str]] = {}
_ORIGINAL_FILTER = base.filter_candidates_by_issuer
_ORIGINAL_RESOLVE = base.resolve_candidates


def declared_a_share_codes(raw: bytes, max_pages: int = 6) -> list[str]:
    """Read explicit stock/company/security codes from the filing itself.

    CNINFO metadata can associate a subsidiary filing with a parent's query/orgId.
    The original PDF is the final identity witness for numeric authority.  Only
    explicit labelled six-digit codes are considered; unlabelled numbers are
    ignored.  Codes outside the frozen main-A lifecycle are diagnostic only and
    do not trigger exclusion.
    """
    doc = fitz.open(stream=raw, filetype="pdf")
    hits: set[str] = set()
    for pno in range(min(doc.page_count, max_pages)):
        text = doc[pno].get_text("text") or ""
        compact = re.sub(r"[ \t\r\f\v]+", "", text)
        for m in CODE_LABEL_RE.finditer(compact):
            code = m.group(1)
            if code in KNOWN_A_SHARE_CODES:
                hits.add(code)
    return sorted(hits)


def parse_pdf_bytes(raw: bytes) -> dict:
    parsed = dict(v8_parse_pdf_bytes(raw))
    parsed["declared_a_share_codes"] = declared_a_share_codes(raw)
    return parsed


def filter_candidates_by_issuer(candidates: list[dict], source_code: str, canonical_id: str):
    allowed = set(base.RELATED_CODES.get(source_code, {source_code})) | {source_code}
    EXPECTED_BY_CANONICAL_ID[str(canonical_id)] = allowed
    return _ORIGINAL_FILTER(candidates, source_code, canonical_id)


def resolve_candidates(parsed: list[dict], canonical_id: str):
    allowed = EXPECTED_BY_CANONICAL_ID.get(str(canonical_id), set())
    eligible: list[dict] = []
    pdf_excluded = 0

    for candidate in parsed:
        codes = set((candidate.get("parsed") or {}).get("declared_a_share_codes") or [])
        # No explicit A-share code: preserve legacy fail-closed path; title,
        # structural and value gates still decide the candidate.
        if not codes:
            eligible.append(candidate)
            continue
        if codes & allowed:
            eligible.append(candidate)
            continue

        reason = f"PDF_DECLARES_OTHER_A_SHARE_ISSUER:{sorted(codes)} EXPECTED:{sorted(allowed)}"
        if str(candidate.get("id")) == str(canonical_id):
            candidate["error"] = reason
            return None, "CANONICAL_PDF_ISSUER_MISMATCH", reason

        candidate["excluded_reason"] = reason
        pdf_excluded += 1

    chosen, resolution, err = _ORIGINAL_RESOLVE(eligible, canonical_id)
    if pdf_excluded:
        resolution += "_AFTER_PDF_ISSUER_GATE"
    return chosen, resolution, err


base.parse_pdf_bytes = parse_pdf_bytes
base.filter_candidates_by_issuer = filter_candidates_by_issuer
base.resolve_candidates = resolve_candidates
base.METHOD = METHOD


if __name__ == "__main__":
    raise SystemExit(base.main())
