from __future__ import annotations

import copy
import unittest
from unittest import mock

import diagnose_stage3_s3g1j_v17_28_split_equity as diagnostic


def row(y: float, tokens: list[tuple[str, float]]) -> dict:
    words = []
    for text, x0 in tokens:
        words.append(
            {
                "x0": x0,
                "y0": y - 2,
                "x1": x0 + max(8.0, len(text) * 5.0),
                "y1": y + 2,
                "text": text,
            }
        )
    return {
        "row_index": 0,
        "y": y,
        "text": " ".join(text for text, _ in tokens),
        "words": words,
    }


class V1728SplitEquityDiagnosticTests(unittest.TestCase):
    def test_exact_target_scope_and_source_identity_are_frozen(self) -> None:
        self.assertEqual(set(diagnostic.TARGETS), {"1207621057", "1209825769"})
        self.assertEqual(
            diagnostic.TARGETS["1207621057"]["source_sha256"],
            "b2aa4afa67e2b02010d5ba708d4e5fe02138623ff4bc48718c03029111a64568",
        )
        self.assertEqual(diagnostic.TARGETS["1207621057"]["source_bytes"], 477621)
        self.assertEqual(
            diagnostic.TARGETS["1209825769"]["source_sha256"],
            "0bd1da8bdac0aff2a3e99b83adc29e7b60e959c99dd29b8ab88cbda1344b441c",
        )
        self.assertEqual(diagnostic.TARGETS["1209825769"]["source_bytes"], 633887)
        self.assertEqual(
            diagnostic.DOCUMENTS_GZIP_SHA256,
            "c2abe07baaa76efb80a30cfdd4e762ad07814f6aa795a92b9c0504f7944ab99a",
        )

    def test_label_and_amounts_then_continuation_is_accepted(self) -> None:
        rows = [
            row(
                100,
                [
                    ("所有者权益（或股东权益）合", 90),
                    ("3,249,566,596.93", 310),
                    ("3,163,797,498.46", 450),
                ],
            ),
            row(112, [("计", 90)]),
        ]
        result = diagnostic.find_split_equity_sequence(
            rows, ["3249566596.93", "3163797498.46"]
        )
        self.assertEqual(result["pattern"], "LABEL_AND_AMOUNTS_THEN_CONTINUATION")
        self.assertEqual(result["amount_index"], 0)
        self.assertEqual(result["continuation_index"], 1)

    def test_label_then_amounts_then_continuation_is_accepted(self) -> None:
        rows = [
            row(100, [("所有者权益（或股东权益）合", 90)]),
            row(108, [("1,303,323,546.81", 310), ("1,261,570,672.73", 450)]),
            row(116, [("计", 90)]),
        ]
        result = diagnostic.find_split_equity_sequence(
            rows, ["1303323546.81", "1261570672.73"]
        )
        self.assertEqual(result["pattern"], "LABEL_THEN_AMOUNTS_THEN_CONTINUATION")
        self.assertEqual(result["amount_index"], 1)
        self.assertEqual(result["continuation_index"], 2)

    def test_missing_continuation_is_rejected(self) -> None:
        rows = [
            row(
                100,
                [
                    ("所有者权益（或股东权益）合", 90),
                    ("3,249,566,596.93", 310),
                    ("3,163,797,498.46", 450),
                ],
            )
        ]
        with self.assertRaisesRegex(ValueError, "sequence count"):
            diagnostic.find_split_equity_sequence(
                rows, ["3249566596.93", "3163797498.46"]
            )

    def test_amount_only_row_with_extra_text_is_rejected(self) -> None:
        rows = [
            row(100, [("所有者权益（或股东权益）合", 90)]),
            row(
                108,
                [
                    ("其中", 90),
                    ("1,303,323,546.81", 310),
                    ("1,261,570,672.73", 450),
                ],
            ),
            row(116, [("计", 90)]),
        ]
        with self.assertRaisesRegex(ValueError, "sequence count"):
            diagnostic.find_split_equity_sequence(
                rows, ["1303323546.81", "1261570672.73"]
            )

    def test_parent_role_is_rejected(self) -> None:
        label = row(100, [("所有者权益（或股东权益）合", 90)])
        parent = {
            "page": 8,
            "y": 40,
            "role": "PARENT",
            "line": "母公司资产负债表",
        }
        with mock.patch.object(
            diagnostic.blocks,
            "bind_alias_to_preceding_statement_event",
            return_value=parent,
        ):
            with self.assertRaisesRegex(ValueError, "must be GROUP"):
                diagnostic.validate_group_event([], 10, label, 8)

    def test_group_anchor_page_and_title_are_required(self) -> None:
        label = row(100, [("所有者权益（或股东权益）合", 90)])
        wrong_page = {
            "page": 7,
            "y": 40,
            "role": "GROUP",
            "line": "合并资产负债表",
        }
        with mock.patch.object(
            diagnostic.blocks,
            "bind_alias_to_preceding_statement_event",
            return_value=wrong_page,
        ):
            with self.assertRaisesRegex(ValueError, "anchor page"):
                diagnostic.validate_group_event([], 10, label, 8)
        wrong_title = dict(wrong_page, page=8, line="合并利润表")
        with mock.patch.object(
            diagnostic.blocks,
            "bind_alias_to_preceding_statement_event",
            return_value=wrong_title,
        ):
            with self.assertRaisesRegex(ValueError, "consolidated balance sheet"):
                diagnostic.validate_group_event([], 10, label, 8)

    def test_both_current_and_prior_identity_columns_are_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "both required"):
            diagnostic.validate_identity(["10"], ["4"], ["6"])

    def test_identity_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "identity failed"):
            diagnostic.validate_identity(
                ["100", "90"], ["40", "30"], ["50", "60"]
            )

    def test_exact_two_column_identity_is_accepted_without_inference(self) -> None:
        result = diagnostic.validate_identity(
            ["5470381065.66", "5189894320.88"],
            ["2220814468.73", "2026096822.42"],
            ["3249566596.93", "3163797498.46"],
        )
        self.assertEqual(len(result["columns"]), 2)
        self.assertEqual(
            [item["identity_residual_cny"] for item in result["columns"]],
            ["0.00", "0.00"],
        )

    def test_non_target_is_rejected_before_network_access(self) -> None:
        document = {
            "announcement_id": "not-target",
            "document_status": "ERROR",
            "numeric_observations": "0",
        }
        with self.assertRaisesRegex(ValueError, "non-target"):
            diagnostic.diagnose_target(document, {}, mock.Mock())

    def test_amount_column_drift_is_fail_closed(self) -> None:
        assets = diagnostic.row_amounts(
            row(100, [("100.00", 300), ("90.00", 440)])
        )
        equity = diagnostic.row_amounts(
            row(110, [("60.00", 350), ("55.00", 490)])
        )
        with self.assertRaisesRegex(ValueError, "column x0 drift"):
            diagnostic.validate_equity_asset_alignment(assets, equity)


if __name__ == "__main__":
    unittest.main()
