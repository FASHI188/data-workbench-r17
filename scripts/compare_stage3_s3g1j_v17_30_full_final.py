#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

TARGET_IDS = ("1223347318", "1223407043")
TARGET_SET = set(TARGET_IDS)
EXPECTED_DOCUMENT_ROWS = 121354
EXPECTED_PREVIOUS_NUMERIC_ROWS = 1051820
EXPECTED_CURRENT_NUMERIC_ROWS = 1051826
EXPECTED_CURRENT_DOCUMENT_ERRORS = 1362
EXPECTED_CURRENT_SOURCE_INCOMPLETE = 1265
EXPECTED_CURRENT_VALUE_CONFLICT = 14
EXPECTED_CURRENT_UNRESOLVED_TIES = 1279
EXPECTED_TARGET_NUMERIC_ROWS = 6
EXPECTED_METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V20_V17_30_EXACT_SOURCE_CROSS_PAGE_GROUP_EQUITY_PRODUCTION"
EXPECTED_METHODOLOGY = "V3.3.14-V17.30"

TARGETS = {
    "1223347318": {
        "source_code": "605289",
        "economic_date": "2025-03-31",
        "source_sha256": "d765c94532cd41a496d147da72cbff392bce4ff776b41b88d95dcf3f1fb697c8",
        "source_bytes": "492929",
        "values": {
            "TOTAL_ASSETS": ("2250857154.79", "7", "资产总计"),
            "TOTAL_LIABILITIES": ("954370096.74", "8", "负债合计"),
            "TOTAL_EQUITY": ("1296487058.05", "8", "所有者权益（或股东权益）合计"),
        },
    },
    "1223407043": {
        "source_code": "605162",
        "economic_date": "2024-12-31",
        "source_sha256": "7540a56179783625ac256726480ef32faf85a893549057fe9e6546abfd6ee903",
        "source_bytes": "1367714",
        "values": {
            "TOTAL_ASSETS": ("1885230514.78", "83", "资产总计"),
            "TOTAL_LIABILITIES": ("564752701.93", "84", "负债合计"),
            "TOTAL_EQUITY": ("1320477812.85", "84", "所有者权益（或股东权益）合计"),
        },
    },
}


def read_csv_gz(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def stable_counter(
    rows: Iterable[dict[str, str]],
    fields: list[str],
    excluded: set[str] | None = None,
) -> Counter[tuple[str, ...]]:
    excluded = excluded or set()
    selected = [field for field in fields if field not in excluded]
    return Counter(tuple(row.get(field, "") for field in selected) for row in rows)


def stable_sha(
    rows: Iterable[dict[str, str]],
    fields: list[str],
    excluded: set[str] | None = None,
) -> str:
    counter = stable_counter(rows, fields, excluded)
    h = hashlib.sha256()
    for key, count in sorted(counter.items()):
        h.update(
            json.dumps([list(key), count], ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        h.update(b"\n")
    return h.hexdigest()


def tie_taxonomy(rows: Iterable[dict[str, str]]) -> dict[str, int]:
    c = Counter(row.get("tie_resolution", "") for row in rows)
    return {
        "TIE_SOURCE_INCOMPLETE": c["TIE_SOURCE_INCOMPLETE"],
        "TIE_VALUE_CONFLICT": c["TIE_VALUE_CONFLICT"],
    }


def by_id(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        aid = row.get("announcement_id", "")
        if not aid:
            raise ValueError("document row missing announcement_id")
        if aid in result:
            raise ValueError(f"duplicate document announcement_id {aid}")
        result[aid] = row
    return result


def numeric_target_map(rows: Iterable[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        aid = row.get("announcement_id", "")
        if aid not in TARGET_SET:
            continue
        key = (aid, row.get("concept", ""))
        if key in result:
            raise ValueError(f"duplicate target numeric row {key}")
        result[key] = row
    return result


def assert_target_documents(current_docs: list[dict[str, str]]) -> None:
    current = by_id(current_docs)
    for aid, expected in TARGETS.items():
        row = current.get(aid)
        if row is None:
            raise ValueError(f"missing target document {aid}")
        if row.get("source_code") != expected["source_code"]:
            raise ValueError(f"{aid}: source_code drift")
        if row.get("economic_date") != expected["economic_date"]:
            raise ValueError(f"{aid}: economic_date drift")
        if row.get("selected_source_sha256") != expected["source_sha256"]:
            raise ValueError(f"{aid}: selected source SHA drift")
        if row.get("selected_source_bytes") != expected["source_bytes"]:
            raise ValueError(f"{aid}: selected source bytes drift")
        if row.get("document_status") != "PASS":
            raise ValueError(f"{aid}: target is not PASS")
        if row.get("tie_resolution") != "SINGLE_CANONICAL":
            raise ValueError(f"{aid}: target is not SINGLE_CANONICAL")
        if row.get("tier2_found") != "3":
            raise ValueError(f"{aid}: tier2_found must be 3")
        if row.get("numeric_observations") != "3":
            raise ValueError(f"{aid}: numeric_observations must be 3")
        if row.get("document_error"):
            raise ValueError(f"{aid}: target retained document_error")


def assert_target_numeric(current_values: list[dict[str, str]]) -> None:
    rows = numeric_target_map(current_values)
    expected_keys = {
        (aid, concept)
        for aid, target in TARGETS.items()
        for concept in target["values"]
    }
    if set(rows) != expected_keys:
        raise ValueError(
            f"target numeric key drift missing={sorted(expected_keys-set(rows))} "
            f"extra={sorted(set(rows)-expected_keys)}"
        )
    for (aid, concept), row in rows.items():
        target = TARGETS[aid]
        value, page, alias = target["values"][concept]
        if row.get("source_code") != target["source_code"]:
            raise ValueError(f"{aid} {concept}: source_code drift")
        if row.get("economic_date") != target["economic_date"]:
            raise ValueError(f"{aid} {concept}: economic_date drift")
        if row.get("source_sha256") != target["source_sha256"]:
            raise ValueError(f"{aid} {concept}: source SHA drift")
        if row.get("source_format") != "PDF":
            raise ValueError(f"{aid} {concept}: source_format is not PDF")
        if row.get("normalized_cny_value") != value:
            raise ValueError(f"{aid} {concept}: value drift")
        if row.get("page") != page:
            raise ValueError(f"{aid} {concept}: page drift")
        if row.get("matched_alias") != alias:
            raise ValueError(f"{aid} {concept}: alias drift")
        if row.get("unit") != "元" or row.get("unit_multiplier") != "1":
            raise ValueError(f"{aid} {concept}: unit drift")
        if row.get("confidence") != "HIGH":
            raise ValueError(f"{aid} {concept}: confidence drift")
        if row.get("extraction_method") != EXPECTED_METHOD:
            raise ValueError(f"{aid} {concept}: extraction method drift")
        if row.get("methodology_version") != EXPECTED_METHODOLOGY:
            raise ValueError(f"{aid} {concept}: methodology drift")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--previous-documents", required=True)
    ap.add_argument("--previous-values", required=True)
    ap.add_argument("--current-documents", required=True)
    ap.add_argument("--current-values", required=True)
    ap.add_argument("--promotion-documents", required=True)
    ap.add_argument("--promotion-values", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    prev_doc_fields, prev_docs = read_csv_gz(Path(args.previous_documents))
    prev_value_fields, prev_values = read_csv_gz(Path(args.previous_values))
    cur_doc_fields, cur_docs = read_csv_gz(Path(args.current_documents))
    cur_value_fields, cur_values = read_csv_gz(Path(args.current_values))
    gold_doc_fields, gold_docs = read_csv_gz(Path(args.promotion_documents))
    gold_value_fields, gold_values = read_csv_gz(Path(args.promotion_values))

    errors: list[str] = []
    report: dict[str, object] = {
        "gate": "S3G1J_V17_30_FULL_BASIS_NON_REGRESSION_V1",
        "target_announcement_ids": list(TARGET_IDS),
        "previous_document_count": len(prev_docs),
        "current_document_count": len(cur_docs),
        "previous_numeric_count": len(prev_values),
        "current_numeric_count": len(cur_values),
    }

    try:
        if len(prev_docs) != EXPECTED_DOCUMENT_ROWS or len(cur_docs) != EXPECTED_DOCUMENT_ROWS:
            raise ValueError(
                f"document population drift prev={len(prev_docs)} current={len(cur_docs)}"
            )
        if len(prev_values) != EXPECTED_PREVIOUS_NUMERIC_ROWS:
            raise ValueError(f"previous numeric population drift {len(prev_values)}")
        if len(cur_values) != EXPECTED_CURRENT_NUMERIC_ROWS:
            raise ValueError(f"current numeric population drift {len(cur_values)}")
        if prev_doc_fields != cur_doc_fields:
            raise ValueError("document schema drift")
        if prev_value_fields != cur_value_fields:
            raise ValueError("numeric schema drift")

        prev_by_id = by_id(prev_docs)
        cur_by_id = by_id(cur_docs)
        if set(prev_by_id) != set(cur_by_id):
            raise ValueError("document identity population changed")

        changed_ids = sorted(
            aid for aid in prev_by_id if prev_by_id[aid] != cur_by_id[aid]
        )
        if changed_ids != list(TARGET_IDS):
            raise ValueError(
                f"document changes escaped exact target set expected={list(TARGET_IDS)} "
                f"actual={changed_ids}"
            )
        non_target_equal_count = sum(
            1
            for aid in prev_by_id
            if aid not in TARGET_SET and prev_by_id[aid] == cur_by_id[aid]
        )
        if non_target_equal_count != EXPECTED_DOCUMENT_ROWS - len(TARGET_IDS):
            raise ValueError(f"non-target document equality count drift {non_target_equal_count}")

        current_error_count = sum(row.get("document_status") == "ERROR" for row in cur_docs)
        taxonomy = tie_taxonomy(cur_docs)
        unresolved = sum(taxonomy.values())
        if current_error_count != EXPECTED_CURRENT_DOCUMENT_ERRORS:
            raise ValueError(f"document error count drift {current_error_count}")
        if taxonomy != {
            "TIE_SOURCE_INCOMPLETE": EXPECTED_CURRENT_SOURCE_INCOMPLETE,
            "TIE_VALUE_CONFLICT": EXPECTED_CURRENT_VALUE_CONFLICT,
        }:
            raise ValueError(f"tie taxonomy drift {taxonomy}")
        if unresolved != EXPECTED_CURRENT_UNRESOLVED_TIES:
            raise ValueError(f"unresolved tie count drift {unresolved}")

        assert_target_documents(cur_docs)
        assert_target_numeric(cur_values)

        current_target_values = [
            row for row in cur_values if row.get("announcement_id") in TARGET_SET
        ]
        if len(current_target_values) != EXPECTED_TARGET_NUMERIC_ROWS:
            raise ValueError(f"target numeric row count drift {len(current_target_values)}")
        previous_target_values = [
            row for row in prev_values if row.get("announcement_id") in TARGET_SET
        ]
        if previous_target_values:
            raise ValueError("previous V17.29 basis unexpectedly contains V17.30 target rows")

        excluded_method_fields = {"extraction_method", "methodology_version"}
        previous_stable_sha = stable_sha(
            prev_values, prev_value_fields, excluded_method_fields
        )
        current_existing = [
            row for row in cur_values if row.get("announcement_id") not in TARGET_SET
        ]
        current_existing_sha = stable_sha(
            current_existing, cur_value_fields, excluded_method_fields
        )
        if len(current_existing) != EXPECTED_PREVIOUS_NUMERIC_ROWS:
            raise ValueError(f"existing numeric row count drift {len(current_existing)}")
        if stable_counter(prev_values, prev_value_fields, excluded_method_fields) != stable_counter(
            current_existing, cur_value_fields, excluded_method_fields
        ):
            raise ValueError("existing 1,051,820 numeric observations changed")

        gold_target_docs = [row for row in gold_docs if row.get("announcement_id") in TARGET_SET]
        if len(gold_target_docs) != 2:
            raise ValueError(f"promotion gold target document count drift {len(gold_target_docs)}")
        gold_target_values = [
            row for row in gold_values if row.get("announcement_id") in TARGET_SET
        ]
        if len(gold_target_values) != EXPECTED_TARGET_NUMERIC_ROWS:
            raise ValueError(f"promotion gold target numeric count drift {len(gold_target_values)}")
        fresh_target_sha = stable_sha(
            current_target_values, cur_value_fields, excluded_method_fields
        )
        gold_target_sha = stable_sha(
            gold_target_values, gold_value_fields, excluded_method_fields
        )
        if stable_counter(
            current_target_values, cur_value_fields, excluded_method_fields
        ) != stable_counter(gold_target_values, gold_value_fields, excluded_method_fields):
            raise ValueError("fresh target numeric rows differ from accepted promotion-safety gold")

        report.update(
            {
                "changed_announcement_ids": changed_ids,
                "non_target_document_equal_count": non_target_equal_count,
                "previous_numeric_count": len(prev_values),
                "current_numeric_count": len(cur_values),
                "existing_numeric_row_count": len(current_existing),
                "existing_numeric_semantic_sha256_previous": previous_stable_sha,
                "existing_numeric_semantic_sha256_current": current_existing_sha,
                "fresh_target_numeric_semantic_sha256": fresh_target_sha,
                "promotion_gold_target_numeric_semantic_sha256": gold_target_sha,
                "target_numeric_rows": len(current_target_values),
                "current_document_errors": current_error_count,
                "current_unresolved_tie_taxonomy": taxonomy,
                "current_unresolved_ties": unresolved,
                "expected_values_are_now_machine_observed_only_if_this_report_passes": True,
                "final_data_verdict": "FAIL_CLOSED",
                "stage3_status": "NOT_READY",
                "stage4_alpha_locked": True,
                "pass": True,
                "errors": [],
            }
        )
    except Exception as exc:
        errors.append(str(exc))
        report.update(
            {
                "pass": False,
                "errors": errors,
                "final_data_verdict": "FAIL_CLOSED",
                "stage3_status": "NOT_READY",
                "stage4_alpha_locked": True,
            }
        )

    Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
