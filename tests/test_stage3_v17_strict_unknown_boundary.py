from __future__ import annotations

import unittest

import stage3_financial_statement_blocks_v16_5 as blocks


def _row(text: str) -> dict:
    return {
        "text": text,
        "y": 100.0,
        "words": [
            {"text": text, "x0": 100.0, "y0": 95.0, "x1": 500.0, "y1": 105.0}
        ],
    }


class V17StrictUnknownBoundaryTests(unittest.TestCase):
    def test_narrative_balance_sheet_references_do_not_create_unknown_events(self):
        narratives = (
            "本集团在每个资产负债表日评估相关金融工具的信用风险自初始确认后是否显著增加",
            "负债相互抵消后以净额在资产负债表列示。于2025年度，本集团无该事项",
            "十五、资产负债表日后事项",
            "3.1 资产负债表项目分析",
            "资产负债表中的资产和负债项目采用资产负债表日的即期汇率折算",
        )
        for text in narratives:
            with self.subTest(text=text):
                events = blocks._title_occurrences_v17_2(_row(text))
                self.assertFalse(any(e.get("role") == "UNKNOWN_STATEMENT" for e in events), events)

    def test_genuine_unqualified_headings_remain_hard_unknown_boundaries(self):
        headings = (
            "资产负债表",
            "资产负债表(续)",
            "未经审计资产负债表",
            "未经审计资产负债表（续）",
            "1、资产负债表",
            "资产负债表 10-12",
        )
        for text in headings:
            with self.subTest(text=text):
                self.assertTrue(blocks._strict_unknown_statement_title(text))
                events = blocks._title_occurrences_v17_2(_row(text))
                self.assertTrue(any(e.get("role") == "UNKNOWN_STATEMENT" for e in events), events)

    def test_group_and_parent_title_occurrences_are_not_changed_by_unknown_filter(self):
        for text, expected in (
            ("合并资产负债表", "GROUP"),
            ("母公司资产负债表", "PARENT"),
            ("合并及母公司资产负债表", "DUAL_GROUP_PARENT"),
        ):
            with self.subTest(text=text):
                events = blocks._title_occurrences_v17_2(_row(text))
                self.assertTrue(any(e.get("role") == expected for e in events), events)


if __name__ == "__main__":
    unittest.main()
