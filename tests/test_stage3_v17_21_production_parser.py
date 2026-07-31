from __future__ import annotations

import unittest
from unittest.mock import patch

import stage3_financial_pdf_parser_v13 as parser


def candidate(concept: str, raw: str, value: str, page: int, *, reverse: bool = False):
    row = {
        "concept": concept,
        "value": value,
        "raw_value": raw,
        "unit": "元",
        "page": page,
        "alias": {
            "TOTAL_ASSETS": "资产总计",
            "TOTAL_LIABILITIES": "负债合计",
            "TOTAL_EQUITY": "所有者权益（或股东权益）合计",
        }[concept],
        "statement_anchor_page": 82,
        "period_evidence": {"matched": True},
    }
    if reverse:
        row.update(
            {
                "adjacent_row_bridge": True,
                "reverse_adjacent_asset_total": True,
                "reverse_bridge_y_delta": "5.87994384765625",
                "reverse_bridge_numeric_row_text": "73,523,417,381.93 64,723,678,252.66",
                "bridge_amount_columns": [
                    {"raw": "73523417381.93", "value": "73523417381.93", "x0": "294.41"},
                    {"raw": "64723678252.66", "value": "64723678252.66", "x0": "418.63"},
                ],
            }
        )
    return row


def valid_diagnostic():
    selected = {
        "TOTAL_ASSETS": candidate("TOTAL_ASSETS", "73523417381.93", "73523417381.93", 83, reverse=True),
        "TOTAL_LIABILITIES": candidate("TOTAL_LIABILITIES", "35828459679.63", "35828459679.63", 83),
        "TOTAL_EQUITY": candidate("TOTAL_EQUITY", "37694957702.30", "37694957702.30", 83),
    }
    return {
        "recovered": True,
        "selected": selected,
        "identity": {
            "identity_relative_error": "0",
            "identity_residual_cny": "0.00",
            "page_span": 0,
            "anchor_span": 0,
        },
        "column_role_gate": {
            "pass": True,
            "concepts": {
                concept: {"pass": True, "evidence_source": "V17_11_TRUSTED_FROZEN_DATE_HEADER"}
                for concept in selected
            },
        },
    }


class V1721ProductionParserTests(unittest.TestCase):
    def test_v17_17_and_earlier_paths_have_absolute_priority(self):
        sentinel_block = {"sentinel": object()}
        sentinel_meta = {"source": "V17_17"}
        with patch.object(
            parser.v12,
            "_validated_balance_sheet_contextual",
            return_value=(sentinel_block, sentinel_meta),
        ), patch.object(parser, "diagnose_spatial_balance_sheet_v17_21") as fallback:
            block, meta = parser._validated_balance_sheet_contextual(object(), "2023-12-31")
        self.assertIs(block, sentinel_block)
        self.assertIs(meta, sentinel_meta)
        fallback.assert_not_called()

    def test_exact_reverse_asset_total_maps_to_validated_block(self):
        with patch.object(
            parser, "diagnose_spatial_balance_sheet_v17_21", return_value=valid_diagnostic()
        ):
            block, meta = parser._v17_21_balance_block(object(), "2023-12-31")

        self.assertEqual(block["TOTAL_ASSETS"].normalized_cny_value, "73523417381.93")
        self.assertEqual(block["TOTAL_LIABILITIES"].normalized_cny_value, "35828459679.63")
        self.assertEqual(block["TOTAL_EQUITY"].normalized_cny_value, "37694957702.30")
        self.assertEqual(block["TOTAL_ASSETS"].matched_alias, "资产总计")
        self.assertEqual(
            block["TOTAL_ASSETS"].extraction_scope,
            "VALIDATED_BALANCE_SHEET_BLOCK_V17_21_EXACT_REVERSE_ADJACENT_ASSET_TOTAL",
        )
        self.assertEqual(
            meta["arbitration"],
            "V17_21_GROUP_PERIOD_FROZEN_DATE_A_EQUALS_L_PLUS_E_EXACT_REVERSE_ASSET_TOTAL",
        )
        self.assertEqual(meta["identity_tolerance"], "0.005")
        self.assertEqual(meta["identity_residual_cny"], "0.00")
        self.assertEqual(meta["reverse_asset_total_selected_concepts"], ["TOTAL_ASSETS"])
        self.assertEqual(meta["reverse_asset_total_alias"], "资产总计")
        self.assertEqual(meta["reverse_asset_total_amount_column_count"], 2)
        self.assertFalse(meta["e_equals_a_minus_l_inference"])
        self.assertFalse(meta["global_row_tolerance_changed"])

    def test_wrong_asset_alias_remains_fail_closed(self):
        diagnostic = valid_diagnostic()
        diagnostic["selected"]["TOTAL_ASSETS"]["alias"] = "流动资产合计"
        with patch.object(
            parser, "diagnose_spatial_balance_sheet_v17_21", return_value=diagnostic
        ):
            block, meta = parser._v17_21_balance_block(object(), "2023-12-31")
        self.assertIsNone(block)
        self.assertIsNone(meta)

    def test_reverse_distance_outside_frozen_window_remains_fail_closed(self):
        diagnostic = valid_diagnostic()
        diagnostic["selected"]["TOTAL_ASSETS"]["reverse_bridge_y_delta"] = "6.26"
        with patch.object(
            parser, "diagnose_spatial_balance_sheet_v17_21", return_value=diagnostic
        ):
            block, meta = parser._v17_21_balance_block(object(), "2023-12-31")
        self.assertIsNone(block)
        self.assertIsNone(meta)

    def test_identity_outside_tolerance_remains_fail_closed(self):
        diagnostic = valid_diagnostic()
        diagnostic["identity"]["identity_relative_error"] = "0.0051"
        with patch.object(
            parser, "diagnose_spatial_balance_sheet_v17_21", return_value=diagnostic
        ):
            block, meta = parser._v17_21_balance_block(object(), "2023-12-31")
        self.assertIsNone(block)
        self.assertIsNone(meta)

    def test_incomplete_column_evidence_remains_fail_closed(self):
        diagnostic = valid_diagnostic()
        diagnostic["column_role_gate"]["concepts"]["TOTAL_EQUITY"]["pass"] = False
        with patch.object(
            parser, "diagnose_spatial_balance_sheet_v17_21", return_value=diagnostic
        ):
            block, meta = parser._v17_21_balance_block(object(), "2023-12-31")
        self.assertIsNone(block)
        self.assertIsNone(meta)


if __name__ == "__main__":
    unittest.main()
