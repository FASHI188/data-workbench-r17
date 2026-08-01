from __future__ import annotations

import csv
import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import compare_stage3_s3g1j_v17_25_full_values as mod


def base_row(aid: str, concept: str, value: str, sha: str = "base-sha") -> dict[str, str]:
    row = {field: "x" for field in mod.STABLE_FIELDS}
    row.update(
        {
            "announcement_id": aid,
            "concept": concept,
            "raw_value": value,
            "normalized_cny_value": value,
            "source_sha256": sha,
        }
    )
    return row


def write_gz(path: Path, rows: list[dict[str, str]]) -> None:
    fields = list(mod.STABLE_FIELDS) + ["extraction_method", "methodology_version"]
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            out = {field: row.get(field, "") for field in fields}
            writer.writerow(out)


def target_rows(aid: str) -> list[dict[str, str]]:
    expected = mod.TARGETS[aid]
    return [
        base_row(aid, concept, value, expected["source_sha256"])
        for concept, value in expected["required_concepts"].items()
    ]


class FullValuesNonRegressionTests(unittest.TestCase):
    def run_compare(self, previous_rows, current_rows):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path(tmp) / "previous.csv.gz"
            current = Path(tmp) / "current.csv.gz"
            write_gz(previous, previous_rows)
            write_gz(current, current_rows)
            previous_scan = mod.scan(previous)
            with patch.object(
                mod, "EXPECTED_PREVIOUS_NON_TARGET_ROWS", previous_scan["non_target_row_count"]
            ), patch.object(
                mod,
                "EXPECTED_PREVIOUS_NON_TARGET_SHA256",
                previous_scan["non_target_semantic_sha256"],
            ):
                return mod.compare(previous, current)

    def test_exact_non_target_and_two_recoveries_pass(self):
        base = [base_row("1", "REVENUE", "10"), base_row("2", "NET_PROFIT", "3")]
        current = base + target_rows("1207035181") + target_rows("1221568845")
        report = self.run_compare(base, current)
        self.assertTrue(report["pass"], report["errors"])

    def test_non_target_value_drift_fails(self):
        previous = [base_row("1", "REVENUE", "10")]
        current = [base_row("1", "REVENUE", "11")] + target_rows("1207035181") + target_rows("1221568845")
        report = self.run_compare(previous, current)
        self.assertFalse(report["pass"])
        self.assertTrue(any("semantic SHA drift" in e for e in report["errors"]))

    def test_non_target_row_order_drift_fails_deterministic_contract(self):
        previous = [base_row("1", "REVENUE", "10"), base_row("2", "NET_PROFIT", "3")]
        current = list(reversed(previous)) + target_rows("1207035181") + target_rows("1221568845")
        report = self.run_compare(previous, current)
        self.assertFalse(report["pass"])
        self.assertTrue(any("semantic SHA drift" in e for e in report["errors"]))

    def test_wrong_target_value_fails(self):
        previous = [base_row("1", "REVENUE", "10")]
        current = previous + target_rows("1207035181") + target_rows("1221568845")
        for row in current:
            if row["announcement_id"] == "1207035181" and row["concept"] == "TOTAL_EQUITY":
                row["normalized_cny_value"] = "0"
        report = self.run_compare(previous, current)
        self.assertFalse(report["pass"])
        self.assertTrue(any("TOTAL_EQUITY" in e for e in report["errors"]))

    def test_wrong_target_source_sha_fails(self):
        previous = [base_row("1", "REVENUE", "10")]
        current = previous + target_rows("1207035181") + target_rows("1221568845")
        for row in current:
            if row["announcement_id"] == "1221568845":
                row["source_sha256"] = "wrong"
        report = self.run_compare(previous, current)
        self.assertFalse(report["pass"])
        self.assertTrue(any("source SHA mismatch" in e for e in report["errors"]))


if __name__ == "__main__":
    unittest.main()
