#!/usr/bin/env python3
from __future__ import annotations

import extract_stage3_financial_pdf_values as base

ORIGINAL_RESOLVE = base.resolve_candidates


def _older_id(candidate_id: str, canonical_id: str) -> bool:
    try:
        return int(candidate_id) < int(canonical_id)
    except Exception:
        return False


def _permanent_missing_source(error: object) -> bool:
    s = str(error or "")
    return "404 Client Error" in s or "410 Client Error" in s


def resolve_candidates(parsed: list[dict], canonical_id: str):
    errors = [x for x in parsed if x.get("error")]
    if not errors:
        return ORIGINAL_RESOLVE(parsed, canonical_id)

    canonical = next(
        (x for x in parsed if str(x.get("id")) == str(canonical_id) and not x.get("error")),
        None,
    )
    if canonical is None or not canonical.get("parsed"):
        return None, "TIE_SOURCE_INCOMPLETE", "canonical PDF is not independently usable"

    canonical_title = base._norm_title(str(canonical.get("title") or ""))
    # This exception is deliberately narrow: an old same-title candidate must be
    # permanently absent from the official static source, be noncanonical and have
    # an older announcement id.  Transient network errors, parser failures, newer
    # ids, different titles and canonical failures all remain hard failures.
    for x in errors:
        if str(x.get("id")) == str(canonical_id):
            return None, "TIE_SOURCE_INCOMPLETE", "canonical candidate failed"
        if base._norm_title(str(x.get("title") or "")) != canonical_title:
            return None, "TIE_SOURCE_INCOMPLETE", "failed tied candidate has a different title"
        if not _older_id(str(x.get("id") or ""), str(canonical_id)):
            return None, "TIE_SOURCE_INCOMPLETE", "failed tied candidate is not an older announcement id"
        if not _permanent_missing_source(x.get("error")):
            return None, "TIE_SOURCE_INCOMPLETE", "failed tied candidate is not an official 404/410"

    survivors = [x for x in parsed if not x.get("error")]
    chosen, resolution, err = ORIGINAL_RESOLVE(survivors, canonical_id)
    if chosen is None or str(chosen.get("id")) != str(canonical_id):
        return None, "TIE_SOURCE_INCOMPLETE", err or "surviving candidates do not resolve to canonical"
    return chosen, f"{resolution}_AFTER_STALE_NONCANONICAL_404", None


# Reuse the fully audited extraction implementation and alter only the tie-source
# resolver above.  All issuer filters, accounting-identity gates and provenance
# output remain unchanged.
base.resolve_candidates = resolve_candidates


if __name__ == "__main__":
    raise SystemExit(base.main())
