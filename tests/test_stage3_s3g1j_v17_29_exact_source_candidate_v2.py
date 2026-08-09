from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

import stage3_financial_pdf_parser_v21_candidate_v2 as candidate


class V1729ExactSourceCandidateV2Tests(unittest.TestCase):
    def test_target_population_and_tolerance_unchanged(self) -> None:
        self.assertEqual(len(candidate.TARGETS), 7)
        self.assertEqual(candidate.IDENTITY_TOLERANCE, Decimal("0.005"))
        self.assertEqual(candidate.MAX_LABEL_FRAGMENT_ROWS, 3)
        self.assertEqual(candidate.MAX_ROW_GAP, Decimal("24"))

    def test_all_frozen_dual_identities_still_close_exactly(self) -> None:
        for target in candidate.TARGETS.values():
            identity = candidate.base._validate_identity(target)
            self.assertTrue(
                all(Decimal(row["identity_residual_cny"]) == 0 for row in identity["columns"])
            )

    def test_label_split_around_amount_is_recognized(self) -> None:
        target = next(
            row for row in candidate.TARGETS.values()
            if row["announcement_id"] == "1215186538"
        )
        rows = [
            {"text": "所有者权益（或股东权", "y": 100.0, "words": []},
            {"text": "1,080,008,925.97 1,088,521,670.81", "y": 107.0, "words": []},
            {"text": "益）合计", "y": 114.0, "words": []},
        ]
        pair = [
            {"value": target["values"]["TOTAL_EQUITY"][0], "raw": "1,080,008,925.97", "x0": 320.0},
            {"value": target["values"]["TOTAL_EQUITY"][1], "raw": "1,088,521,670.81", "x0": 430.0},
        ]
        event = {"page": 1, "role": "GROUP", "line": "合并资产负债表（更正后）", "y": 20.0}
        with patch.object(
            candidate.base,
            "_amount_pair",
            side_effect=lambda row, expected: pair if row is rows[1] else None,
        ), patch.object(candidate.base, "_amounts", return_value=[]), patch.object(
            candidate.base, "_bind", return_value=event
        ), patch.object(candidate.base, "_validate_header", return_value={"ok": True}):
            result = candidate._find_split_equity({1: rows}, [event], target)
        self.assertEqual(result["pattern"], "SPLIT_LABEL_1_BEFORE_1_AFTER_AMOUNT")
        self.assertEqual(result["row_gaps"], ["7.0", "7.0"])

    def test_amount_row_cannot_skip_intervening_numeric_label_fragment(self) -> None:
        target = next(iter(candidate.TARGETS.values()))
        rows = [
            {"text": "所有者权益（或股东权", "y": 100.0, "words": []},
            {"text": "1,080,008,925.97 1,088,521,670.81", "y": 107.0, "words": []},
            {"text": "益）合计 999", "y": 114.0, "words": []},
        ]
        pair = [
            {"value": target["values"]["TOTAL_EQUITY"][0], "raw": "x", "x0": 320.0},
            {"value": target["values"]["TOTAL_EQUITY"][1], "raw": "y", "x0": 430.0},
        ]
        with patch.object(
            candidate.base,
            "_amount_pair",
            side_effect=lambda row, expected: pair if row is rows[1] else None,
        ), patch.object(
            candidate.base,
            "_amounts",
            side_effect=lambda row: [{"value": "999"}] if row is rows[2] else [],
        ):
            with self.assertRaisesRegex(ValueError, "count expected=1 actual=0"):
                candidate._find_split_equity({1: rows}, [], target)

    def test_non_target_returns_formal_v1728_object_identity(self) -> None:
        sentinel = {"parser_version": "FORMAL_V17_28"}
        with patch.object(candidate.accepted, "parse_pdf_bytes", return_value=sentinel):
            actual = candidate.parse_pdf_bytes(b"not-a-target", "2024-06-30")
        self.assertIs(actual, sentinel)


if __name__ == "__main__":
    unittest.main()
