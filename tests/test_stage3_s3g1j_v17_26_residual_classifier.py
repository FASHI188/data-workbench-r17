from __future__ import annotations

import unittest

import classify_stage3_s3g1j_v17_26_residuals as classifier


class V1726ResidualClassifierTests(unittest.TestCase):
    def row(self, **updates):
        base = {
            "announcement_id": "1",
            "document_error": "NO_VALIDATED_BALANCE_SHEET_BLOCK",
            "tie_resolution": "UNIQUE_CANONICAL",
        }
        base.update(updates)
        return base

    def candidate(self, tier2: int, errors: list[str]):
        return {"tier2_found": tier2, "validation_errors": errors}

    def test_issuer_mismatch_has_authority_priority(self) -> None:
        result = classifier.classify(
            self.row(document_error="PDF_DECLARES_OTHER_A_SHARE_ISSUER: 600000"),
            [self.candidate(0, [classifier.NO_BLOCK])],
        )
        self.assertEqual(
            result,
            ("CANONICAL_PDF_ISSUER_MISMATCH", "P4_ISSUER_AUTHORITY_REVIEW"),
        )

    def test_single_tier2_three_without_identity_conflict_is_p0(self) -> None:
        result = classifier.classify(
            self.row(), [self.candidate(3, [classifier.NO_BLOCK])]
        )
        self.assertEqual(
            result,
            (
                "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3",
                "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT",
            ),
        )

    def test_identity_conflicts_remain_outside_safe_recovery(self) -> None:
        tier3 = classifier.classify(
            self.row(), [self.candidate(3, [classifier.IDENTITY])]
        )
        tier2 = classifier.classify(
            self.row(), [self.candidate(2, [classifier.IDENTITY])]
        )
        self.assertEqual(
            tier3,
            (
                "SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_3",
                "P1_IDENTITY_CONFLICT_TIER2_3",
            ),
        )
        self.assertEqual(
            tier2,
            (
                "SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_2",
                "P3_IDENTITY_CONFLICT_LOWER_EVIDENCE",
            ),
        )

    def test_multi_candidate_classes_preserve_resolution(self) -> None:
        candidates = [self.candidate(0, []), self.candidate(0, [])]
        incomplete = classifier.classify(
            self.row(tie_resolution="TIE_SOURCE_INCOMPLETE"), candidates
        )
        conflict = classifier.classify(
            self.row(tie_resolution="TIE_VALUE_CONFLICT"), candidates
        )
        self.assertEqual(
            incomplete,
            (
                "MULTI_CANDIDATE_SOURCE_INCOMPLETE_2_CANDIDATES",
                "P3_SOURCE_COMPLETENESS_REVIEW",
            ),
        )
        self.assertEqual(
            conflict,
            (
                "MULTI_CANDIDATE_VALUE_CONFLICT",
                "P4_SOURCE_VALUE_CONFLICT_REVIEW",
            ),
        )

    def test_unknown_validation_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown validation errors"):
            classifier.classify(
                self.row(), [self.candidate(2, ["UNRECOGNIZED_VALIDATION"])]
            )

    def test_current_accounting_constants_are_exact(self) -> None:
        self.assertEqual(sum(classifier.EXPECTED_CLASS_COUNTS.values()), 1378)
        self.assertEqual(sum(classifier.EXPECTED_PRIORITY_COUNTS.values()), 1378)
        self.assertEqual(
            classifier.EXPECTED_CLASS_COUNTS[
                "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3"
            ],
            21,
        )
        self.assertEqual(
            classifier.RECOVERED_EXIT_IDS, ("1207035181", "1221568845")
        )
        self.assertEqual(classifier.SOURCE_RUN, 30733013665)
        self.assertEqual(classifier.PREVIOUS_CLASSIFIER_RUN, 30687393120)


if __name__ == "__main__":
    unittest.main()
