from __future__ import annotations

import unittest
from unittest.mock import patch

import stage3_financial_pdf_parser_v10 as parser


class V16ContextualParserTests(unittest.TestCase):
    def test_contextual_hook_is_restored_after_exception(self):
        original_hook = parser.v2._validated_balance_sheet
        seen = {}

        def fail_parse(raw: bytes):
            seen["hook_during_parse"] = parser.v2._validated_balance_sheet
            raise RuntimeError("synthetic parse failure")

        original_parse = parser.v13.parse_pdf_bytes
        parser.v13.parse_pdf_bytes = fail_parse
        try:
            with self.assertRaisesRegex(RuntimeError, "synthetic parse failure"):
                parser.parse_pdf_bytes(b"not-used", "2024-12-31")
        finally:
            parser.v13.parse_pdf_bytes = original_parse

        self.assertIsNot(seen["hook_during_parse"], original_hook)
        self.assertIs(parser.v2._validated_balance_sheet, original_hook)

    def test_mupdf_diagnostic_guard_restores_global_state_after_exception(self):
        original_get_text = parser.fitz.Page.get_text
        original_search_for = parser.fitz.Page.search_for
        prior_errors = parser.fitz.TOOLS.mupdf_display_errors()
        prior_warnings = parser.fitz.TOOLS.mupdf_display_warnings()

        with self.assertRaisesRegex(RuntimeError, "guard failure"):
            with parser._mupdf_diagnostic_guard():
                self.assertIsNot(parser.fitz.Page.get_text, original_get_text)
                self.assertIsNot(parser.fitz.Page.search_for, original_search_for)
                self.assertFalse(parser.fitz.TOOLS.mupdf_display_errors())
                self.assertFalse(parser.fitz.TOOLS.mupdf_display_warnings())
                raise RuntimeError("guard failure")

        self.assertIs(parser.fitz.Page.get_text, original_get_text)
        self.assertIs(parser.fitz.Page.search_for, original_search_for)
        self.assertEqual(parser.fitz.TOOLS.mupdf_display_errors(), prior_errors)
        self.assertEqual(parser.fitz.TOOLS.mupdf_display_warnings(), prior_warnings)

    def test_guarded_get_text_preserves_text_and_search_results(self):
        doc = parser.fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "人民币元")
        baseline_text = page.get_text("text")
        baseline_rects = page.search_for("人民币元")

        with parser._mupdf_diagnostic_guard():
            guarded_text = page.get_text("text")
            guarded_rects = page.search_for("人民币元")

        self.assertEqual(guarded_text, baseline_text)
        self.assertEqual(guarded_rects, baseline_rects)

    def test_v14_success_short_circuits_v16(self):
        sentinel_block = {"TOTAL_ASSETS": object()}
        sentinel_meta = {"arbitration": "V14_SENTINEL"}
        with patch.object(parser.v14, "_validated_balance_sheet_v14", return_value=(sentinel_block, sentinel_meta)):
            with patch.object(parser, "_v16_7_balance_block", side_effect=AssertionError("V16 must not run")):
                block, meta = parser._validated_balance_sheet_contextual(object(), "2024-12-31")
        self.assertIs(block, sentinel_block)
        self.assertIs(meta, sentinel_meta)

    def test_v16_block_preserves_observation_contract(self):
        selected = {
            "TOTAL_ASSETS": {
                "raw_value": "100", "value": "1000000", "unit": "万元", "page": 10,
                "alias": "资产总计", "statement_anchor_page": 8, "period_evidence": {"matched": True},
            },
            "TOTAL_LIABILITIES": {
                "raw_value": "60", "value": "600000", "unit": "万元", "page": 11,
                "alias": "负债合计", "statement_anchor_page": 8, "period_evidence": {"matched": True},
            },
            "TOTAL_EQUITY": {
                "raw_value": "40", "value": "400000", "unit": "万元", "page": 11,
                "alias": "所有者权益合计", "statement_anchor_page": 8, "period_evidence": {"matched": True},
            },
        }
        diagnostic = {
            "recovered": True,
            "selected": selected,
            "identity": {"identity_relative_error": "0", "identity_residual_cny": "0", "page_span": 1, "anchor_span": 0},
            "column_role_gate": {"pass": True, "concepts": {k: {"pass": True} for k in selected}},
        }
        with patch.object(parser, "diagnose_spatial_balance_sheet_v16_7", return_value=diagnostic):
            block, meta = parser._v16_7_balance_block(object(), "2024-12-31")
        self.assertEqual(block["TOTAL_ASSETS"].normalized_cny_value, "1000000")
        self.assertEqual(block["TOTAL_ASSETS"].unit_multiplier, "10000")
        self.assertEqual(block["TOTAL_EQUITY"].status, "FOUND")
        self.assertEqual(block["EQUITY_ATTRIBUTABLE_TO_PARENT"].status, "NOT_FOUND")
        self.assertTrue(meta["column_role_gate_pass"])
        self.assertEqual(meta["expected_economic_date"], "2024-12-31")
        self.assertEqual(meta["arbitration"], "V16_7_GROUP_PERIOD_FROZEN_DATE_COLUMN_A_EQUALS_L_PLUS_E")


if __name__ == "__main__":
    unittest.main()
