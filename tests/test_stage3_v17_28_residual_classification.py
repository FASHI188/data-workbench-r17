from __future__ import annotations

import unittest

import classify_stage3_s3g1j_v17_28_residuals as classifier


def row(**kwargs):
    base = {
        "announcement_id": "x",
        "document_error": "NO_VALIDATED_BALANCE_SHEET_BLOCK",
        "tie_resolution": "SINGLE_CANONICAL",
    }
    base.update(kwargs)
    return base


def candidate(tier2: int, errors: list[str]) -> dict:
    return {
        "id": "x",
        "tier1_found": 0,
        "tier2_found": tier2,
        "page_count": 10,
        "validation_errors": errors,
    }


class V1728ResidualClassificationTests(unittest.TestCase):
    def test_safe_near_complete_requires_single_tier2_three_without_identity_error(self) -> None:
        actual = classifier.classify(row(), [candidate(3, [classifier.NO_BLOCK])])
        self.assertEqual(
            actual,
            (
                "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3",
                "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT",
            ),
        )

    def test_identity_conflict_never_enters_p0(self) -> None:
        actual = classifier.classify(
            row(), [candidate(3, [classifier.IDENTITY, classifier.NO_BLOCK])]
        )
        self.assertEqual(
            actual,
            (
                "SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_3",
                "P1_IDENTITY_CONFLICT_TIER2_3",
            ),
        )

    def test_source_incomplete_and_value_conflict_remain_separate(self) -> None:
        candidates = [
            candidate(0, [classifier.NO_BLOCK]),
            candidate(0, [classifier.NO_BLOCK]),
        ]
        self.assertEqual(
            classifier.classify(row(tie_resolution="TIE_SOURCE_INCOMPLETE"), candidates),
            (
                "MULTI_CANDIDATE_SOURCE_INCOMPLETE_2_CANDIDATES",
                "P3_SOURCE_COMPLETENESS_REVIEW",
            ),
        )
        self.assertEqual(
            classifier.classify(row(tie_resolution="TIE_VALUE_CONFLICT"), candidates),
            (
                "MULTI_CANDIDATE_VALUE_CONFLICT",
                "P4_SOURCE_VALUE_CONFLICT_REVIEW",
            ),
        )

    def test_issuer_mismatch_has_priority_over_candidate_shape(self) -> None:
        actual = classifier.classify(
            row(document_error=classifier.ISSUER_PREFIX + ":000001"), []
        )
        self.assertEqual(
            actual,
            ("CANONICAL_PDF_ISSUER_MISMATCH", "P4_ISSUER_AUTHORITY_REVIEW"),
        )

    def test_unknown_single_candidate_validation_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            classifier.classify(row(), [candidate(3, ["UNKNOWN_VALIDATION"])])

    def test_exact_population_and_migration_constants_are_frozen(self) -> None:
        self.assertEqual(sum(classifier.EXPECTED_CLASS_COUNTS.values()), 1371)
        self.assertEqual(sum(classifier.EXPECTED_PRIORITY_COUNTS.values()), 1371)
        self.assertEqual(
            classifier.EXPECTED_TIE_TAXONOMY,
            {"TIE_SOURCE_INCOMPLETE": 1274, "TIE_VALUE_CONFLICT": 14},
        )
        self.assertEqual(len(classifier.EXPECTED_P0_IDS), 14)
        self.assertEqual(len(set(classifier.EXPECTED_P0_IDS)), 14)
        self.assertEqual(len(classifier.RECOVERED_EXIT_IDS), 7)
        self.assertTrue(
            set(classifier.RECOVERED_EXIT_IDS).isdisjoint(classifier.EXPECTED_P0_IDS)
        )
        self.assertEqual(classifier.SOURCE_RUN, 30997260730)
        self.assertEqual(classifier.SOURCE_ARTIFACT_ID, 8927455692)
        self.assertEqual(classifier.PREVIOUS_CLASSIFIER_RUN, 30734063100)
        self.assertEqual(classifier.PREVIOUS_CLASSIFIER_ARTIFACT_ID, 8828913247)


if __name__ == "__main__":
    unittest.main()
