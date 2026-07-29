#!/usr/bin/env python3
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

import extract_stage3_financial_pdf_values_v9 as v14

METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V10_UNIQUE_USABLE_TIE"
_ORIGINAL_RESOLVE = v14.v9.base.resolve_candidates

REPORT_SIGNATURE_RE = re.compile(
    r"(?P<year>20\d{2})年(?P<kind>年度报告|半年度报告|第一季度报告|第三季度报告)"
)


def _report_signature(title: object) -> tuple[str, str] | None:
    text = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", str(title or "")))
    match = REPORT_SIGNATURE_RE.search(text)
    if not match:
        return None
    return match.group("year"), match.group("kind")


def _dec(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _same_value(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) / max(abs(a), abs(b), Decimal("1")) <= Decimal("0.000000001")


def _is_independently_usable(candidate: dict) -> bool:
    if candidate.get("error"):
        return False
    parsed = candidate.get("parsed") or {}
    if parsed.get("validation_errors"):
        return False
    if not parsed.get("balance_sheet_block"):
        return False
    if int(parsed.get("tier2_found") or 0) < 3:
        return False
    return True


def _is_narrow_balance_parser_failure(candidate: dict) -> bool:
    # This V15 exception is intentionally limited to the exact deterministic
    # failure observed in the frozen 41 true-tie diagnostic. Network/HTTP,
    # issuer mismatch, identity conflict and any future error class remain hard.
    if str(candidate.get("error") or "") != "NO_VALIDATED_BALANCE_SHEET_BLOCK":
        return False
    parsed = candidate.get("parsed") or {}
    if not parsed:
        return False
    if parsed.get("balance_sheet_block"):
        return False
    if int(parsed.get("tier2_found") or 0) >= 3:
        return False
    return True


def _overlapping_found_values_compatible(good: dict, bad: dict) -> tuple[bool, list[dict]]:
    good_obs = ((good.get("parsed") or {}).get("observations") or {})
    bad_obs = ((bad.get("parsed") or {}).get("observations") or {})
    conflicts: list[dict] = []
    for concept in sorted(set(good_obs) & set(bad_obs)):
        go = good_obs.get(concept) or {}
        bo = bad_obs.get(concept) or {}
        if go.get("status") != "FOUND" or bo.get("status") != "FOUND":
            continue
        gv = _dec(go.get("normalized_cny_value"))
        bv = _dec(bo.get("normalized_cny_value"))
        if gv is None or bv is None:
            continue
        if not _same_value(gv, bv):
            conflicts.append({"concept": concept, "good": str(gv), "bad": str(bv)})
    return not conflicts, conflicts


def _unique_usable_tie_candidate(parsed: list[dict]) -> tuple[dict | None, str | None]:
    if len(parsed) != 2:
        return None, "V15 requires exactly two tied candidates"

    usable = [candidate for candidate in parsed if _is_independently_usable(candidate)]
    if len(usable) != 1:
        return None, f"expected exactly one independently usable candidate, got {len(usable)}"

    good = usable[0]
    bad = parsed[0] if parsed[1] is good else parsed[1]
    if not _is_narrow_balance_parser_failure(bad):
        return None, "non-usable candidate is not the narrow balance-parser failure"

    good_sig = _report_signature(good.get("title"))
    bad_sig = _report_signature(bad.get("title"))
    if good_sig is None or bad_sig is None or good_sig != bad_sig:
        return None, f"report signatures differ good={good_sig} bad={bad_sig}"

    compatible, conflicts = _overlapping_found_values_compatible(good, bad)
    if not compatible:
        return None, f"overlapping extracted values conflict: {conflicts}"

    return good, None


def resolve_candidates(parsed: list[dict], canonical_id: str):
    chosen, resolution, err = _ORIGINAL_RESOLVE(parsed, canonical_id)
    if chosen is not None:
        return chosen, resolution, err

    # Never convert a real value conflict, issuer mismatch, source/network error,
    # or single-candidate parser failure into a pass.
    if resolution != "TIE_SOURCE_INCOMPLETE":
        return None, resolution, err

    candidate, gate_error = _unique_usable_tie_candidate(parsed)
    if candidate is None:
        return None, resolution, err or gate_error

    suffix = "CANONICAL" if str(candidate.get("id")) == str(canonical_id) else "NONCANONICAL"
    return candidate, f"TIE_UNIQUE_INDEPENDENTLY_USABLE_{suffix}", None


# Preserve V14.1 parser, PDF issuer gate and candidate provenance. Replace only
# the final tied-candidate resolver.
v14.v9.base.resolve_candidates = resolve_candidates
v14.v9.base.METHOD = METHOD


if __name__ == "__main__":
    raise SystemExit(v14.v9.base.main())
