from __future__ import annotations

from decimal import Decimal
import unittest
from unittest.mock import patch

import stage3_financial_pdf_parser_v11 as parser


def candidate(concept: str, raw: str, value: str, *, bridged: bool = False):
    return {
        "concept": concept,
        "value": Decimal(value),
        "raw_value": raw,
        "unit": "元",
        "page": 10,
        "alias": {
            "TOTAL_ASSETS": "资产总计",
            "TOTAL_LIABILITIES": "负债合计",
            "TOTAL_EQUITY": "股东权益合计",
        }[concept],
        "statement_anchor_page": 10,
        "period_evidence": {"matched": True},
        "adjacent_row_bridge": bridged,
    }


class V1715ProductionParserTests(unittest.TestCase):
    def test_prior_contextual_parser_has_absolute_priority(self):
        sentinel_block = {"sentinel": object()}
        sentinel_meta = {"source": "V16_7"}
        with patch.object(
            parser.v10,
            "_validated_balance_sheet_contextual",
            return_value=(sentinel_block, sentinel_meta),
        ), patch.object(parser, "diagnose_spatial_balance_sheet_v17_15") as fallback:
            block, meta = parser._validated_balance_sheet_contextual(object(), "2025-12-31")
        self.assertIs(block, sentinel_block)
        self.assertIs(meta, sentinel_meta)
        fallback.assert_not_called()

    def test_strict_adjacent_fallback_maps_validated_identity_to_observations(self):
        selected = {
            "TOTAL_ASSETS": candidate("TOTAL_ASSETS", "1000", "1000", bridged=False),
            "TOTAL_LIABILITIES": candidate("TOTAL_LIABILITIES", "600", "600", bridged=False),
            "TOTAL_EQUITY": candidate("TOTAL_EQUITY", "400", "400", bridged=True),
        }
        diagnostic = {
            "recovered": True,
            "selected": selected,
            "identity": {
                "identity_relative_error": "0",
                "identity_residual_cny": "0",
                "page_span": 0,
                "anchor_span": 0,
            },
            "column_role_gate": {"pass": True, "concepts": {"TOTAL_EQUITY": {"pass": True}}},
        }
        with patch.object(parser, "diagnose_spatial_balance_sheet_v17_15", return_value=diagnostic):
            block, meta = parser._v17_15_balance_block(object(), "2025-12-31")

        self.assertEqual(block["TOTAL_ASSETS"].normalized_cny_value, "1000")
        self.assertEqual(block["TOTAL_LIABILITIES"].normalized_cny_value, "600")
        self.assertEqual(block["TOTAL_EQUITY"].normalized_cny_value, "400")
        self.assertEqual(
            block["TOTAL_EQUITY"].extraction_scope,
            "VALIDATED_BALANCE_SHEET_BLOCK_V17_15_STRICT_ADJACENT_ROW_COLUMN_GATE",
        )
        self.assertEqual(meta["identity_tolerance"], "0.005")
        self.assertEqual(meta["identity_relative_error"], "0")
        self.assertEqual(meta["adjacent_row_bridge_selected_concepts"], ["TOTAL_EQUITY"])
        self.assertFalse(meta["global_row_tolerance_changed"])

    def test_recovery_without_actual_bridge_is_rejected(self):
        selected = {
            "TOTAL_ASSETS": candidate("TOTAL_ASSETS", "1000", "1000"),
            "TOTAL_LIABILITIES": candidate("TOTAL_LIABILITIES", "600", "600"),
            "TOTAL_EQUITY": candidate("TOTAL_EQUITY", "400", "400"),
        }
        diagnostic = {
            "recovered": True,
            "selected": selected,
            "identity": {"identity_relative_error": "0", "identity_residual_cny": "0"},
            "column_role_gate": {"pass": True, "concepts": {}},
        }
        with patch.object(parser, "diagnose_spatial_balance_sheet_v17_15", return_value=diagnostic):
            block, meta = parser._v17_15_balance_block(object(), "2025-12-31")
        self.assertIsNone(block)
        self.assertIsNone(meta)

    def test_failed_candidate_remains_fail_closed(self):
        with patch.object(
            parser,
            "diagnose_spatial_balance_sheet_v17_15",
            return_value={"recovered": False},
        ):
            block, meta = parser._v17_15_balance_block(object(), "2025-12-31")
        self.assertIsNone(block)
        self.assertIsNone(meta)


if __name__ == "__main__":
    unittest.main()
