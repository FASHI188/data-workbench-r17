from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import extract_stage3_financial_pdf_values_v12 as extractor
import stage3_financial_pdf_parser_v12 as parser


HEADER_SOURCE = "V17_17_STRICT_THREE_COLUMN_TWO_ROW_YEAR_MONTH_DAY_HEADER"


def selected_candidate(concept: str, raw: str, value: str, page: int, *, bridged: bool = False, strict: bool = False):
    return {
        "value": value,
        "raw_value": raw,
        "unit": "元",
        "page": page,
        "alias": {
            "TOTAL_ASSETS": "资产总计",
            "TOTAL_LIABILITIES": "负债合计",
            "TOTAL_EQUITY": "股东权益总计",
        }[concept],
        "statement_anchor_page": 97,
        "period_evidence": {"matched": True},
        "adjacent_row_bridge": bridged,
        "strict_same_row_equity_total": strict,
    }


def column_evidence(raw: str, *, source: str = HEADER_SOURCE):
    return {
        "pass": True,
        "evidence_source": source,
        "header": {
            "structural_source": source,
            "expected_date": "2021-12-31",
            "expected_column_index": 0,
            "dates": [
                {"date": "2021-12-31"},
                {"date": "2021-01-01"},
                {"date": "2020-12-31"},
            ],
        },
        "selected_raw_value": raw,
    }


class V1717ProductionParserTests(unittest.TestCase):
    def test_v17_15_and_earlier_paths_have_absolute_priority(self):
        sentinel_block = {"sentinel": object()}
        sentinel_meta = {"source": "V17_15"}
        with patch.object(
            parser.v11,
            "_validated_balance_sheet_contextual",
            return_value=(sentinel_block, sentinel_meta),
        ), patch.object(parser, "diagnose_spatial_balance_sheet_v17_17") as fallback:
            block, meta = parser._validated_balance_sheet_contextual(object(), "2021-12-31")
        self.assertIs(block, sentinel_block)
        self.assertIs(meta, sentinel_meta)
        fallback.assert_not_called()

    def test_strict_explicit_equity_and_paired_header_maps_to_observations(self):
        selected = {
            "TOTAL_ASSETS": selected_candidate("TOTAL_ASSETS", "20214466018.97", "20214466018.97", 97, bridged=True),
            "TOTAL_LIABILITIES": selected_candidate("TOTAL_LIABILITIES", "13296884507.65", "13296884507.65", 98, bridged=True),
            "TOTAL_EQUITY": selected_candidate("TOTAL_EQUITY", "6917581511.32", "6917581511.32", 99, strict=True),
        }
        diagnostic = {
            "recovered": True,
            "selected": selected,
            "identity": {
                "identity_relative_error": "0",
                "identity_residual_cny": "0.00",
                "page_span": 2,
                "anchor_span": 0,
            },
            "column_role_gate": {
                "pass": True,
                "concepts": {
                    "TOTAL_ASSETS": column_evidence("20214466018.97"),
                    "TOTAL_LIABILITIES": column_evidence("13296884507.65"),
                    "TOTAL_EQUITY": column_evidence("6917581511.32"),
                },
            },
        }
        with patch.object(parser, "diagnose_spatial_balance_sheet_v17_17", return_value=diagnostic):
            block, meta = parser._v17_17_balance_block(object(), "2021-12-31")

        self.assertEqual(block["TOTAL_ASSETS"].normalized_cny_value, "20214466018.97")
        self.assertEqual(block["TOTAL_LIABILITIES"].normalized_cny_value, "13296884507.65")
        self.assertEqual(block["TOTAL_EQUITY"].normalized_cny_value, "6917581511.32")
        self.assertEqual(block["TOTAL_EQUITY"].matched_alias, "股东权益总计")
        self.assertEqual(meta["identity_tolerance"], "0.005")
        self.assertEqual(meta["identity_residual_cny"], "0.00")
        self.assertEqual(meta["adjacent_row_bridge_selected_concepts"], ["TOTAL_ASSETS", "TOTAL_LIABILITIES"])
        self.assertEqual(meta["strict_total_equity_selected_concepts"], ["TOTAL_EQUITY"])
        self.assertEqual(meta["paired_header_evidence_source"], HEADER_SOURCE)
        self.assertFalse(meta["e_equals_a_minus_l_inference"])
        self.assertFalse(meta["global_row_tolerance_changed"])

    def test_wrong_header_source_remains_fail_closed(self):
        selected = {
            "TOTAL_ASSETS": selected_candidate("TOTAL_ASSETS", "1000", "1000", 97, bridged=True),
            "TOTAL_LIABILITIES": selected_candidate("TOTAL_LIABILITIES", "600", "600", 98, bridged=True),
            "TOTAL_EQUITY": selected_candidate("TOTAL_EQUITY", "400", "400", 99, strict=True),
        }
        diagnostic = {
            "recovered": True,
            "selected": selected,
            "identity": {"identity_relative_error": "0", "identity_residual_cny": "0"},
            "column_role_gate": {
                "pass": True,
                "concepts": {
                    "TOTAL_ASSETS": column_evidence("1000", source="OTHER"),
                    "TOTAL_LIABILITIES": column_evidence("600"),
                    "TOTAL_EQUITY": column_evidence("400"),
                },
            },
        }
        with patch.object(parser, "diagnose_spatial_balance_sheet_v17_17", return_value=diagnostic):
            block, meta = parser._v17_17_balance_block(object(), "2021-12-31")
        self.assertIsNone(block)
        self.assertIsNone(meta)

    def test_missing_explicit_total_equity_remains_fail_closed(self):
        selected = {
            "TOTAL_ASSETS": selected_candidate("TOTAL_ASSETS", "1000", "1000", 97, bridged=True),
            "TOTAL_LIABILITIES": selected_candidate("TOTAL_LIABILITIES", "600", "600", 98, bridged=True),
            "TOTAL_EQUITY": selected_candidate("TOTAL_EQUITY", "400", "400", 99, strict=False),
        }
        diagnostic = {
            "recovered": True,
            "selected": selected,
            "identity": {"identity_relative_error": "0", "identity_residual_cny": "0"},
            "column_role_gate": {
                "pass": True,
                "concepts": {concept: column_evidence(selected[concept]["raw_value"]) for concept in selected},
            },
        }
        with patch.object(parser, "diagnose_spatial_balance_sheet_v17_17", return_value=diagnostic):
            block, meta = parser._v17_17_balance_block(object(), "2021-12-31")
        self.assertIsNone(block)
        self.assertIsNone(meta)

    def test_formal_shard_output_contract_is_complete_and_hashed(self):
        version = {
            "exchange": "SSE",
            "source_code": "601330",
            "effective_code": "601330",
            "org_id": "gssh0601330",
            "report_family": "ANNUAL",
            "economic_date": "2021-12-31",
            "canonical_announcement_id": "1212731093",
            "revision_sequence": "1",
            "source_published_at": "2022-04-29",
            "effective_session": "2022-05-05",
            "available_at": "2022-05-05",
            "canonical_title": "绿色动力2021年年度报告",
            "canonical_source_url": "https://example.invalid/1212731093.pdf",
            "same_day_tied_top_ids": "[]",
            "same_day_tied_top_titles": "[]",
            "same_day_tied_top_urls": "[]",
        }
        parsed = {
            "observations": {
                "TOTAL_ASSETS": {
                    "status": "FOUND",
                    "raw_value": "20214466018.97",
                    "normalized_cny_value": "20214466018.97",
                    "unit": "元",
                    "unit_multiplier": "1",
                    "page": 97,
                    "matched_alias": "资产总计",
                    "confidence": "HIGH",
                }
            },
            "tier1_found": 1,
            "tier2_found": 0,
            "page_count": 120,
            "parser_version": parser.METHOD,
            "validation_errors": [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            argv = [
                "extract",
                "--versions",
                str(Path(tmp) / "versions.csv.gz"),
                "--shard",
                "0",
                "--shards",
                "64",
                "--out",
                str(out),
            ]
            with patch.object(sys, "argv", argv), patch.object(
                extractor.base, "read_versions", return_value=[version]
            ), patch.object(
                extractor.base, "stable_shard", return_value=0
            ), patch.object(
                extractor.base, "get_pdf", return_value=b"%PDF-1.7 synthetic"
            ), patch.object(
                extractor, "parse_pdf_bytes", return_value=parsed
            ):
                code = extractor.main()

            self.assertEqual(code, 0)
            numeric_path = out / "financial_values_shard00.csv.gz"
            documents_path = out / "financial_documents_shard00.csv.gz"
            manifest_path = out / "financial_extract_shard00.manifest.json"
            self.assertTrue(numeric_path.is_file())
            self.assertTrue(documents_path.is_file())
            self.assertTrue(manifest_path.is_file())

            with gzip.open(numeric_path, "rt", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_format"], "PDF")
            self.assertEqual(rows[0]["extraction_method"], extractor.METHOD)
            self.assertEqual(rows[0]["methodology_version"], extractor.METHODOLOGY_VERSION)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["pass"])
            self.assertEqual(manifest["error_count"], 0)
            self.assertEqual(manifest["selected_versions"], 1)
            self.assertEqual(manifest["document_rows"], 1)
            self.assertEqual(manifest["numeric_rows"], 1)
            self.assertEqual(manifest["gzip_header_mtime"], 0)
            self.assertEqual(manifest["gzip_embedded_filename"], "")
            self.assertEqual(
                manifest["numeric_sha256"], hashlib.sha256(numeric_path.read_bytes()).hexdigest()
            )
            self.assertEqual(
                manifest["documents_sha256"], hashlib.sha256(documents_path.read_bytes()).hexdigest()
            )


if __name__ == "__main__":
    unittest.main()
