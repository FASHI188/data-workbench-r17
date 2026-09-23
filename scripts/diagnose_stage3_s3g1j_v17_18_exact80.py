#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import fitz
import requests

import diagnose_stage3_s3g1j_v17_11_remaining as legacy
import stage3_financial_coordinate_fallback_v14 as v14
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard
from stage3_financial_pdf_parser_v12 import parse_pdf_bytes
from stage3_financial_spatial_alias_v17_17 import diagnose_spatial_balance_sheet_v17_17

CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
EXPECTED_SOURCE_TOTAL = 82
EXPECTED_RECOVERED = {"1212731093", "1225153907"}
EXPECTED_REMAINING = 80
EXPECTED_SHARDS = (0, 1, 7, 9)


def _current_funnel_category(diagnostic: dict) -> str:
    base_funnel = diagnostic.get("base_funnel") or {}
    counts = diagnostic.get("candidate_counts") or {}
    if diagnostic.get("recovered"):
        return "UNEXPECTED_RECOVERY"
    if diagnostic.get("identity_recovered_before_column_gate"):
        return "COLUMN_ROLE_GATE"
    if int(base_funnel.get("candidate_pages", 0) or 0) == 0:
        return "NO_CANDIDATE_PAGES"
    if int(base_funnel.get("formal_group_events", 0) or 0) == 0:
        return "NO_FORMAL_GROUP_EVENT"
    if all(int(counts.get(concept, 0) or 0) > 0 for concept in CONCEPTS):
        return "CANDIDATES_NO_VALID_IDENTITY"
    missing = [concept for concept in CONCEPTS if int(counts.get(concept, 0) or 0) == 0]
    stages = [legacy._concept_stage(base_funnel, counts, concept) for concept in missing]
    for label in (
        "POST_AMOUNT_FILTER",
        "NO_RIGHT_AMOUNT",
        "PERIOD_GATE",
        "NO_UNIT_CONTEXT",
        "NO_GROUP_ROLE_BINDING",
        "NO_ALIAS_ROWS",
    ):
        if label in stages:
            return f"MISSING_CONCEPT_{label}"
    return "OTHER_FAIL_CLOSED"


def _extension_tags(diagnostic: dict) -> list[str]:
    tags: list[str] = []
    bridge = diagnostic.get("bridge_funnel") or {}
    strict = diagnostic.get("strict_equity_funnel") or {}
    strict_counts = diagnostic.get("strict_candidate_counts") or {}
    if any(int(value or 0) > 0 for value in bridge.values() if isinstance(value, (int, float))):
        tags.append("V17_15_BRIDGE_EVIDENCE_PRESENT")
    if any(int(value or 0) > 0 for value in strict.values() if isinstance(value, (int, float))):
        tags.append("V17_17_STRICT_EQUITY_EVIDENCE_PRESENT")
    if int(strict_counts.get("TOTAL_EQUITY", 0) or 0) > 0:
        tags.append("V17_17_STRICT_TOTAL_EQUITY_CANDIDATE_PRESENT")
    if diagnostic.get("identity_recovered_before_column_gate") and not diagnostic.get("recovered"):
        tags.append("IDENTITY_PRESENT_COLUMN_EVIDENCE_FAILED")
    return tags


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", required=True)
    parser.add_argument("--v17-11-acceptance", required=True)
    parser.add_argument("--v17-17-summary", required=True)
    parser.add_argument("--shard", required=True, type=int)
    parser.add_argument("--shards", default=64, type=int)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.shards != 64 or args.shard not in EXPECTED_SHARDS:
        raise ValueError("V17.18 diagnostic is frozen to shards 0,1,7,9 of the 64-shard partition")

    accepted = json.loads(Path(args.v17_11_acceptance).read_text(encoding="utf-8"))
    if not accepted.get("pass") or int(accepted.get("v17_11_remaining_count", -1)) != EXPECTED_SOURCE_TOTAL:
        raise ValueError("not the accepted V17.11 exact-82 source state")
    source_rows = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if len(source_rows) != EXPECTED_SOURCE_TOTAL:
        raise ValueError(f"expected 82 accepted source rows, got {len(source_rows)}")

    combined = json.loads(Path(args.v17_17_summary).read_text(encoding="utf-8"))
    recovered = {str(value) for value in combined.get("production_recovered_announcement_ids") or []}
    if not combined.get("pass") or int(combined.get("input_count", -1)) != EXPECTED_SOURCE_TOTAL:
        raise ValueError("not the accepted V17.17 combined exact-82 production state")
    if recovered != EXPECTED_RECOVERED:
        raise ValueError(f"unexpected accepted recovery set {sorted(recovered)}")
    if int(combined.get("remaining_fail_closed_count", -1)) != EXPECTED_REMAINING:
        raise ValueError("combined production summary does not leave exact 80")

    target_ids = set(source_rows) - recovered
    if len(target_ids) != EXPECTED_REMAINING:
        raise ValueError(f"expected exact 80 target ids, got {len(target_ids)}")

    rows = [
        row
        for row in legacy._read_rows(Path(args.versions))
        if row["canonical_announcement_id"] in target_ids
        and legacy.base.stable_shard(row["canonical_announcement_id"], args.shards) == args.shard
    ]
    rows.sort(key=lambda row: row["canonical_announcement_id"])

    session = requests.Session()
    diagnostics: list[dict] = []
    failures: list[dict] = []
    funnel_counts: Counter = Counter()
    structural_counts: Counter = Counter()
    extension_counts: Counter = Counter()
    family_counts: defaultdict = defaultdict(Counter)

    for index, row in enumerate(rows, 1):
        aid = row["canonical_announcement_id"]
        try:
            raw = legacy._download(session, row["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            expected_sha = str(source_rows[aid]["sha256"])
            if digest != expected_sha:
                raise ValueError(f"source SHA changed expected={expected_sha} actual={digest}")
            with fitz.open(stream=raw, filetype="pdf") as doc:
                with _mupdf_diagnostic_guard():
                    parsed = parse_pdf_bytes(raw, row["economic_date"])
                    spatial = diagnose_spatial_balance_sheet_v17_17(doc, row["economic_date"])
                    role_events = v14._statement_events(doc)
                    pages = [legacy._page_structure(doc[pno], pno + 1) for pno in range(doc.page_count)]

            validation_errors = list(parsed.get("validation_errors") or [])
            block = parsed.get("balance_sheet_block")
            if block is not None or not validation_errors:
                raise ValueError("accepted residual no longer remains fail closed")

            category = _current_funnel_category(spatial)
            if category == "UNEXPECTED_RECOVERY":
                raise ValueError("spatial diagnostic unexpectedly recovered accepted residual")
            structural_tags = legacy._structural_category(pages, role_events, validation_errors)
            extension_tags = _extension_tags(spatial)
            funnel_counts[category] += 1
            family_counts[row["report_family"]][category] += 1
            for tag in structural_tags:
                structural_counts[tag] += 1
            for tag in extension_tags:
                extension_counts[tag] += 1

            observations = parsed.get("observations") or {}
            raw_balance_found = {
                concept: (observations.get(concept) or {}).get("status") == "FOUND"
                for concept in CONCEPTS
            }
            evidence_pages = [
                page
                for page in pages
                if page["title_lines"]
                or page["terminal_lines"]
                or page["continuation_lines"]
                or page["unit_lines"]
                or page["date_lines"]
                or page["low_text_with_image"]
            ]
            diagnostics.append(
                {
                    "announcement_id": aid,
                    "source_code": row["source_code"],
                    "report_family": row["report_family"],
                    "economic_date": row["economic_date"],
                    "canonical_title": row["canonical_title"],
                    "canonical_source_url": row["canonical_source_url"],
                    "source_sha256": digest,
                    "source_bytes": len(raw),
                    "page_count": len(pages),
                    "production_parser_version": parsed.get("parser_version"),
                    "production_validation_errors": validation_errors,
                    "production_balance_sheet_block": block,
                    "raw_balance_concepts_found": raw_balance_found,
                    "raw_balance_all_found": all(raw_balance_found.values()),
                    "funnel_category": category,
                    "structural_tags": structural_tags,
                    "extension_tags": extension_tags,
                    "statement_role_event_count": len(role_events),
                    "statement_role_events": role_events,
                    "candidate_counts": spatial.get("candidate_counts"),
                    "strict_candidate_counts": spatial.get("strict_candidate_counts"),
                    "base_funnel": spatial.get("base_funnel"),
                    "bridge_funnel": spatial.get("bridge_funnel"),
                    "strict_equity_funnel": spatial.get("strict_equity_funnel"),
                    "identity_recovered_before_column_gate": spatial.get("identity_recovered_before_column_gate"),
                    "identity": spatial.get("identity"),
                    "column_role_gate": spatial.get("column_role_gate"),
                    "evidence_pages": evidence_pages,
                    "low_text_image_page_count": sum(bool(page["low_text_with_image"]) for page in pages),
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "announcement_id": aid,
                    "source_code": row.get("source_code"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(f"S3G1J_V17_18_EXACT80 shard={args.shard} {index}/{len(rows)} aid={aid}", flush=True)

    report = {
        "gate": "S3G1J_V17_18_EXACT_80_RESIDUAL_DIAGNOSTIC_SHARD",
        "diagnostic_only": True,
        "no_parser_change": True,
        "no_ocr": True,
        "accounting_tolerance_changed": False,
        "global_row_tolerance_changed": False,
        "source_policy_changed": False,
        "shard": args.shard,
        "shards": args.shards,
        "input_residual_count": len(rows),
        "diagnosed_count": len(diagnostics),
        "source_sha_match_count": len(diagnostics),
        "diagnostic_failures": failures,
        "funnel_category_counts": dict(funnel_counts),
        "structural_tag_counts": dict(structural_counts),
        "extension_tag_counts": dict(extension_counts),
        "family_funnel_counts": {key: dict(value) for key, value in family_counts.items()},
        "diagnostics": diagnostics,
        "pass": not failures and len(diagnostics) == len(rows),
        "stage4_alpha_locked": True,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "shard": args.shard,
                "input": len(rows),
                "diagnosed": len(diagnostics),
                "funnel_categories": dict(funnel_counts),
                "structural_tags": dict(structural_counts),
                "extension_tags": dict(extension_counts),
                "failures": failures,
                "pass": report["pass"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
