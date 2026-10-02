import unittest

from scripts.stage3_financial_pdf_parser_v4 import _is_parent_equity_alias_hit


class BalanceBlockV6Tests(unittest.TestCase):
    def test_parent_equity_row_cannot_satisfy_total_equity(self):
        self.assertTrue(
            _is_parent_equity_alias_hit(
                "归属于母公司所有者权益合计 102397165148 95000000000",
                "所有者权益合计",
                "TOTAL_EQUITY",
            )
        )

    def test_parent_equity_remains_allowed_for_parent_equity_concept(self):
        self.assertFalse(
            _is_parent_equity_alias_hit(
                "归属于母公司所有者权益合计 102397165148 95000000000",
                "归属于母公司所有者权益合计",
                "EQUITY_ATTRIBUTABLE_TO_PARENT",
            )
        )

    def test_true_total_equity_row_is_not_rejected(self):
        self.assertFalse(
            _is_parent_equity_alias_hit(
                "所有者权益合计 119795849333 108000000000",
                "所有者权益合计",
                "TOTAL_EQUITY",
            )
        )

    def test_preceding_unrelated_text_does_not_trigger_parent_guard(self):
        self.assertFalse(
            _is_parent_equity_alias_hit(
                "少数股东权益 17398684185 所有者权益合计 119795849333",
                "所有者权益合计",
                "TOTAL_EQUITY",
            )
        )


if __name__ == "__main__":
    unittest.main()
