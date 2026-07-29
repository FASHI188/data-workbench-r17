from __future__ import annotations

import unittest

import stage3_financial_statement_blocks_v16_3 as blocks


class StatementBlocksV163Tests(unittest.TestCase):
    def test_corrupted_dual_title_is_normalized_only_in_title_parser(self):
        role, continuation = blocks.classify_formal_statement_title("合幵及银行资产负债表")
        self.assertEqual(role, "DUAL_GROUP_PARENT")
        self.assertFalse(continuation)

    def test_narrative_reference_is_not_a_formal_title(self):
        role, _ = blocks.classify_formal_statement_title("公司按照准则编制合并资产负债表并调整期初数")
        self.assertIsNone(role)

    def test_dated_group_title_and_continuation(self):
        role, continuation = blocks.classify_formal_statement_title("2024年6月30日合并资产负债表（续）")
        self.assertEqual(role, "GROUP")
        self.assertTrue(continuation)

    def test_standalone_units_are_exact_only(self):
        self.assertEqual(blocks.detect_standalone_statement_unit("人民币百万元"), ("百万元", blocks.Decimal("1000000")))
        self.assertEqual(blocks.detect_standalone_statement_unit("人民币元"), ("元", blocks.Decimal("1")))
        self.assertEqual(blocks.detect_standalone_statement_unit("本期以人民币元列示"), (None, None))

    def test_same_page_same_band_uses_horizontal_nearest_title(self):
        events = [
            {"page": 10, "y": 100.0, "x_center": 150.0, "x0": 100.0, "role": "GROUP", "continuation": False, "line": "合并资产负债表", "matched_title": "合并资产负债表"},
            {"page": 10, "y": 101.0, "x_center": 450.0, "x0": 400.0, "role": "PARENT", "continuation": False, "line": "公司资产负债表", "matched_title": "公司资产负债表"},
        ]
        left = blocks.bind_alias_to_preceding_statement_event(events, 10, 300.0, 140.0)
        right = blocks.bind_alias_to_preceding_statement_event(events, 10, 300.0, 460.0)
        self.assertEqual(left["role"], "GROUP")
        self.assertEqual(right["role"], "PARENT")

    def test_later_parent_title_does_not_relabel_earlier_group_row(self):
        events = [
            {"page": 10, "y": 100.0, "x_center": 180.0, "x0": 120.0, "role": "GROUP", "continuation": False, "line": "合并资产负债表", "matched_title": "合并资产负债表"},
            {"page": 10, "y": 500.0, "x_center": 180.0, "x0": 120.0, "role": "PARENT", "continuation": False, "line": "母公司资产负债表", "matched_title": "母公司资产负债表"},
        ]
        before_parent = blocks.bind_alias_to_preceding_statement_event(events, 10, 350.0, 180.0)
        after_parent = blocks.bind_alias_to_preceding_statement_event(events, 10, 650.0, 180.0)
        self.assertEqual(before_parent["role"], "GROUP")
        self.assertEqual(after_parent["role"], "PARENT")


if __name__ == "__main__":
    unittest.main()
