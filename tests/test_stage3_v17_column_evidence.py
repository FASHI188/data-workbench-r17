from __future__ import annotations

import unittest
from unittest.mock import patch

import stage3_financial_spatial_alias_v16_7 as v167


class V17ColumnEvidenceTests(unittest.TestCase):
    def test_strict_single_date_statement_header_forms_are_exact(self):
        expected = "2023年12月31日"
        self.assertEqual(
            v167._strict_single_date_header_form(f"于{expected}", expected),
            "V17_11_STRICT_LEADING_YU_DATE",
        )
        self.assertEqual(
            v167._strict_single_date_header_form(f"{expected}人民币千元", expected),
            "V17_11_STRICT_DATE_WITH_EXPLICIT_UNIT",
        )
        self.assertEqual(
            v167._strict_single_date_header_form(f"{expected}百万元", expected),
            "V17_11_STRICT_DATE_WITH_EXPLICIT_UNIT",
        )
        for text in (
            f"截至{expected}",
            f"于{expected}本集团",
            f"{expected}后事项",
            f"{expected}未经审计",
        ):
            with self.subTest(text=text):
                self.assertIsNone(v167._strict_single_date_header_form(text, expected))

    def _candidate(self, page=10, anchor=10, role="GROUP", unit="千元"):
        return {
            "page": page,
            "statement_anchor_page": anchor,
            "statement_role": role,
            "unit": unit,
            "raw_value": "100",
            "value_x": "400",
        }

    def test_same_page_sibling_requires_direct_pass_same_anchor_role_and_unit(self):
        target = self._candidate()
        selected = {
            "TOTAL_ASSETS": self._candidate(),
            "TOTAL_LIABILITIES": target,
            "TOTAL_EQUITY": self._candidate(),
        }
        direct = {
            "TOTAL_ASSETS": {
                "pass": True,
                "evidence_source": "DIRECT_EXPECTED_DATE_HEADER",
                "header": {"page": 10, "expected_column_index": 0},
            },
            "TOTAL_LIABILITIES": {"pass": False},
            "TOTAL_EQUITY": {"pass": False},
        }
        mapped_result = {
            "pass": True,
            "evidence_source": "SAME_PAGE_SAME_ANCHOR_DIRECT_SIBLING_HEADER",
        }
        with patch.object(v167, "_column_role_evidence_with_header", return_value=mapped_result) as mapped:
            out = v167._same_page_trusted_sibling_column_evidence(
                object(), "TOTAL_LIABILITIES", target, selected, direct
            )
        self.assertTrue(out["pass"])
        self.assertEqual(out["trusted_sibling_concept"], "TOTAL_ASSETS")
        self.assertEqual(out["evidence_source"], "SAME_PAGE_SAME_ANCHOR_DIRECT_SIBLING_HEADER")
        mapped.assert_called_once()

        for field, bad in (
            ("page", 11),
            ("statement_anchor_page", 9),
            ("statement_role", "PARENT"),
            ("unit", "元"),
        ):
            broken = {k: dict(v) for k, v in selected.items()}
            broken["TOTAL_ASSETS"][field] = bad
            with patch.object(v167, "_column_role_evidence_with_header", return_value=mapped_result):
                out = v167._same_page_trusted_sibling_column_evidence(
                    object(), "TOTAL_LIABILITIES", target, broken, direct
                )
            self.assertIsNone(out, field)

    def test_sibling_reuse_is_non_transitive(self):
        target = self._candidate()
        selected = {
            "TOTAL_ASSETS": self._candidate(),
            "TOTAL_LIABILITIES": target,
            "TOTAL_EQUITY": self._candidate(),
        }
        direct = {
            "TOTAL_ASSETS": {"pass": False},
            "TOTAL_LIABILITIES": {"pass": False},
            # A sibling-derived result must never seed another reuse because only
            # direct evidence is passed to the helper.
            "TOTAL_EQUITY": {
                "pass": False,
                "evidence_source": "SAME_PAGE_SAME_ANCHOR_DIRECT_SIBLING_HEADER",
                "header": {"page": 10, "expected_column_index": 0},
            },
        }
        with patch.object(
            v167,
            "_column_role_evidence_with_header",
            return_value={"pass": True, "evidence_source": "SAME_PAGE_SAME_ANCHOR_DIRECT_SIBLING_HEADER"},
        ):
            out = v167._same_page_trusted_sibling_column_evidence(
                object(), "TOTAL_LIABILITIES", target, selected, direct
            )
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
