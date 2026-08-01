from __future__ import annotations

import json
import unittest

from scripts.compare_stage3_s3g1j_v17_25_full_final import (
    canonical_document_error,
)


class FullFinalComparatorTest(unittest.TestCase):
    def test_reordered_conflict_evidence_is_semantically_equal(self) -> None:
        left = json.dumps(
            [
                {
                    "concept": "TOTAL_ASSETS",
                    "values": [["a", "10"], ["b", "11"]],
                },
                {
                    "concept": "TOTAL_LIABILITIES",
                    "values": [["a", "4"], ["b", "5"]],
                },
            ],
            ensure_ascii=False,
        )
        right = json.dumps(
            [
                {
                    "values": [["b", "5"], ["a", "4"]],
                    "concept": "TOTAL_LIABILITIES",
                },
                {
                    "values": [["b", "11"], ["a", "10"]],
                    "concept": "TOTAL_ASSETS",
                },
            ],
            ensure_ascii=False,
        )
        self.assertEqual(
            canonical_document_error(left),
            canonical_document_error(right),
        )

    def test_changed_value_remains_a_regression(self) -> None:
        left = json.dumps(
            [{"concept": "TOTAL_ASSETS", "values": [["a", "10"]]}]
        )
        right = json.dumps(
            [{"concept": "TOTAL_ASSETS", "values": [["a", "10.01"]]}]
        )
        self.assertNotEqual(
            canonical_document_error(left),
            canonical_document_error(right),
        )

    def test_duplicate_evidence_is_not_collapsed(self) -> None:
        one = json.dumps([{"concept": "TOTAL_ASSETS", "values": [["a", "10"]]}])
        duplicate = json.dumps(
            [
                {"concept": "TOTAL_ASSETS", "values": [["a", "10"]]},
                {"concept": "TOTAL_ASSETS", "values": [["a", "10"]]},
            ]
        )
        self.assertNotEqual(
            canonical_document_error(one),
            canonical_document_error(duplicate),
        )

    def test_plain_text_errors_remain_byte_exact(self) -> None:
        self.assertEqual(
            canonical_document_error("plain fail-closed error"),
            "plain fail-closed error",
        )
        self.assertNotEqual(
            canonical_document_error("plain fail-closed error"),
            canonical_document_error("plain fail closed error"),
        )


if __name__ == "__main__":
    unittest.main()
