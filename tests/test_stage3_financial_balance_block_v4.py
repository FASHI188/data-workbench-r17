import unittest

from scripts.stage3_financial_pdf_parser_v2 import _numeric_tokens_after_alias_preserve_columns


class BalanceBlockNumericTests(unittest.TestCase):
    def test_two_year_integer_columns_never_concatenate(self):
        vals = _numeric_tokens_after_alias_preserve_columns(
            "资产总计 7540118905 5885118039",
            "资产总计",
        )
        self.assertGreaterEqual(len(vals), 2)
        self.assertEqual(str(vals[0][1]), "7540118905")
        self.assertEqual(str(vals[1][1]), "5885118039")

    def test_note_index_is_dropped_before_current_value(self):
        vals = _numeric_tokens_after_alias_preserve_columns(
            "负债合计 18 52799998.86 48000000.00",
            "负债合计",
        )
        self.assertGreaterEqual(len(vals), 2)
        self.assertEqual(str(vals[0][1]), "52799998.86")

    def test_whitespace_inside_chinese_label_is_supported(self):
        vals = _numeric_tokens_after_alias_preserve_columns(
            "资 产 总 计  123,456.78  100,000.00",
            "资产总计",
        )
        self.assertEqual(str(vals[0][1]), "123456.78")


if __name__ == "__main__":
    unittest.main()
