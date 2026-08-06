#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path

import select_stage3_financial_report_versions_v3_1 as selector_v3_1

FIELDS = [
    "exchange",
    "source_code",
    "effective_code",
    "org_id",
    "report_family",
    "economic_date",
    "source_published_at",
    "effective_session",
    "available_at",
    "announcement_id",
    "announcement_title",
    "source_url",
    "revision_kind",
    "publication_relation_to_full_authority",
    "prior_full_authority_date",
    "later_full_authority_date",
    "treatment",
]


def readgz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--full-versions", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    raw = readgz(Path(args.ledger))
    full = readgz(Path(args.full_versions))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    full_ids = {r["canonical_announcement_id"] for r in full}
    full_dates: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    full_moments = set()
    for r in full:
        pk = (r["org_id"], r["report_family"], r["economic_date"])
        full_dates[pk].append(r["source_published_at"])
        full_moments.add((*pk, r["source_published_at"]))
    for pk in full_dates:
        full_dates[pk] = sorted(set(full_dates[pk]))

    rows = []
    relation_counts: dict[str, int] = defaultdict(int)
    for r in raw:
        if not r.get("economic_date"):
            continue
        tc = selector_v3_1.title_class(r.get("announcement_title", ""), r["report_family"])
        if not tc or tc[0] != "PARTIAL_REPORT_BODY":
            continue
        pk = (r["org_id"], r["report_family"], r["economic_date"])
        moment = (*pk, r["source_published_at"])
        # A body on the same publication moment as a selected complete report is
        # merely a redundant variant.  Only body-only moments belong in this ledger.
        if moment in full_moments:
            continue
        dates = full_dates.get(pk, [])
        prior = [d for d in dates if d < r["source_published_at"]]
        later = [d for d in dates if d > r["source_published_at"]]
        if later:
            relation = "BODY_PRECEDES_LATER_FULL_AUTHORITY"
        elif prior:
            relation = "BODY_FOLLOWS_PRIOR_FULL_AUTHORITY"
        else:
            relation = "BODY_ONLY_NO_FULL_AUTHORITY_IN_FROZEN_LEDGER"
        relation_counts[relation] += 1
        if r["announcement_id"] in full_ids:
            errors.append(f"partial body also selected as full authority: {r['announcement_id']}")
        rows.append(
            {
                "exchange": r["exchange"],
                "source_code": r["source_code"],
                "effective_code": r["effective_code"],
                "org_id": r["org_id"],
                "report_family": r["report_family"],
                "economic_date": r["economic_date"],
                "source_published_at": r["source_published_at"],
                "effective_session": r["effective_session"],
                "available_at": r["available_at"],
                "announcement_id": r["announcement_id"],
                "announcement_title": r["announcement_title"],
                "source_url": r["source_url"],
                "revision_kind": r["revision_kind"],
                "publication_relation_to_full_authority": relation,
                "prior_full_authority_date": prior[-1] if prior else "",
                "later_full_authority_date": later[0] if later else "",
                "treatment": "PARTIAL_SOURCE_EVENT_KEEP_PIT_DO_NOT_ASSERT_COMPLETE_BALANCE_SHEET",
            }
        )

    rows.sort(
        key=lambda r: (
            r["source_published_at"],
            r["exchange"],
            r["source_code"],
            r["report_family"],
            r["economic_date"],
            int(r["announcement_id"]) if r["announcement_id"].isdigit() else r["announcement_id"],
        )
    )
    data_path = out / "stage3_partial_report_body_events_v12.csv.gz"
    with gzip.open(data_path, "wt", encoding="utf-8", newline="", compresslevel=9) as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    unique_moments = {
        (r["org_id"], r["report_family"], r["economic_date"], r["source_published_at"])
        for r in rows
    }
    unique_periods = {(r["org_id"], r["report_family"], r["economic_date"]) for r in rows}
    report = {
        "gate": "S3G1J_V12_PARTIAL_BODY_PIT_LEDGER",
        "pass": not errors,
        "partial_body_rows": len(rows),
        "partial_body_publication_moments": len(unique_moments),
        "partial_body_period_groups": len(unique_periods),
        "relation_counts": dict(sorted(relation_counts.items())),
        "full_authority_revision_moments": len(full),
        "policy": {
            "partial_body_is_not_full_statement_authority": True,
            "partial_body_event_time_is_preserved": True,
            "partial_values_may_be_extracted_later_only_from_original_source_with_sha": True,
            "partial_body_may_not_assert_total_assets_liabilities_equity_without_validated_joint_block": True,
            "no_current_f10_backfill": True,
        },
        "data_file": data_path.name,
        "errors": errors,
    }
    (out / "stage3_partial_report_body_events_v12_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
