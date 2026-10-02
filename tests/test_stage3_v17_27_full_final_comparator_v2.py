from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import compare_stage3_s3g1j_v17_27_full_final_v2 as v2


class V1727FullFinalComparatorV2Tests(unittest.TestCase):
    def test_top_level_conflict_order_is_semantically_ignored(self):
        first = json.dumps(
            [
                {"concept": "TOTAL_ASSETS", "values": [["a", "1"], ["b", "2"]]},
                {"concept": "TOTAL_EQUITY", "values": [["a", "3"], ["b", "4"]]},
            ],
            ensure_ascii=False,
        )
        second = json.dumps(
            [
                {"concept": "TOTAL_EQUITY", "values": [["a", "3"], ["b", "4"]]},
                {"concept": "TOTAL_ASSETS", "values": [["a", "1"], ["b", "2"]]},
            ],
            ensure_ascii=False,
        )
        self.assertEqual(
            v2.canonical_document_error(first),
            v2.canonical_document_error(second),
        )

    def test_nested_candidate_value_order_remains_strict(self):
        first = json.dumps(
            [{"concept": "TOTAL_ASSETS", "values": [["a", "1"], ["b", "2"]]}]
        )
        second = json.dumps(
            [{"concept": "TOTAL_ASSETS", "values": [["b", "2"], ["a", "1"]]}]
        )
        self.assertNotEqual(
            v2.canonical_document_error(first),
            v2.canonical_document_error(second),
        )

    def test_exact_five_tie_recovery_is_accepted(self):
        def fake_compare(*args):
            current_for_v1 = args[-1]
            self.assertEqual(current_for_v1["unresolved_tie_count"], 1295)
            return {"errors": [], "pass": True, "execution_verdict": "PASS"}

        with patch.object(v2.v1, "compare", side_effect=fake_compare):
            report = v2.compare(
                [],
                [],
                [],
                [],
                {"unresolved_tie_count": 1295},
                {"unresolved_tie_count": 1290},
            )
        self.assertTrue(report["pass"])
        self.assertEqual(report["recovered_unresolved_tie_count"], 5)
        self.assertTrue(report["top_level_conflict_concept_order_normalized"])
        self.assertTrue(report["nested_conflict_evidence_order_preserved"])

    def test_wrong_tie_transition_fails_closed(self):
        with patch.object(
            v2.v1,
            "compare",
            return_value={"errors": [], "pass": True, "execution_verdict": "PASS"},
        ):
            report = v2.compare(
                [],
                [],
                [],
                [],
                {"unresolved_tie_count": 1295},
                {"unresolved_tie_count": 1291},
            )
        self.assertFalse(report["pass"])
        self.assertTrue(any("current unresolved ties" in row for row in report["errors"]))


if __name__ == "__main__":
    unittest.main()
