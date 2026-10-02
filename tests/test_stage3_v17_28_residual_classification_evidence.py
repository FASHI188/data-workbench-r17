from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_28_residual_classification.json"


class V1728ResidualClassificationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_exact_run_and_artifact_identity(self) -> None:
        run = self.evidence["accepted_run"]
        self.assertEqual(run["run_id"], 31022605702)
        self.assertEqual(run["head_sha"], "b997f7b91cb2a5fcbb5d8473f428effd26ed5bf0")
        self.assertEqual(run["artifact_id"], 8937238672)
        self.assertEqual(
            run["artifact_digest"],
            "sha256:2c54496b329b719c09f299fe0c2d61ece4b05a0c8859b4a39441012abfb248ad",
        )
        self.assertEqual(run["conclusion"], "SUCCESS")

    def test_exact_classification_and_p0_population(self) -> None:
        result = self.evidence["classification_result"]
        self.assertEqual(result["input_document_rows"], 121354)
        self.assertEqual(result["pass_document_rows"], 119983)
        self.assertEqual(result["residual_document_rows"], 1371)
        self.assertEqual(sum(result["class_counts"].values()), 1371)
        self.assertEqual(sum(result["priority_counts"].values()), 1371)
        self.assertEqual(result["p0_safe_near_complete_count"], 14)
        self.assertEqual(len(result["p0_announcement_ids"]), 14)
        self.assertEqual(len(set(result["p0_announcement_ids"])), 14)
        self.assertEqual(
            result["unresolved_tie_taxonomy"],
            {"TIE_SOURCE_INCOMPLETE": 1274, "TIE_VALUE_CONFLICT": 14},
        )

    def test_migration_has_only_seven_recovered_exits(self) -> None:
        migration = self.evidence["migration_from_v17_26"]
        self.assertEqual(migration["previous_residual_rows"], 1378)
        self.assertEqual(migration["current_residual_rows"], 1371)
        self.assertEqual(migration["unchanged_common_residuals"], 1371)
        self.assertEqual(migration["recovered_exit_count"], 7)
        self.assertEqual(migration["new_residual_count"], 0)
        self.assertEqual(migration["common_residual_reclassification_count"], 0)
        self.assertIs(migration["all_recovered_exits_were_prior_p0_safe_near_complete"], True)
        self.assertIs(migration["all_other_residual_classes_and_priorities_unchanged"], True)

    def test_output_hashes_and_independent_verification_are_frozen(self) -> None:
        hashes = self.evidence["output_hashes"]
        self.assertEqual(
            hashes["classification_ledger_gzip_sha256"],
            "d1d1c40cf242e93f0a5c8f18eb7335b15238bbf780429cd3e086eb7efe0765cc",
        )
        self.assertEqual(
            hashes["p0_ledger_gzip_sha256"],
            "dc6cc9b10482406121e66772c38bf13e745e00ab0a80f4e324ccf9bb897bd922",
        )
        self.assertEqual(
            hashes["migration_ledger_gzip_sha256"],
            "2915b4b3d039a8e96a6cdbd60ced928b1e209c24a287ddeddb0353dce39fe114",
        )
        verification = self.evidence["independent_verification"]
        self.assertIs(verification["artifact_downloaded_and_inspected"], True)
        self.assertIs(verification["machine_outputs_byte_equal_local_read_only_reproduction"], True)
        self.assertEqual(verification["errors"], [])

    def test_diagnostic_does_not_change_authority(self) -> None:
        boundaries = self.evidence["hard_boundaries"]
        self.assertIs(boundaries["diagnostic_only"], True)
        self.assertIs(boundaries["formal_parser_changed"], False)
        self.assertIs(boundaries["runtime_authority_changed"], False)
        self.assertIs(boundaries["production_data_changed"], False)
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["main_changed"], False)
        self.assertIs(boundaries["merge_to_main_authorized"], False)


if __name__ == "__main__":
    unittest.main()
