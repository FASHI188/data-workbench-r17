from __future__ import annotations

import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
