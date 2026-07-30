#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import fitz
import requests

import extract_stage3_financial_pdf_values as input_base
import probe_stage3_s3g1j_v17_residual_funnel as funnel_base
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard
from stage3_financial_spatial_alias_v16_7 import diagnose_spatial_balance_sheet_v16_7

EXPECTED_TOTAL_REMAINING = 82
EXPECTED_SHARDS = (0, 1, 7, 9)
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--v17-11-acceptance", required=True)
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--shards", type=int, default=64)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.shard not in EXPECTED_SHARDS or args.shards != 64:
        raise ValueError("diagnostic frozen to shards 0,1,7,9 of the 64-shard partition")

    accepted = json.loads(Path(args.v17_11_acceptance).read_text(encoding="utf-8"))
    if not accepted.get("pass"):
        raise ValueError("V17.11 acceptance is not PASS")
    if int(accepted.get("v14_remaining_count", -1)) != 113:
        raise ValueError("V17.11 acceptance lost frozen V14=113 baseline")
    if int(accepted.get("v17_11_recovery_count", -1)) != 31:
        raise ValueError("V17.11 accepted recovery count is not 31")
    if int(accepted.get("v17_11_remaining_count", -1)) != EXPECTED_TOTAL_REMAINING:
        raise ValueError("V17.11 accepted remaining count is not 82")
    if not accepted.get("all_v14_success_paths_unchanged"):
        raise ValueError("V14 success paths are not accepted unchanged")
    if not accepted.get("all_prior_v17_7_recoveries_preserved"):
        raise ValueError("V17.7 recovery set is not accepted preserved")
    if not accepted.get("no_unexpected_recoveries"):
        raise ValueError("V17.11 acceptance contains unexpected recovery IDs")
    if not accepted.get("all_recoveries_have_period_column_identity_evidence"):
        raise ValueError("V17.11 hard recovery evidence is incomplete")
    if accepted.get("stage4_alpha_locked") is not True:
        raise ValueError("Stage4/Alpha lock missing")

    target_ids = {str(x["announcement_id"]) for x in accepted.get("remaining") or []}
    if len(target_ids) != EXPECTED_TOTAL_REMAINING:
        raise ValueError(f"expected 82 unique remaining ids, got {len(target_ids)}")

    all_rows = funnel_base.read_rows(Path(args.versions))
    rows = [
        row for row in all_rows
        if row["canonical_announcement_id"] in target_ids
        and input_base.stable_shard(row["canonical_announcement_id"], args.shards) == args.shard
    ]
    rows.sort(key=lambda r: r["canonical_announcement_id"])

    session = requests.Session()
    diagnostics: list[dict] = []
    failures: list[dict] = []
    category_counts = Counter()
    concept_stage_counts = {c: Counter() for c in CONCEPTS}
    family_category = defaultdict(Counter)
    era_category = defaultdict(Counter)

    for idx, row in enumerate(rows, 1):
        aid = row["canonical_announcement_id"]
        try:
            raw = funnel_base.download(session, row["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            with fitz.open(stream=raw, filetype="pdf") as doc:
                page_count = doc.page_count
                with _mupdf_diagnostic_guard():
                    diag = diagnose_spatial_balance_sheet_v16_7(doc, row["economic_date"])
            if diag.get("recovered"):
                raise AssertionError("accepted V17.11 remaining PDF unexpectedly recovers under identical parser")
            category = funnel_base.classify(diag)
            funnel = diag.get("funnel") or {}
            counts = diag.get("candidate_counts") or {}
            stages = {c: funnel_base.concept_stage(funnel, counts, c) for c in CONCEPTS}
            for c, stage in stages.items():
                concept_stage_counts[c][stage] += 1
            category_counts[category] += 1
            family_category[row["report_family"]][category] += 1
            era_category[funnel_base.year_bucket(row["economic_date"])][category] += 1
            diagnostics.append({
                "announcement_id": aid,
                "source_code": row["source_code"],
                "report_family": row["report_family"],
                "economic_date": row["economic_date"],
                "canonical_title": row["canonical_title"],
                "sha256": digest,
                "page_count": page_count,
                "category": category,
                "concept_stage": stages,
                "candidate_counts": counts,
                "funnel": funnel,
                "v16_6_recovered": bool(diag.get("v16_6_recovered")),
                "column_role_gate": diag.get("column_role_gate"),
                "identity": diag.get("identity"),
            })
        except Exception as exc:
            failures.append({
                "announcement_id": aid,
                "source_code": row.get("source_code"),
                "error": f"{type(exc).__name__}: {exc}",
            })
        print(f"V17_12_RESIDUAL_FUNNEL shard={args.shard} {idx}/{len(rows)} aid={aid}", flush=True)

    report = {
        "gate": "S3G1J_V17_12_RESIDUAL_FUNNEL_SHARD",
        "shard": args.shard,
        "shards": args.shards,
        "input_residual_count": len(rows),
        "diagnosed_count": len(diagnostics),
        "diagnostic_failures": failures,
        "category_counts": dict(category_counts),
        "concept_stage_counts": {c: dict(counter) for c, counter in concept_stage_counts.items()},
        "family_category": {k: dict(v) for k, v in family_category.items()},
        "era_category": {k: dict(v) for k, v in era_category.items()},
        "diagnostics": diagnostics,
        "pass": not failures and len(diagnostics) == len(rows),
        "accepted_v17_11_recovery_count": 31,
        "stage4_alpha_locked": True,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "shard": args.shard,
        "input": len(rows),
        "diagnosed": len(diagnostics),
        "categories": dict(category_counts),
        "failures": failures,
        "pass": report["pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
