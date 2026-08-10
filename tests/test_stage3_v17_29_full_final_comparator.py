from __future__ import annotations

import copy
import json
import unittest
from collections import Counter

import compare_stage3_s3g1j_v17_29_full_final as comparator


class V1729FullComparatorTests(unittest.TestCase):
    def test_top_level_document_error_order_is_semantic(self) -> None:
        left = json.dumps([
            {"concept": "B", "values": [["2", "20"]]},
            {"concept": "A", "values": [["1", "10"]]},
        ], ensure_ascii=False)
        right = json.dumps([
            {"concept": "A", "values": [["1", "10"]]},
            {"concept": "B", "values": [["2", "20"]]},
        ], ensure_ascii=False)
        self.assertEqual(
            comparator.v28.v27.canonical_document_error(left),
            comparator.v28.v27.canonical_document_error(right),
        )

    def test_nested_evidence_order_remains_strict(self) -> None:
        left = json.dumps([{"concept": "A", "values": [["1", "10"], ["2", "20"]]}])
        right = json.dumps([{"concept": "A", "values": [["2", "20"], ["1", "10"]]}])
        self.assertNotEqual(
            comparator.v28.v27.canonical_document_error(left),
            comparator.v28.v27.canonical_document_error(right),
        )

    def test_candidate_evidence_array_order_remains_strict(self) -> None:
        left = {field: "" for field in comparator.v28.v27.v1.DOC_FIELDS}
        right = copy.deepcopy(left)
        left["candidate_evidence_json"] = json.dumps([{"id": "1"}, {"id": "2"}])
        right["candidate_evidence_json"] = json.dumps([{"id": "2"}, {"id": "1"}])
        self.assertNotEqual(comparator.canon(left), comparator.canon(right))

    def test_numeric_semantic_hash_detects_stable_field_drift(self) -> None:
        fields = comparator.v28.v27.v1.STABLE_NUMERIC_FIELDS
        row = {field: field for field in fields}
        changed = dict(row)
        changed["normalized_cny_value"] = "changed"
        original_counter = Counter([comparator.numtuple(row)])
        changed_counter = Counter([comparator.numtuple(changed)])
        self.assertNotEqual(original_counter, changed_counter)
        self.assertNotEqual(
            comparator.semsha(original_counter),
            comparator.semsha(changed_counter),
        )

    def test_generation_metadata_is_excluded_from_stable_numeric_identity(self) -> None:
        fields = comparator.v28.v27.v1.STABLE_NUMERIC_FIELDS
        self.assertNotIn("extraction_method", fields)
        self.assertNotIn("methodology_version", fields)
        self.assertEqual(
            set(comparator.v28.v27.v1.EXCLUDED_GENERATION_FIELDS),
            {"extraction_method", "methodology_version"},
        )

    def test_exact_seven_target_scope_is_frozen(self) -> None:
        self.assertEqual(
            set(comparator.TARGETS),
            {
                "1215186538", "1219426855", "1219792633", "1219840508",
                "1219879687", "1220087244", "1221006100",
            },
        )
        self.assertEqual(
            comparator.TARGETS["1215186538"],
            ("c1856e15d16e6ede5f22a7a0c97dcfd540185573725b64861d8015fae1b4b920", "2711641", "2022-06-30", 132),
        )
        self.assertEqual(
            comparator.TARGETS["1221006100"],
            ("8679311bb2eb42e00d575404456fc5f0fb1a84d0ecab0ae3f6572b7962a1d806", "3650480", "2024-06-30", 204),
        )

    def test_production_identity_is_not_candidate_or_experiment_identity(self) -> None:
        self.assertEqual(comparator.EXPECTED_METHODOLOGY, "V3.3.13-V17.29")
        self.assertEqual(
            comparator.EXPECTED_PARSER_VERSION,
            "V17_29_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION",
        )
        self.assertIn("PRODUCTION", comparator.EXPECTED_EXTRACTOR_METHOD)
        self.assertNotIn("CANDIDATE", comparator.EXPECTED_EXTRACTOR_METHOD)
        self.assertNotIn("EXPERIMENT", comparator.EXPECTED_EXTRACTOR_METHOD)


if __name__ == "__main__":
    unittest.main()
