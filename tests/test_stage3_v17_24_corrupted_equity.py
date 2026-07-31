from __future__ import annotations

import unittest
from unittest.mock import patch

import stage3_financial_pdf_parser_v14 as parser
import stage3_financial_spatial_alias_v17_24 as spatial


class V1724CorruptedEquityTests(unittest.TestCase):
    def test_exact_corrupted_alias_only(self):
        self.assertTrue(
            spatial._is_exact_corrupted_equity_row(
                "所有者权益（或d 股东权益）合计 1,260,141,935.13 1,257,210,563.29"
            )
        )
        self.assertFalse(
            spatial._is_exact_corrupted_equity_row(
                "所有者权益（或股东权益）合计 1,260,141,935.13"
            )
        )
        self.assertFalse(
            spatial._is_exact_corrupted_equity_row(
                "负债和所有者权益（或d 股东权益）合计 3,642,768,851.01"
            )
        )
        self.assertFalse(
            spatial._is_exact_corrupted_equity_row(
                "所有者权益（或x 股东权益）合计 1,260,141,935.13"
            )
        )

    def test_v17_21_and_earlier_paths_have_absolute_priority(self):
        sentinel_block = {"sentinel": object()}
        sentinel_meta = {"source": "V17_21"}
        with patch.object(
            parser.v13,
            "_validated_balance_sheet_contextual",
            return_value=(sentinel_block, sentinel_meta),
        ), patch.object(parser, "_v17_24_balance_block") as candidate:
            block, meta = parser._validated_balance_sheet_contextual(
                object(), "2024-09-30"
            )
        self.assertIs(block, sentinel_block)
        self.assertIs(meta, sentinel_meta)
        candidate.assert_not_called()

    def test_candidate_block_requires_exact_flag_alias_and_two_columns(self):
        selected = {
            "TOTAL_ASSETS": {
                "value": "3642768851.01",
                "raw_value": "3642768851.01",
                "unit": "元",
                "page": 7,
                "alias": "资产总计",
                "statement_anchor_page": 5,
                "period_evidence": {"matched": True},
            },
            "TOTAL_LIABILITIES": {
                "value": "2382626915.88",
                "raw_value": "2382626915.88",
                "unit": "元",
                "page": 8,
                "alias": "负债合计",
                "statement_anchor_page": 5,
                "period_evidence": {"matched": True},
            },
            "TOTAL_EQUITY": {
                "value": "1260141935.13",
                "raw_value": "1260141935.13",
                "unit": "元",
                "page": 8,
                "alias": spatial.CORRUPTED_EQUITY_ALIAS,
                "statement_anchor_page": 5,
                "period_evidence": {"matched": True},
                "row_text": (
                    "所有者权益（或d 股东权益）合计 "
                    "1,260,141,935.13 1,257,210,563.29"
                ),
                "strict_corrupted_equity_alias_v17_24": True,
                "corrupted_equity_alias_normalized": (
                    spatial.CORRUPTED_EQUITY_ALIAS
                ),
                "corrupted_equity_amount_columns": [
                    {"raw": "1260141935.13", "value": "1260141935.13", "x0": "1"},
                    {"raw": "1257210563.29", "value": "1257210563.29", "x0": "2"},
                ],
            },
        }
        diagnostic = {
            "recovered": True,
            "selected": selected,
            "identity": {
                "identity_relative_error": "0",
                "identity_residual_cny": "0.00",
                "page_span": 1,
                "anchor_span": 0,
            },
            "column_role_gate": {
                "pass": True,
                "concepts": {
                    concept: {"pass": True} for concept in parser.CONCEPTS
                },
            },
        }
        with patch.object(
            parser,
            "diagnose_spatial_balance_sheet_v17_24",
            return_value=diagnostic,
        ):
            block, meta = parser._v17_24_balance_block(
                object(), "2024-09-30"
            )
        self.assertEqual(
            block["TOTAL_EQUITY"].normalized_cny_value,
            "1260141935.13",
        )
        self.assertEqual(
            meta["corrupted_equity_selected_concepts"],
            ["TOTAL_EQUITY"],
        )
        self.assertEqual(meta["identity_tolerance"], "0.005")
        self.assertFalse(meta["e_equals_a_minus_l_inference"])
        self.assertTrue(meta["candidate_only"])


if __name__ == "__main__":
    unittest.main()
