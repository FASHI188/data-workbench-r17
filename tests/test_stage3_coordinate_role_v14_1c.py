import unittest

import fitz

import scripts.probe_stage3_s3g1j_coordinate_role_v14_1c as v14c


class CoordinateRoleV141cTests(unittest.TestCase):
    def test_title_role_classification(self):
        self.assertEqual(v14c._line_role("合并资产负债表（续）"), "GROUP")
        self.assertEqual(v14c._line_role("（二）母公司资产负债表"), "PARENT")
        self.assertEqual(
            v14c._line_role("合并资产负债表和母公司资产负债表"),
            "DUAL_GROUP_PARENT",
        )
        self.assertEqual(
            v14c._line_role("合并及银行资产负债表"),
            "DUAL_GROUP_PARENT",
        )

    def test_nearest_title_wins_over_earlier_consolidated_title(self):
        # Use ASCII text for the synthetic PDF round-trip. Default PyMuPDF test
        # fonts do not guarantee CJK round-trip, while Chinese title semantics are
        # already covered directly by test_title_role_classification above.
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text((72, 72), "Consolidated Balance Sheet")
        p2 = doc.new_page()
        p2.insert_text((72, 72), "Balance Sheet of Parent Company")
        doc.new_page().insert_text((72, 72), "Total assets 100")
        role, evidence = v14c._nearest_statement_role(doc, 3)
        self.assertEqual(role, "PARENT")
        self.assertEqual(evidence["chosen"]["page"], 2)

    def test_special_scope_trust_table_is_rejected(self):
        selected = {
            "row_text": "信托资产总计 20,593,926.57 19,640,630.80",
            "alias": "资产总计",
        }
        ok, reason = v14c.probe._row_scope_ok(selected)
        self.assertFalse(ok)
        self.assertEqual(reason, "SPECIAL_SCOPE_PREFIX:信托")

    def test_role_header_tokens_are_explicit_only(self):
        self.assertEqual(v14c.probe.GROUP_HEADERS, ("本集团",))
        self.assertEqual(v14c.probe.PARENT_HEADERS, ("本公司", "本行", "母公司"))


if __name__ == "__main__":
    unittest.main()
