from __future__ import annotations

import unittest
from unittest.mock import patch

import stage3_financial_pdf_parser as parser_base
import stage3_financial_spatial_alias_v16_3 as v166
import stage3_financial_statement_blocks_v16_5 as blocks


class _Rect:
    def __init__(self, y0: float):
        self.y0 = y0


class _UnitPage:
    def get_text(self, mode: str = "text", **kwargs):
        if mode == "words":
            return []
        return "(除特别注明外，以人民币百万元列示)\n"

    def search_for(self, text: str):
        if text == "(除特别注明外，以人民币百万元列示)":
            return [_Rect(105.1)]
        return []


class _FakeDoc:
    def __init__(self, page):
        self.page = page

    def __getitem__(self, index):
        if index != 0:
            raise IndexError(index)
        return self.page


class V17ExplicitDualEvidenceTests(unittest.TestCase):
    def test_v14_base_aliases_remain_unchanged(self):
        self.assertEqual(parser_base.TIER2_ALIASES["TOTAL_LIABILITIES"], ["负债合计"])
        aliases = v166._v16_concept_aliases()["TOTAL_LIABILITIES"]
        self.assertIn("负债合计", aliases)
        self.assertIn("负债总计", aliases)

    def test_explicit_presentation_unit_is_v16_only_and_positioned(self):
        self.assertEqual(parser_base.detect_unit("(除特别注明外，以人民币百万元列示)"), (None, None))
        units = blocks._page_units_with_y_v16_5(_UnitPage())
        presentation = [u for u in units if u.get("source") == "TEXT_LINE_EXPLICIT_PRESENTATION_UNIT"]
        self.assertEqual(len(presentation), 1)
        self.assertEqual(presentation[0]["unit"], "百万元")
        self.assertEqual(str(presentation[0]["multiplier"]), "1000000")
        self.assertEqual(presentation[0]["line"], "(除特别注明外，以人民币百万元列示)")
        self.assertEqual(presentation[0]["y"], 105.1)

    def test_generic_unknown_is_promoted_only_with_explicit_dual_role_split(self):
        event = {
            "page": 1,
            "y": 90.0,
            "x0": 270.0,
            "x1": 326.0,
            "x_center": 298.0,
            "role": "UNKNOWN_STATEMENT",
            "continuation": False,
            "line": "资产负债表",
            "matched_title": "资产负债表",
        }
        split = {"group_header_x": 275, "parent_header_x": 442, "split_x": 358.5}
        with patch.object(blocks, "_ORIGINAL_FORMAL_STATEMENT_EVENTS", return_value=[event]):
            with patch.object(blocks.v14, "_page_role_split", return_value=split):
                out = blocks.formal_statement_events(_FakeDoc(object()))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["role"], "DUAL_GROUP_PARENT")
        self.assertEqual(out[0]["matched_title"], "GENERIC_BALANCE_SHEET_WITH_EXPLICIT_DUAL_ROLE_HEADERS")
        self.assertEqual(out[0]["role_header_evidence"]["split_x"], "358.5")

    def test_generic_unknown_without_split_remains_unknown(self):
        event = {
            "page": 1,
            "y": 90.0,
            "x0": 270.0,
            "x1": 326.0,
            "x_center": 298.0,
            "role": "UNKNOWN_STATEMENT",
            "continuation": False,
            "line": "未经审计资产负债表",
            "matched_title": "资产负债表",
        }
        with patch.object(blocks, "_ORIGINAL_FORMAL_STATEMENT_EVENTS", return_value=[event]):
            with patch.object(blocks.v14, "_page_role_split", return_value=None):
                out = blocks.formal_statement_events(_FakeDoc(object()))
        self.assertEqual(out[0]["role"], "UNKNOWN_STATEMENT")

    def test_narrative_unknown_is_not_promoted_even_if_split_exists(self):
        event = {
            "page": 1,
            "y": 90.0,
            "x0": 270.0,
            "x1": 326.0,
            "x_center": 298.0,
            "role": "UNKNOWN_STATEMENT",
            "continuation": False,
            "line": "资产负债表日后事项",
            "matched_title": "资产负债表",
        }
        split = {"group_header_x": 275, "parent_header_x": 442, "split_x": 358.5}
        with patch.object(blocks, "_ORIGINAL_FORMAL_STATEMENT_EVENTS", return_value=[event]):
            with patch.object(blocks.v14, "_page_role_split", return_value=split):
                out = blocks.formal_statement_events(_FakeDoc(object()))
        self.assertEqual(out[0]["role"], "UNKNOWN_STATEMENT")


if __name__ == "__main__":
    unittest.main()
