#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter
from pathlib import Path


def readgz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def key(r: dict) -> tuple[str, str, str, str]:
    return (r["org_id"], r["report_family"], r["economic_date"], r["source_published_at"])


def title_kind(title: str) -> str:
    if "全文" in title:
        return "FULLTEXT"
    if "正文" in title:
        return "BODY"
    if "摘要" in title:
        return "SUMMARY"
    return "PLAIN_REPORT"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--v3", required=True)
    ap.add_argument("--v3-audit", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    baseline = readgz(Path(a.baseline))
    v3 = readgz(Path(a.v3))
    v3_audit = json.loads(Path(a.v3_audit).read_text(encoding="utf-8"))
    old = {key(r): r for r in baseline}
    new = {key(r): r for r in v3}
    errors: list[str] = []

    common = set(old) & set(new)
    changed = []
    transition_counts = Counter()
    for k in sorted(common):
        before = old[k]
        after = new[k]
        if before["canonical_announcement_id"] == after["canonical_announcement_id"]:
            continue
        transition = f"{title_kind(before['canonical_title'])}->{title_kind(after['canonical_title'])}"
        transition_counts[transition] += 1
        changed.append({
            "key": list(k),
            "source_code": after["source_code"],
            "before_id": before["canonical_announcement_id"],
            "before_title": before["canonical_title"],
            "after_id": after["canonical_announcement_id"],
            "after_title": after["canonical_title"],
            "transition": transition,
        })

    added = [new[k] for k in sorted(set(new) - set(old))]
    removed = [old[k] for k in sorted(set(old) - set(new))]

    forbidden = [
        r for r in v3
        if "摘要" in r["canonical_title"] or "正文" in r["canonical_title"]
        or "已取消" in r["canonical_title"] or "取消" in r["canonical_title"]
    ]
    if forbidden:
        errors.append(f"V3 selected forbidden partial/summary/cancelled authorities: {len(forbidden)}")

    expected = {
        ("603798", "ANNUAL", "2020-12-31", "2021-04-30"): "1209876947",
        ("605177", "Q1", "2021-03-31", "2021-04-30"): "1209877352",
        ("605168", "Q1", "2021-03-31", "2021-04-19"): "1209718403",
        ("603856", "Q3", "2020-09-30", "2020-10-28"): "1208623550",
        ("603993", "Q3", "2020-09-30", "2020-10-29"): "1208635673",
    }
    actual_by_business = {
        (r["source_code"], r["report_family"], r["economic_date"], r["source_published_at"]): r
        for r in v3
    }
    expected_checks = []
    for business_key, expected_id in expected.items():
        row = actual_by_business.get(business_key)
        actual_id = row["canonical_announcement_id"] if row else None
        ok = actual_id == expected_id
        expected_checks.append({
            "key": list(business_key),
            "expected_id": expected_id,
            "actual_id": actual_id,
            "actual_title": row["canonical_title"] if row else None,
            "pass": ok,
        })
        if not ok:
            errors.append(f"known source-selection regression {business_key}: expected={expected_id} actual={actual_id}")

    report = {
        "gate": "S3G1G_V3_SOURCE_SELECTION_DIFF",
        "pass": not errors,
        "baseline_revision_moments": len(baseline),
        "v3_revision_moments": len(v3),
        "common_moments": len(common),
        "changed_canonical_same_moment": len(changed),
        "added_full_authority_moments": len(added),
        "removed_partial_only_moments": len(removed),
        "canonical_transition_counts": dict(sorted(transition_counts.items())),
        "changed_samples": changed[:200],
        "added_samples": [
            {k: r[k] for k in ("source_code","report_family","economic_date","source_published_at","canonical_announcement_id","canonical_title")}
            for r in added[:200]
        ],
        "removed_samples": [
            {k: r[k] for k in ("source_code","report_family","economic_date","source_published_at","canonical_announcement_id","canonical_title")}
            for r in removed[:200]
        ],
        "known_expected_corrections": expected_checks,
        "forbidden_selected_count": len(forbidden),
        "v3_selector_audit": {
            "explicit_full_synonym_rescues": v3_audit.get("explicit_full_synonym_rescues"),
            "partial_body_only_publication_moments": v3_audit.get("partial_body_only_publication_moments"),
            "old_full_period_groups_not_in_v3": v3_audit.get("old_full_period_groups_not_in_v3"),
            "v3_period_groups_not_in_old_full_flag": v3_audit.get("v3_period_groups_not_in_old_full_flag"),
        },
        "errors": errors,
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
