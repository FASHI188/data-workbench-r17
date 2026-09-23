from __future__ import annotations

import unittest

import diagnose_stage3_s3g1j_v17_26_p0 as diagnostic


class V1726P0DiagnosticTests(unittest.TestCase):
    def test_exact_current_population_is_frozen(self) -> None:
        self.assertEqual(len(diagnostic.EXPECTED_IDS), 21)
        self.assertEqual(len(set(diagnostic.EXPECTED_IDS)), 21)
        self.assertNotIn("1207035181", diagnostic.EXPECTED_IDS)
        self.assertNotIn("1221568845", diagnostic.EXPECTED_IDS)
        self.assertEqual(
            diagnostic.EXPECTED_SIGNATURE_COUNTS,
            {
                diagnostic.ALL_MISSING: 10,
                diagnostic.EQUITY_MISSING: 11,
            },
        )
        self.assertEqual(sum(diagnostic.EXPECTED_SIGNATURE_COUNTS.values()), 21)

    def test_generic_witness_population_is_exact(self) -> None:
        self.assertEqual(
            diagnostic.EXPECTED_GENERIC_PROMOTED_IDS,
            (
                "1200907104",
                "1201708762",
                "1202195310",
                "1202774611",
                "1203358200",
                "1204077386",
                "1205543437",
            ),
        )
        self.assertTrue(
            set(diagnostic.EXPECTED_GENERIC_PROMOTED_IDS).issubset(
                set(diagnostic.EXPECTED_IDS)
            )
        )

    def test_next_gate_is_fail_closed(self) -> None:
        self.assertEqual(
            diagnostic.next_gate(diagnostic.ALL_MISSING, 1),
            "GENERIC_GROUP_WITNESS_PRESENT_BUT_DOWNSTREAM_GATE_FAILED",
        )
        self.assertEqual(
            diagnostic.next_gate(diagnostic.ALL_MISSING, 0),
            "NO_FORMAL_SPATIAL_ALE_CANDIDATES_AFTER_ACCEPTED_ROLE_BINDING",
        )
        self.assertEqual(
            diagnostic.next_gate(diagnostic.EQUITY_MISSING, 0),
            "GROUP_ASSET_LIABILITY_PRESENT_BUT_GROUP_EQUITY_MISSING",
        )
        self.assertEqual(
            diagnostic.next_gate("UNKNOWN", 0), "UNCLASSIFIED_FAIL_CLOSED"
        )

    def test_source_artifact_identities_are_frozen(self) -> None:
        self.assertEqual(diagnostic.SOURCE_CLASSIFIER_RUN, 30734063100)
        self.assertEqual(diagnostic.SOURCE_FULL_RUN, 30733013665)
        self.assertEqual(
            diagnostic.P0_GZIP_SHA256,
            "75f41b4576fc843b93bca6ac98f12a12e72475daaa0f00473e2a6edae5fdcf90",
        )
        self.assertEqual(
            diagnostic.DOCUMENTS_GZIP_SHA256,
            "891d6e10b92e13e3aea604ab9e22bd8dd0ea66764cc485a68abdc50eb8742d68",
        )


if __name__ == "__main__":
    unittest.main()
