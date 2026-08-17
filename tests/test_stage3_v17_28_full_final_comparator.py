from __future__ import annotations

import copy
import json
import unittest
from collections import Counter

import compare_stage3_s3g1j_v17_28_full_final as comparator


class V1728FullComparatorTests(unittest.TestCase):
    def test_top_level_document_error_order_is_semantic(self) -> None:
        left = json.dumps(
            [
                {"concept": "B", "values": [["2", "20"]]},
                {"concept": "A", "values": [["1", "10"]]},
            ],
            ensure_ascii=False,
        )
        right = json.dumps(
            [
                {"concept": "A", "values": [["1", "10"]]},
                {"concept": "B", "values": [["2", "20"]]},
            ],
            ensure_ascii=False,
        )
        self.assertEqual(
            comparator.v27.canonical_document_error(left),
            comparator.v27.canonical_document_error(right),
        )

    def test_nested_evidence_order_remains_strict(self) -> None:
        left = json.dumps(
            [{"concept": "A", "values": [["1", "10"], ["2", "20"]]}]
        )
        right = json.dumps(
            [{"concept": "A", "values": [["2", "20"], ["1", "10"]]}]
        )
        self.assertNotEqual(
            comparator.v27.canonical_document_error(left),
            comparator.v27.canonical_document_error(right),
        )

    def test_candidate_evidence_array_order_remains_strict(self) -> None:
        left = {field: "" for field in comparator.v27.v1.DOC_FIELDS}
        right = copy.deepcopy(left)
        left["candidate_evidence_json"] = json.dumps(
            [{"id": "1"}, {"id": "2"}]
        )
        right["candidate_evidence_json"] = json.dumps(
            [{"id": "2"}, {"id": "1"}]
        )
        self.assertNotEqual(
            comparator.canonical_document(left),
            comparator.canonical_document(right),
        )

    def test_numeric_semantic_hash_detects_stable_field_drift(self) -> None:
        fields = comparator.v27.v1.STABLE_NUMERIC_FIELDS
        row = {field: field for field in fields}
        changed = dict(row)
        changed["normalized_cny_value"] = "changed"
        original_counter = Counter([comparator.numeric_tuple(row)])
        changed_counter = Counter([comparator.numeric_tuple(changed)])
        self.assertNotEqual(original_counter, changed_counter)
        self.assertNotEqual(
            comparator.semantic_multiset_sha(original_counter),
            comparator.semantic_multiset_sha(changed_counter),
        )

    def test_exact_target_scope_and_pages_are_frozen(self) -> None:
        self.assertEqual(
            set(comparator.TARGETS),
            {"1207621057", "1209825769"},
        )
        concepts = {
            concept
            for target in comparator.TARGETS.values()
            for concept in target["values"]
        }
        self.assertEqual(
            concepts,
            {"TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"},
        )
        self.assertEqual(
            comparator.TARGETS["1207621057"]["values"]["TOTAL_EQUITY"][1:],
            ("10", "所有者权益（或股东权益）合计"),
        )
        self.assertEqual(
            comparator.TARGETS["1209825769"]["values"]["TOTAL_LIABILITIES"][1:],
            ("10", "负债合计"),
        )

    def test_production_identity_is_not_candidate_identity(self) -> None:
        self.assertEqual(comparator.EXPECTED_METHODOLOGY, "V3.3.8-V17.28")
        self.assertIn("PRODUCTION", comparator.EXPECTED_EXTRACTOR_METHOD)
        self.assertNotIn("CANDIDATE", comparator.EXPECTED_EXTRACTOR_METHOD)
        self.assertEqual(
            comparator.EXPECTED_PARSER_VERSION,
            "V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION",
        )


if __name__ == "__main__":
    unittest.main()
