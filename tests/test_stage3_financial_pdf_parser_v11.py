import unittest
from decimal import Decimal

import scripts.stage3_financial_pdf_parser_v6 as v11


class FinancialPdfParserV11Tests(unittest.TestCase):
    def test_chinese_unit_variants(self):
        self.assertEqual(v11.detect_unit("金额单位为人民币元"), ("元", Decimal("1")))
        self.assertEqual(v11.detect_unit("单位：人民币千元"), ("千元", Decimal("1000")))
        self.assertEqual(
            v11.detect_unit("货币单位均以人民币百万元列示"),
            ("百万元", Decimal("1000000")),
        )

    def test_english_unit_variants(self):
        self.assertEqual(v11.detect_unit("Unit: RMB"), ("RMB", Decimal("1")))
        self.assertEqual(v11.detect_unit("Unit: RMB million"), ("RMB million", Decimal("1000000")))

    def test_verified_chinese_statement_titles(self):
        self.assertEqual(v11._balance_title_kind("2014 年12 月31 日合并及公司资产负债表"), "CONSOLIDATED")
        self.assertEqual(v11._balance_title_kind("合并及银行资产负债表"), "CONSOLIDATED")
        self.assertEqual(v11._balance_title_kind("未经审计合并资产负债表"), "CONSOLIDATED")

    def test_english_statement_titles(self):
        self.assertEqual(v11._balance_title_kind("Consolidated Balance Sheet"), "CONSOLIDATED")
        self.assertEqual(v11._balance_title_kind("Balance Sheet of Parent Company"), "PARENT_ONLY")

    def test_narrative_title_mentions_stay_rejected(self):
        self.assertIsNone(v11._balance_title_kind("本年度合并及公司资产负债表相关项目发生变化"))
        self.assertIsNone(v11._balance_title_kind("Consolidated Balance Sheet and related notes"))

    def test_total_assets_alias_includes_asset_total(self):
        self.assertIn("资产合计", v11.base.TIER1_ALIASES["TOTAL_ASSETS"])

    def test_english_gross_rows_do_not_masquerade_as_operating_line_items(self):
        self.assertFalse(
            v11.semantic_row_match("1. Gross operating income 100 90", "Operating income", "OPERATING_REVENUE")
        )
        self.assertFalse(
            v11.semantic_row_match("2. Gross operating cost 80 70", "Operating cost", "OPERATING_COST")
        )
        self.assertTrue(
            v11.semantic_row_match("Incl.: Operating income 100 90", "Operating income", "OPERATING_REVENUE")
        )
        self.assertTrue(
            v11.semantic_row_match("Incl.: Operating cost 80 70", "Operating cost", "OPERATING_COST")
        )

    def test_parent_attributable_equity_is_not_total_equity(self):
        self.assertTrue(
            v11._is_parent_equity_alias_hit(
                "Subtotal of owner's equity attributable to parent company 100 90",
                "Total of owner's equity",
                "TOTAL_EQUITY",
            )
        )


if __name__ == "__main__":
    unittest.main()
