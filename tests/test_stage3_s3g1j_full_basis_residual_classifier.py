from __future__ import annotations

import unittest

from scripts import classify_stage3_s3g1j_full_basis_residuals as classifier


class FullBasisResidualClassifierTests(unittest.TestCase):
    def row(self, error: str = "", tie: str = "TIE_SOURCE_INCOMPLETE") -> dict:
        return {
            "announcement_id": "1",
            "document_error": error,
            "tie_resolution": tie,
        }

    def candidate(self, tier2: int, errors: list[str]) -> dict:
        return {"tier2_found": tier2, "validation_errors": errors}

    def test_safe_near_complete_is_separate_from_identity_conflict(self):
        safe = [self.candidate(3, [classifier.NO_BLOCK])]
        conflict = [
            self.candidate(
                3,
                [classifier.NO_BLOCK, classifier.IDENTITY + " rel=0.2"],
            )
        ]
        self.assertEqual(
            classifier.classify(self.row(), safe),
            (
                "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3",
                "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT",
            ),
        )
        self.assertEqual(
            classifier.classify(self.row(), conflict),
            (
                "SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_3",
                "P1_IDENTITY_CONFLICT_TIER2_3",
            ),
        )

    def test_issuer_mismatch_has_authority_priority(self):
        result = classifier.classify(
            self.row("PDF_DECLARES_OTHER_A_SHARE_ISSUER:['1'] EXPECTED:['2']"),
            [self.candidate(0, [])],
        )
        self.assertEqual(
            result,
            ("CANONICAL_PDF_ISSUER_MISMATCH", "P4_ISSUER_AUTHORITY_REVIEW"),
        )

    def test_multi_candidate_classes_follow_tie_resolution(self):
        candidates = [self.candidate(0, []), self.candidate(1, [])]
        self.assertEqual(
            classifier.classify(self.row(tie="TIE_VALUE_CONFLICT"), candidates),
            (
                "MULTI_CANDIDATE_VALUE_CONFLICT",
                "P4_SOURCE_VALUE_CONFLICT_REVIEW",
            ),
        )
        self.assertEqual(
            classifier.classify(self.row(tie="TIE_SOURCE_INCOMPLETE"), candidates),
            (
                "MULTI_CANDIDATE_SOURCE_INCOMPLETE_2_CANDIDATES",
                "P3_SOURCE_COMPLETENESS_REVIEW",
            ),
        )

    def test_unknown_single_candidate_error_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown validation errors"):
            classifier.classify(
                self.row(),
                [self.candidate(1, ["UNKNOWN_ERROR"])],
            )


if __name__ == "__main__":
    unittest.main()
