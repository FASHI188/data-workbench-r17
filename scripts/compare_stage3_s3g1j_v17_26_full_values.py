#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import Iterable

TARGETS = {
    "1207035181": {
        "source_sha256": "320e3a950a4768e73766d57a09bcf34d893d4da949b8ed5a1b2f887852e76229",
        "required_concepts": {
            "TOTAL_ASSETS": "760508375.73",
            "TOTAL_LIABILITIES": "176499397.46",
            "TOTAL_EQUITY": "584008978.27",
        },
    },
    "1221568845": {
        "source_sha256": "fa72059d35715f20df620691538528f720fe3ae42581c172c853f26799befb93",
        "required_concepts": {
            "TOTAL_ASSETS": "3642768851.01",
            "TOTAL_LIABILITIES": "2382626915.88",
            "TOTAL_EQUITY": "1260141935.13",
        },
    },
}

STABLE_FIELDS = (
    "exchange",
    "source_code",
    "effective_code",
    "issuer_org_id",
    "report_family",
    "economic_date",
    "announcement_id",
    "revision_sequence",
    "source_published_at",
    "effective_session",
    "available_at",
    "concept",
    "raw_value",
    "normalized_cny_value",
    "unit",
    "unit_multiplier",
    "source_url",
    "source_sha256",
    "source_format",
    "page",
    "matched_alias",
    "confidence",
)

EXPECTED_PREVIOUS_NON_TARGET_ROWS = 1_051_772
EXPECTED_PREVIOUS_NON_TARGET_SHA256 = (
    "f9f7751943b113db9488b0b7b1d33ffbd93e1e3eb56486ca8e399f252a5953b4"
)
EXPECTED_CURRENT_TOTAL_ROWS = 1_051_778


def _open_rows(path: Path) -> Iterable[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in STABLE_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"missing stable fields: {missing}")
        yield from reader


def _semantic_line(row: dict[str, str]) -> bytes:
    return ("\x1f".join(row.get(field, "") for field in STABLE_FIELDS) + "\n").encode(
        "utf-8"
    )


def scan(path: Path) -> dict:
    digest = hashlib.sha256()
    non_target_rows = 0
    total_rows = 0
    target_rows: dict[str, list[dict[str, str]]] = {aid: [] for aid in TARGETS}
    for row in _open_rows(path):
        total_rows += 1
        aid = str(row.get("announcement_id", ""))
        if aid in TARGETS:
            target_rows[aid].append(row)
            continue
        digest.update(_semantic_line(row))
        non_target_rows += 1
    return {
        "total_row_count": total_rows,
        "non_target_row_count": non_target_rows,
        "non_target_semantic_sha256": digest.hexdigest(),
        "target_rows": target_rows,
    }


def _target_summary(rows: list[dict[str, str]], expected: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    expected_sha = expected["source_sha256"]
    expected_concepts = set(expected["required_concepts"])
    source_shas = sorted({row.get("source_sha256", "") for row in rows})
    by_concept: dict[str, list[str]] = {}
    for row in rows:
        by_concept.setdefault(row.get("concept", ""), []).append(
            row.get("normalized_cny_value", "")
        )

    if len(rows) != len(expected_concepts):
        errors.append(
            f"numeric row count expected={len(expected_concepts)} actual={len(rows)}"
        )
    if set(by_concept) != expected_concepts:
        errors.append(
            f"concept scope expected={sorted(expected_concepts)} "
            f"actual={sorted(by_concept)}"
        )
    if source_shas != [expected_sha]:
        errors.append(f"source SHA mismatch expected={expected_sha} actual={source_shas}")
    for concept, value in expected["required_concepts"].items():
        actual = by_concept.get(concept, [])
        if actual != [value]:
            errors.append(f"{concept} expected one {value}, actual={actual}")

    return (
        {
            "numeric_row_count": len(rows),
            "concepts": sorted(by_concept),
            "source_sha256_values": source_shas,
            "required_concept_values": {
                concept: by_concept.get(concept, [])
                for concept in expected["required_concepts"]
            },
        },
        errors,
    )


def compare(previous_path: Path, current_path: Path) -> dict:
    previous = scan(previous_path)
    current = scan(current_path)
    errors: list[str] = []

    if previous["non_target_row_count"] != EXPECTED_PREVIOUS_NON_TARGET_ROWS:
        errors.append(
            "previous non-target row count changed "
            f"expected={EXPECTED_PREVIOUS_NON_TARGET_ROWS} "
            f"actual={previous['non_target_row_count']}"
        )
    if previous["non_target_semantic_sha256"] != EXPECTED_PREVIOUS_NON_TARGET_SHA256:
        errors.append(
            "previous non-target semantic SHA changed "
            f"expected={EXPECTED_PREVIOUS_NON_TARGET_SHA256} "
            f"actual={previous['non_target_semantic_sha256']}"
        )
    if current["total_row_count"] != EXPECTED_CURRENT_TOTAL_ROWS:
        errors.append(
            f"current total row count expected={EXPECTED_CURRENT_TOTAL_ROWS} "
            f"actual={current['total_row_count']}"
        )
    if current["non_target_row_count"] != previous["non_target_row_count"]:
        errors.append(
            "non-target numeric row count drift "
            f"previous={previous['non_target_row_count']} "
            f"current={current['non_target_row_count']}"
        )
    if current["non_target_semantic_sha256"] != previous["non_target_semantic_sha256"]:
        errors.append(
            "non-target numeric semantic SHA drift "
            f"previous={previous['non_target_semantic_sha256']} "
            f"current={current['non_target_semantic_sha256']}"
        )

    target_evidence: dict[str, dict] = {}
    for aid, expected in TARGETS.items():
        previous_rows = previous["target_rows"][aid]
        current_rows = current["target_rows"][aid]
        if previous_rows:
            errors.append(f"previous full basis unexpectedly contains target numeric rows {aid}")
        summary, target_errors = _target_summary(current_rows, expected)
        target_evidence[aid] = summary
        errors.extend(f"{aid}: {error}" for error in target_errors)

    return {
        "gate": "S3G1J_V17_26_FULL_VALUES_NON_REGRESSION",
        "pass": not errors,
        "stable_fields": list(STABLE_FIELDS),
        "excluded_generation_fields": ["extraction_method", "methodology_version"],
        "previous_total_row_count": previous["total_row_count"],
        "current_total_row_count": current["total_row_count"],
        "previous_non_target_row_count": previous["non_target_row_count"],
        "current_non_target_row_count": current["non_target_row_count"],
        "previous_non_target_semantic_sha256": previous[
            "non_target_semantic_sha256"
        ],
        "current_non_target_semantic_sha256": current[
            "non_target_semantic_sha256"
        ],
        "target_announcement_ids": sorted(TARGETS),
        "target_evidence": target_evidence,
        "non_balance_target_concepts_allowed": False,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    report = compare(Path(args.previous), Path(args.current))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
