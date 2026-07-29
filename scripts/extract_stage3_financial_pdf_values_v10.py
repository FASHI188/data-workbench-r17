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


def _half_display_step_cny(observation: dict) -> Decimal | None:
    """Infer half one displayed monetary unit from raw precision + unit scale.

    Example: 663800.32 万元 is displayed to 0.01 万元, so its ordinary
    rounding interval is +/- 50 yuan. This is not a percentage tolerance and
    cannot justify material differences between two filings.
    """
    raw = str(observation.get("raw_value") or "").strip().replace(",", "")
    if not raw:
        return None
    if raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1]
    raw = raw.lstrip("+-")
    if not re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return None
    decimals = len(raw.partition(".")[2]) if "." in raw else 0
    multiplier = _dec(observation.get("unit_multiplier"))
    if multiplier is None or multiplier <= 0:
        return None
    display_step = multiplier * (Decimal("10") ** Decimal(-decimals))
    return display_step / Decimal("2")


def _observations_compatible(a_obs: dict, b_obs: dict) -> tuple[bool, dict]:
    a = _dec(a_obs.get("normalized_cny_value"))
    b = _dec(b_obs.get("normalized_cny_value"))
    if a is None or b is None:
        return True, {"mode": "NON_NUMERIC_SKIP"}
    diff = abs(a - b)
    rel = diff / max(abs(a), abs(b), Decimal("1"))
    if rel <= Decimal("0.000000001"):
        return True, {"mode": "EXACT_RELATIVE", "relative_difference": str(rel)}

    a_half = _half_display_step_cny(a_obs)
    b_half = _half_display_step_cny(b_obs)
    available = [x for x in (a_half, b_half) if x is not None]
    if available:
        allowed = max(available)
        if diff <= allowed:
            return True, {
                "mode": "DECLARED_UNIT_DISPLAY_ROUNDING",
                "absolute_difference_cny": str(diff),
                "allowed_half_display_step_cny": str(allowed),
                "relative_difference": str(rel),
            }
    return False, {
        "mode": "MATERIAL_CONFLICT",
        "absolute_difference_cny": str(diff),
        "allowed_half_display_step_cny": str(max(available)) if available else None,
        "relative_difference": str(rel),
    }


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
        compatible, evidence = _observations_compatible(go, bo)
        if not compatible:
            conflicts.append({
                "concept": concept,
                "good": str(go.get("normalized_cny_value")),
                "bad": str(bo.get("normalized_cny_value")),
                "good_raw": go.get("raw_value"),
                "bad_raw": bo.get("raw_value"),
                "good_unit": go.get("unit"),
                "bad_unit": bo.get("unit"),
                "good_unit_multiplier": go.get("unit_multiplier"),
                "bad_unit_multiplier": bo.get("unit_multiplier"),
                **evidence,
            })
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
        # Preserve the original failure while exposing which V15 safety gate
        # refused the exception. This changes diagnostics only, not authority.
        detail = str(err or resolution)
        if gate_error:
            detail += f" | V15_GATE: {gate_error}"
        return None, resolution, detail

    suffix = "CANONICAL" if str(candidate.get("id")) == str(canonical_id) else "NONCANONICAL"
    return candidate, f"TIE_UNIQUE_INDEPENDENTLY_USABLE_{suffix}", None


# Preserve V14.1 parser, PDF issuer gate and candidate provenance. Replace only
# the final tied-candidate resolver.
v14.v9.base.resolve_candidates = resolve_candidates
v14.v9.base.METHOD = METHOD


if __name__ == "__main__":
    raise SystemExit(v14.v9.base.main())
