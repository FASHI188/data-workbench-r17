from __future__ import annotations

import csv
import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/compare_stage3_s3g1j_v17_30_full_final.py"

DOC_FIELDS = [
    "announcement_id", "source_code", "economic_date", "selected_source_sha256",
    "selected_source_bytes", "document_status", "tie_resolution", "tier2_found",
    "numeric_observations", "document_error",
]
VALUE_FIELDS = [
    "announcement_id", "source_code", "economic_date", "concept", "normalized_cny_value",
    "unit", "unit_multiplier", "source_sha256", "source_format", "extraction_method",
    "methodology_version", "page", "matched_alias", "confidence",
]

TARGETS = {
    "1223347318": {
        "source_code": "605289", "economic_date": "2025-03-31",
        "sha": "d765c94532cd41a496d147da72cbff392bce4ff776b41b88d95dcf3f1fb697c8",
        "bytes": "492929",
        "values": {
            "TOTAL_ASSETS": ("2250857154.79", "7", "资产总计"),
            "TOTAL_LIABILITIES": ("954370096.74", "8", "负债合计"),
            "TOTAL_EQUITY": ("1296487058.05", "8", "所有者权益（或股东权益）合计"),
        },
    },
    "1223407043": {
        "source_code": "605162", "economic_date": "2024-12-31",
        "sha": "7540a56179783625ac256726480ef32faf85a893549057fe9e6546abfd6ee903",
        "bytes": "1367714",
        "values": {
            "TOTAL_ASSETS": ("1885230514.78", "83", "资产总计"),
            "TOTAL_LIABILITIES": ("564752701.93", "84", "负债合计"),
            "TOTAL_EQUITY": ("1320477812.85", "84", "所有者权益（或股东权益）合计"),
        },
    },
}


def write_gz(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class V1730FullFinalComparatorTest(unittest.TestCase):
    def test_constants_lock_exact_targets_and_counts(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        for value in (
            "1223347318", "1223407043", "1051820", "1051826", "1362", "1279",
            "S3G1J_V17_30_FULL_BASIS_NON_REGRESSION_V1",
            "CNINFO_ORIGINAL_PDF_PYMUPDF_V20_V17_30_EXACT_SOURCE_CROSS_PAGE_GROUP_EQUITY_PRODUCTION",
            "V3.3.14-V17.30",
        ):
            self.assertIn(value, text)
        self.assertNotIn("OCR", text.upper().replace("NO OCR", ""))

    def test_target_fixture_values_are_exact(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cmp_v1730", SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(tuple(mod.TARGET_IDS), ("1223347318", "1223407043"))
        self.assertEqual(mod.EXPECTED_DOCUMENT_ROWS, 121354)
        self.assertEqual(mod.EXPECTED_PREVIOUS_NUMERIC_ROWS, 1051820)
        self.assertEqual(mod.EXPECTED_CURRENT_NUMERIC_ROWS, 1051826)
        self.assertEqual(mod.EXPECTED_CURRENT_DOCUMENT_ERRORS, 1362)
        self.assertEqual(mod.EXPECTED_CURRENT_UNRESOLVED_TIES, 1279)
        self.assertEqual(mod.TARGETS["1223347318"]["values"]["TOTAL_EQUITY"][0], "1296487058.05")
        self.assertEqual(mod.TARGETS["1223407043"]["values"]["TOTAL_EQUITY"][0], "1320477812.85")

    def test_wrong_target_value_fails_closed_before_acceptance(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cmp_v1730_mut", SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rows = []
        for aid, target in TARGETS.items():
            for concept, (value, page, alias) in target["values"].items():
                rows.append({
                    "announcement_id": aid,
                    "source_code": target["source_code"],
                    "economic_date": target["economic_date"],
                    "concept": concept,
                    "normalized_cny_value": value,
                    "unit": "元",
                    "unit_multiplier": "1",
                    "source_sha256": target["sha"],
                    "source_format": "PDF",
                    "extraction_method": mod.EXPECTED_METHOD,
                    "methodology_version": mod.EXPECTED_METHODOLOGY,
                    "page": page,
                    "matched_alias": alias,
                    "confidence": "HIGH",
                })
        mod.assert_target_numeric(rows)
        rows[0] = dict(rows[0])
        rows[0]["normalized_cny_value"] = "1.00"
        with self.assertRaisesRegex(ValueError, "value drift"):
            mod.assert_target_numeric(rows)

    def test_document_target_requires_exact_source_identity(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cmp_v1730_docs", SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rows=[]
        for aid,target in TARGETS.items():
            rows.append({
                "announcement_id":aid,
                "source_code":target["source_code"],
                "economic_date":target["economic_date"],
                "selected_source_sha256":target["sha"],
                "selected_source_bytes":target["bytes"],
                "document_status":"PASS",
                "tie_resolution":"SINGLE_CANONICAL",
                "tier2_found":"3",
                "numeric_observations":"3",
                "document_error":"",
            })
        mod.assert_target_documents(rows)
        rows[0]=dict(rows[0])
        rows[0]["selected_source_bytes"]="1"
        with self.assertRaisesRegex(ValueError,"source bytes drift"):
            mod.assert_target_documents(rows)


if __name__ == "__main__":
    unittest.main()
