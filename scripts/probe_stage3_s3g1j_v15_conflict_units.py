#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

import extract_stage3_financial_pdf_values_v10 as v15

TARGET_CANONICAL_IDS = {
    "1208613323",
    "1208613147",
    "1209859456",
    "1210913320",
    "1213052590",
    "1225269023",
}


def _dec(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def _observation_meta(obs: dict) -> dict:
    return {
        "status": obs.get("status"),
        "raw_value": obs.get("raw_value"),
        "normalized_cny_value": obs.get("normalized_cny_value"),
        "unit": obs.get("unit"),
        "unit_multiplier": obs.get("unit_multiplier"),
        "page": obs.get("page"),
        "matched_alias": obs.get("matched_alias"),
        "extraction_scope": obs.get("extraction_scope"),
        "confidence": obs.get("confidence"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    versions = _read_versions(Path(args.versions))
    missing = TARGET_CANONICAL_IDS - set(versions)
    if missing:
        raise ValueError(f"missing target version rows: {sorted(missing)}")

    session = requests.Session()
    rows = []
    diagnostic_errors = []

    for canonical_id in sorted(TARGET_CANONICAL_IDS):
        version = versions[canonical_id]
        candidates, excluded = v15.v14.v9.base.filter_candidates_by_issuer(
            v15.v14.v9.base.candidate_list(version),
            version["source_code"],
            canonical_id,
        )
        parsed = []
        for candidate in candidates:
            ev = {"id": candidate["id"], "title": candidate["title"], "url": candidate["url"]}
            try:
                raw = v15.v14.v9.base.get_pdf(session, candidate["url"])
                result = v15.v14.parse_pdf_bytes(raw)
                ev.update({
                    "sha256": v15.v14.v9.base.sha(raw),
                    "bytes": len(raw),
                    "parsed": result,
                })
                if result.get("validation_errors"):
                    ev["error"] = "; ".join(map(str, result["validation_errors"]))
            except Exception as exc:
                ev["error"] = repr(exc)
            parsed.append(ev)

        usable = [candidate for candidate in parsed if v15._is_independently_usable(candidate)]
        bads = [candidate for candidate in parsed if not v15._is_independently_usable(candidate)]
        record = {
            "canonical_announcement_id": canonical_id,
            "source_code": version["source_code"],
            "report_family": version["report_family"],
            "economic_date": version["economic_date"],
            "canonical_title": version["canonical_title"],
            "usable_count": len(usable),
            "bad_count": len(bads),
            "excluded": excluded,
            "candidates": [],
            "overlap": [],
        }
        for candidate in parsed:
            result = candidate.get("parsed") or {}
            record["candidates"].append({
                "id": candidate.get("id"),
                "title": candidate.get("title"),
                "error": candidate.get("error"),
                "bytes": candidate.get("bytes"),
                "page_count": result.get("page_count"),
                "tier1_found": result.get("tier1_found"),
                "tier2_found": result.get("tier2_found"),
                "balance_sheet_block": result.get("balance_sheet_block"),
            })

        if len(usable) == 1 and len(bads) == 1:
            good, bad = usable[0], bads[0]
            go = ((good.get("parsed") or {}).get("observations") or {})
            bo = ((bad.get("parsed") or {}).get("observations") or {})
            for concept in sorted(set(go) & set(bo)):
                g = go.get(concept) or {}
                b = bo.get(concept) or {}
                if g.get("status") != "FOUND" or b.get("status") != "FOUND":
                    continue
                gv = _dec(g.get("normalized_cny_value"))
                bv = _dec(b.get("normalized_cny_value"))
                if gv is None or bv is None:
                    continue
                gmult = _dec(g.get("unit_multiplier")) or Decimal("1")
                bmult = _dec(b.get("unit_multiplier")) or Decimal("1")
                diff = abs(gv - bv)
                # A value reported to 2 decimals in a declared monetary unit has
                # half of 0.01 unit as its maximal normal rounding error.
                half_step_good = abs(gmult) * Decimal("0.005")
                half_step_bad = abs(bmult) * Decimal("0.005")
                allowed_rounding = max(half_step_good, half_step_bad)
                record["overlap"].append({
                    "concept": concept,
                    "good_candidate_id": good.get("id"),
                    "bad_candidate_id": bad.get("id"),
                    "good": _observation_meta(g),
                    "bad": _observation_meta(b),
                    "absolute_difference_cny": str(diff),
                    "half_smallest_display_step_cny": str(allowed_rounding),
                    "explainable_by_declared_unit_rounding": diff <= allowed_rounding,
                    "relative_difference": str(diff / max(abs(gv), abs(bv), Decimal("1"))),
                })
        else:
            diagnostic_errors.append(
                f"{canonical_id}: expected 1 usable + 1 bad, got {len(usable)} + {len(bads)}"
            )
        rows.append(record)

    report = {
        "gate": "S3G1J_V15_SIX_TIE_CONFLICT_UNIT_DIAGNOSTIC",
        "diagnostic_pass": not diagnostic_errors,
        "sample_count": len(rows),
        "rows": rows,
        "diagnostic_errors": diagnostic_errors,
        "policy": {
            "diagnostic_only": True,
            "no_resolver_relaxation": True,
            "rounding_test": "abs(value_a-value_b) <= max(unit_multiplier_a, unit_multiplier_b)*0.005",
            "rationale": "two-decimal display precision in declared monetary unit",
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["diagnostic_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
