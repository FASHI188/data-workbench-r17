from __future__ import annotations

import unittest

import diagnose_stage3_s3g1j_p0_layout_evidence as evidence


class P0LayoutEvidenceTests(unittest.TestCase):
    def test_title_like_accepts_balance_sheet_headings(self):
        self.assertTrue(evidence.title_like("合 并 资 产 负 债 表"))
        self.assertTrue(evidence.title_like("母公司资产负债表（续）"))
        self.assertFalse(evidence.title_like("本期合并范围发生变化的原因"))

    def test_concept_aliases_are_explicit(self):
        matched = evidence.concept_aliases(
            "资产总计 1,000 负债合计 600 所有者权益合计 400"
        )
        self.assertIn("资产总计", matched["TOTAL_ASSETS"])
        self.assertIn("负债合计", matched["TOTAL_LIABILITIES"])
        self.assertIn("所有者权益合计", matched["TOTAL_EQUITY"])

    def test_serialize_event_keeps_role_evidence(self):
        event = {
            "page": 2,
            "y": 10.5,
            "x0": 1.0,
            "x1": 9.0,
            "x_center": 5.0,
            "role": "GROUP",
            "line": "合并资产负债表",
            "matched_title": "合并资产负债表",
            "ignored": "x",
        }
        result = evidence.serialize_event(event)
        self.assertEqual(result["role"], "GROUP")
        self.assertNotIn("ignored", result)

    def test_title_like_rejects_long_narrative(self):
        self.assertFalse(evidence.title_like("合并" + "说明" * 80))


if __name__ == "__main__":
    unittest.main()
