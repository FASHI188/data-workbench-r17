from __future__ import annotations

import json
import unittest

from scripts.compare_stage3_s3g1j_v17_26_full_final_v2 import canonical_document_error


class V1726FullFinalComparatorTests(unittest.TestCase):
    def test_only_top_level_conflict_order_is_non_semantic(self) -> None:
        assets = {
            "concept": "TOTAL_ASSETS",
            "values": [["1201", "10"], ["1202", "11"]],
        }
        liabilities = {
            "concept": "TOTAL_LIABILITIES",
            "values": [["1201", "4"], ["1202", "5"]],
        }
        left = json.dumps([assets, liabilities], ensure_ascii=False)
        right = json.dumps([liabilities, assets], ensure_ascii=False)
        self.assertEqual(
            canonical_document_error(left),
            canonical_document_error(right),
        )

    def test_nested_candidate_order_remains_semantic(self) -> None:
        left = json.dumps(
            [{"concept": "TOTAL_ASSETS", "values": [["1201", "10"], ["1202", "11"]]}]
        )
        right = json.dumps(
            [{"concept": "TOTAL_ASSETS", "values": [["1202", "11"], ["1201", "10"]]}]
        )
        self.assertNotEqual(
            canonical_document_error(left),
            canonical_document_error(right),
        )

    def test_changed_value_remains_a_regression(self) -> None:
        left = json.dumps(
            [{"concept": "TOTAL_ASSETS", "values": [["1201", "10"]]}]
        )
        right = json.dumps(
            [{"concept": "TOTAL_ASSETS", "values": [["1201", "10.01"]]}]
        )
        self.assertNotEqual(
            canonical_document_error(left),
            canonical_document_error(right),
        )

    def test_duplicate_evidence_is_not_collapsed(self) -> None:
        one = json.dumps([{"concept": "TOTAL_ASSETS", "values": [["1201", "10"]]}])
        duplicate = json.dumps(
            [
                {"concept": "TOTAL_ASSETS", "values": [["1201", "10"]]},
                {"concept": "TOTAL_ASSETS", "values": [["1201", "10"]]},
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
