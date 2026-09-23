from __future__ import annotations

from decimal import Decimal
import unittest

import stage3_financial_spatial_alias_v17_15 as v1715


def word(text: str, x0: float, x1: float | None = None):
    return {"text": text, "x0": x0, "x1": x1 if x1 is not None else x0 + 20, "y0": 0, "y1": 10}


class V1715AdjacentBridgeTests(unittest.TestCase):
    def test_exact_terminal_alias_rejects_subtotals_and_equity_change_headers(self):
        self.assertTrue(v1715._exact_terminal_alias("资产总计", "资产总计", "TOTAL_ASSETS"))
        self.assertFalse(v1715._exact_terminal_alias("流动资产合计", "资产合计", "TOTAL_ASSETS"))
        self.assertTrue(v1715._exact_terminal_alias("股东权益合计", "股东权益合计", "TOTAL_EQUITY"))
        self.assertFalse(
            v1715._exact_terminal_alias(
                "股本 资本公积 未分配利润 股东权益合计",
                "股东权益合计",
                "TOTAL_EQUITY",
            )
        )

    def test_adjacent_numeric_row_is_narrow_and_numeric_only(self):
        current = {"y": 100.0, "text": "资产总计", "words": [word("资产总计", 10)]}
        good = {
            "y": 103.0,
            "text": "1,000 900",
            "words": [word("1,000", 300), word("900", 400)],
        }
        out = v1715._adjacent_numeric_row([current, good], 0, 100)
        self.assertIsNotNone(out)
        _, amounts, delta = out
        self.assertEqual(delta, Decimal("3.0"))
        self.assertEqual([x["value"] for x in amounts], [Decimal("1000"), Decimal("900")])

        too_close = dict(good, y=102.8)
        self.assertIsNone(v1715._adjacent_numeric_row([current, too_close], 0, 100))
        too_far = dict(good, y=103.26)
        self.assertIsNone(v1715._adjacent_numeric_row([current, too_far], 0, 100))
        narrative = {
            "y": 103.0,
            "text": "附注 1,000 900",
            "words": [word("附注", 250), word("1,000", 300), word("900", 400)],
        }
        self.assertIsNone(v1715._adjacent_numeric_row([current, narrative], 0, 100))
        one_column = {"y": 103.0, "text": "1,000", "words": [word("1,000", 300)]}
        self.assertIsNone(v1715._adjacent_numeric_row([current, one_column], 0, 100))

    def test_bridge_column_gate_reapplies_frozen_date_ordinal(self):
        candidate = {
            "raw_value": "1000",
            "value_x": Decimal("300"),
            "bridge_y_delta": "3.0",
            "bridge_numeric_row_text": "1000 900",
            "bridge_amount_columns": [
                {"raw": "1000", "value": Decimal("1000"), "x0": Decimal("300")},
                {"raw": "900", "value": Decimal("900"), "x0": Decimal("400")},
            ],
        }
        passed = v1715._bridge_column_evidence_with_header(
            candidate, {"page": 10, "expected_column_index": 0}, "DIRECT_EXPECTED_DATE_HEADER"
        )
        self.assertTrue(passed["pass"])
        failed = v1715._bridge_column_evidence_with_header(
            candidate, {"page": 10, "expected_column_index": 1}, "DIRECT_EXPECTED_DATE_HEADER"
        )
        self.assertFalse(failed["pass"])

    def test_dedupe_prefers_existing_same_row_candidate(self):
        common = {
            "value": Decimal("1000"),
            "page": 10,
            "statement_anchor_page": 10,
            "value_x": Decimal("300"),
            "alias_strength": 5,
            "alias": "资产总计",
            "alias_x0": 10,
        }
        existing = dict(common, adjacent_row_bridge=False)
        bridged = dict(common, adjacent_row_bridge=True, alias_strength=99)
        out = v1715._dedupe_candidates({"TOTAL_ASSETS": [bridged, existing]})
        self.assertEqual(len(out["TOTAL_ASSETS"]), 1)
        self.assertFalse(out["TOTAL_ASSETS"][0]["adjacent_row_bridge"])

    def test_sibling_header_reuse_remains_non_transitive_and_context_bound(self):
        target = {
            "page": 10,
            "statement_anchor_page": 10,
            "statement_role": "GROUP",
            "unit": "千元",
            "adjacent_row_bridge": True,
            "raw_value": "1000",
            "value_x": "300",
            "bridge_amount_columns": [
                {"raw": "1000", "value": Decimal("1000"), "x0": Decimal("300")},
                {"raw": "900", "value": Decimal("900"), "x0": Decimal("400")},
            ],
        }
        selected = {
            "TOTAL_ASSETS": dict(target),
            "TOTAL_LIABILITIES": target,
            "TOTAL_EQUITY": dict(target),
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
        out = v1715._trusted_sibling_evidence(object(), "TOTAL_LIABILITIES", target, selected, direct)
        self.assertTrue(out["pass"])
        self.assertEqual(out["trusted_sibling_concept"], "TOTAL_ASSETS")

        direct["TOTAL_ASSETS"] = {
            "pass": False,
            "evidence_source": "SAME_PAGE_SAME_ANCHOR_DIRECT_SIBLING_HEADER",
            "header": {"page": 10, "expected_column_index": 0},
        }
        self.assertIsNone(v1715._trusted_sibling_evidence(object(), "TOTAL_LIABILITIES", target, selected, direct))


if __name__ == "__main__":
    unittest.main()
