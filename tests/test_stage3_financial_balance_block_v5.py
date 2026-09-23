import unittest

from scripts.stage3_financial_pdf_parser_v3 import (
    NO_VALIDATED_BALANCE_BLOCK,
    _enforce_validated_balance_block,
    _numeric_tokens_after_alias_preserve_columns,
)


class BalanceBlockV5Tests(unittest.TestCase):
    def test_lone_note_index_is_not_accepted_as_amount(self):
        vals = _numeric_tokens_after_alias_preserve_columns("负债合计 18", "负债合计")
        self.assertEqual(vals, [])

    def test_note_index_is_dropped_when_amount_columns_follow(self):
        vals = _numeric_tokens_after_alias_preserve_columns(
            "负债合计 18 52799998.86 48000000.00", "负债合计"
        )
        self.assertGreaterEqual(len(vals), 2)
        self.assertEqual(str(vals[0][1]), "52799998.86")
        self.assertEqual(str(vals[1][1]), "48000000.00")

    def test_small_decimal_amount_is_not_misclassified_as_note(self):
        vals = _numeric_tokens_after_alias_preserve_columns(
            "负债合计 18.00 17.00", "负债合计"
        )
        self.assertEqual(str(vals[0][1]), "18.00")

    def test_missing_validated_block_is_hard_error(self):
        parsed = _enforce_validated_balance_block({
            "balance_sheet_block": None,
            "validation_errors": [],
        })
        self.assertIn(NO_VALIDATED_BALANCE_BLOCK, parsed["validation_errors"])

    def test_validated_block_does_not_add_hard_error(self):
        parsed = _enforce_validated_balance_block({
            "balance_sheet_block": {"start_page": 7, "unit": "元"},
            "validation_errors": [],
        })
        self.assertNotIn(NO_VALIDATED_BALANCE_BLOCK, parsed["validation_errors"])


if __name__ == "__main__":
    unittest.main()
