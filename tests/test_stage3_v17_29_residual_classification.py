from __future__ import annotations

import unittest

import classify_stage3_s3g1j_v17_29_residuals as c


def row(error: str = "", tie: str = "TIE_SOURCE_INCOMPLETE", aid: str = "x") -> dict:
    return {"document_error": error, "tie_resolution": tie, "announcement_id": aid}


def candidate(tier2: int, errors: list[str]) -> dict:
    return {"tier2_found": tier2, "validation_errors": errors}


class V1729ResidualClassificationTests(unittest.TestCase):
    def test_frozen_source_and_previous_identities(self) -> None:
        self.assertEqual(c.SOURCE_RUN, 31389854868)
        self.assertEqual(c.SOURCE_ARTIFACT_ID, 9063271903)
        self.assertEqual(c.PREVIOUS_CLASSIFIER_RUN, 31022605702)
        self.assertEqual(c.PREVIOUS_CLASSIFIER_ARTIFACT_ID, 8937238672)
        self.assertEqual(len(c.RECOVERED_EXIT_IDS), 7)
        self.assertEqual(len(c.EXPECTED_P0_IDS), 7)

    def test_single_canonical_no_block_tier3_is_p0(self) -> None:
        actual = c.classify(row(), [candidate(3, [c.NO_BLOCK])])
        self.assertEqual(actual, (
            "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3",
            "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT",
        ))

    def test_identity_conflict_never_enters_p0(self) -> None:
        actual = c.classify(row(), [candidate(3, [c.NO_BLOCK, c.IDENTITY])])
        self.assertEqual(actual, (
            "SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_3",
            "P1_IDENTITY_CONFLICT_TIER2_3",
        ))

    def test_partial_tier2_stays_p2(self) -> None:
        actual = c.classify(row(), [candidate(2, [c.NO_BLOCK])])
        self.assertEqual(actual, (
            "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_2",
            "P2_SAFE_PARTIAL_TIER2_2",
        ))

    def test_issuer_mismatch_has_priority_over_candidate_shape(self) -> None:
        actual = c.classify(row(c.ISSUER_PREFIX + ":expected=1"), [candidate(3, [c.NO_BLOCK])])
        self.assertEqual(actual, ("CANONICAL_PDF_ISSUER_MISMATCH", "P4_ISSUER_AUTHORITY_REVIEW"))

    def test_multi_candidate_source_and_value_conflicts_are_separate(self) -> None:
        two = [candidate(0, [c.NO_BLOCK]), candidate(0, [c.NO_BLOCK])]
        self.assertEqual(c.classify(row(tie="TIE_SOURCE_INCOMPLETE"), two), (
            "MULTI_CANDIDATE_SOURCE_INCOMPLETE_2_CANDIDATES", "P3_SOURCE_COMPLETENESS_REVIEW"
        ))
        self.assertEqual(c.classify(row(tie="TIE_VALUE_CONFLICT"), two), (
            "MULTI_CANDIDATE_VALUE_CONFLICT", "P4_SOURCE_VALUE_CONFLICT_REVIEW"
        ))

    def test_unknown_single_candidate_error_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            c.classify(row(), [candidate(3, ["UNKNOWN_FAILURE"])])

    def test_expected_counts_close_exactly(self) -> None:
        self.assertEqual(sum(c.EXPECTED_CLASS_COUNTS.values()), 1364)
        self.assertEqual(sum(c.EXPECTED_PRIORITY_COUNTS.values()), 1364)
        self.assertEqual(c.EXPECTED_TIE_TAXONOMY, {"TIE_SOURCE_INCOMPLETE": 1267, "TIE_VALUE_CONFLICT": 14})


if __name__ == "__main__":
    unittest.main()
