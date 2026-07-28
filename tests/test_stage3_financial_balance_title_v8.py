import unittest

from scripts.stage3_financial_pdf_parser_v5 import _balance_title_kind


class BalanceTitleV8Tests(unittest.TestCase):
    def test_late_quarterly_consolidated_title(self):
        self.assertEqual(_balance_title_kind("1、合并资产负债表"), "CONSOLIDATED")

    def test_combined_group_parent_title(self):
        self.assertEqual(
            _balance_title_kind("2024 年6 月30 日合并及母公司资产负债表"),
            "CONSOLIDATED",
        )

    def test_issuer_prefixed_combined_title(self):
        self.assertEqual(
            _balance_title_kind("国海证券股份有限公司合并及母公司资产负债表（未经审计）"),
            "CONSOLIDATED",
        )

    def test_parent_only_title_is_not_consolidated(self):
        self.assertEqual(_balance_title_kind("母公司资产负债表"), "PARENT_ONLY")

    def test_generic_statement_title_is_allowed(self):
        self.assertEqual(_balance_title_kind("资产负债表"), "GENERIC")

    def test_narrative_analysis_heading_is_rejected(self):
        self.assertIsNone(_balance_title_kind("资产负债表项目分析"))

    def test_post_balance_sheet_note_is_rejected(self):
        self.assertIsNone(_balance_title_kind("资产负债表日后事项"))


if __name__ == "__main__":
    unittest.main()
