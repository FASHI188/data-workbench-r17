#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import fitz
import requests

import extract_stage3_financial_pdf_values as base
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard
from stage3_financial_spatial_alias_v16_7 import diagnose_spatial_balance_sheet_v16_7

CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
EXPECTED_TOTAL_REMAINING = 91
EXPECTED_SHARDS = (0, 1, 7, 9)


def read_rows(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17-residual-funnel",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def concept_stage(funnel: dict, counts: dict, concept: str) -> str:
    if int(counts.get(concept, 0) or 0) > 0:
        return "CANDIDATE_PRESENT"
    stages = (
        (f"{concept}_group_alias_with_right_amount", "POST_AMOUNT_FILTER"),
        (f"{concept}_group_alias_period_matched", "NO_RIGHT_AMOUNT"),
        (f"{concept}_group_alias_with_unit", "PERIOD_GATE"),
        (f"{concept}_alias_group_role", "NO_UNIT_CONTEXT"),
        (f"{concept}_alias_rows", "NO_GROUP_ROLE_BINDING"),
    )
    for key, label in stages:
        if int(funnel.get(key, 0) or 0) > 0:
            return label
    return "NO_ALIAS_ROWS"


def classify(diag: dict) -> str:
    funnel = diag.get("funnel") or {}
    counts = diag.get("candidate_counts") or {}
    v16_6_recovered = bool(diag.get("v16_6_recovered"))
    recovered = bool(diag.get("recovered"))

    if recovered:
        return "UNEXPECTED_RECOVERY"
    if v16_6_recovered:
        return "COLUMN_ROLE_GATE"
    if int(funnel.get("candidate_pages", 0) or 0) == 0:
        return "NO_CANDIDATE_PAGES"
    if int(funnel.get("formal_group_events", 0) or 0) == 0:
        return "NO_FORMAL_GROUP_EVENT"
    if all(int(counts.get(c, 0) or 0) > 0 for c in CONCEPTS):
        return "CANDIDATES_NO_VALID_IDENTITY"
    stages = {c: concept_stage(funnel, counts, c) for c in CONCEPTS}
    missing = [c for c in CONCEPTS if int(counts.get(c, 0) or 0) == 0]
    if missing:
        deepest = [stages[c] for c in missing]
        priority = (
            "POST_AMOUNT_FILTER",
            "NO_RIGHT_AMOUNT",
            "PERIOD_GATE",
            "NO_UNIT_CONTEXT",
            "NO_GROUP_ROLE_BINDING",
            "NO_ALIAS_ROWS",
        )
        for label in priority:
            if label in deepest:
                return f"MISSING_CONCEPT_{label}"
        return "MISSING_CONCEPT_OTHER"
    return "OTHER_FAIL_CLOSED"


def year_bucket(value: str) -> str:
    try:
        year = int(str(value)[:4])
    except ValueError:
        return "UNKNOWN"
    if year <= 2017:
        return "2014-2017"
    if year <= 2021:
        return "2018-2021"
    return "2022-2026"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--exact-summary", required=True)
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--shards", type=int, default=64)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.shard not in EXPECTED_SHARDS or args.shards != 64:
        raise ValueError("diagnostic frozen to shards 0,1,7,9 of the 64-shard partition")

    summary = json.loads(Path(args.exact_summary).read_text(encoding="utf-8"))
    if not summary.get("pass") or int(summary.get("v16_remaining_count", -1)) != EXPECTED_TOTAL_REMAINING:
        raise ValueError("exact-113 upstream summary is not the accepted 91-residual state")
    target_ids = {str(x["announcement_id"]) for x in summary.get("v16_remaining") or []}
    if len(target_ids) != EXPECTED_TOTAL_REMAINING:
        raise ValueError(f"expected 91 unique residual ids, got {len(target_ids)}")

    rows = [
        row for row in read_rows(Path(args.versions))
        if row["canonical_announcement_id"] in target_ids
        and base.stable_shard(row["canonical_announcement_id"], args.shards) == args.shard
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
            raw = download(session, row["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            with fitz.open(stream=raw, filetype="pdf") as doc:
                page_count = doc.page_count
                with _mupdf_diagnostic_guard():
                    diag = diagnose_spatial_balance_sheet_v16_7(doc, row["economic_date"])
            category = classify(diag)
            funnel = diag.get("funnel") or {}
            counts = diag.get("candidate_counts") or {}
            stages = {c: concept_stage(funnel, counts, c) for c in CONCEPTS}
            for c, stage in stages.items():
                concept_stage_counts[c][stage] += 1
            category_counts[category] += 1
            family_category[row["report_family"]][category] += 1
            era_category[year_bucket(row["economic_date"])][category] += 1
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
        print(f"V17_RESIDUAL_FUNNEL shard={args.shard} {idx}/{len(rows)} aid={aid}", flush=True)

    report = {
        "gate": "S3G1J_V17_RESIDUAL_FUNNEL_SHARD",
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
