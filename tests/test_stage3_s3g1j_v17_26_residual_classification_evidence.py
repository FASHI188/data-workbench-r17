from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_26_residual_classification.json"
ACTIVATION = ROOT / "governance/stage3_workflow_activation_manifest.json"
ONE_SHOT = ROOT / ".github/workflows/stage3-s3g1j-v17-26-residual-classifier.yml"
LONG_LIVED_CONTRACT = ROOT / ".github/workflows/stage3-s3g1j-v17-26-evidence-contract.yml"


class V1726ResidualClassificationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        cls.activation = json.loads(ACTIVATION.read_text(encoding="utf-8"))

    def test_machine_artifact_identity_is_frozen(self) -> None:
        run = self.evidence["accepted_run"]
        self.assertEqual(run["run_id"], 30734063100)
        self.assertEqual(run["head_sha"], "d9dc3119cc710a46174fb9d5ce9a6f1518ea5c50")
        self.assertEqual(run["conclusion"], "SUCCESS")
        self.assertEqual(run["artifact_id"], 8828913247)
        self.assertEqual(run["artifact_digest"], "sha256:f667e5e494e6ac1456a370b5dab47677b4925d0466beedceec3e47bdeb5f16a5")

    def test_current_accounting_and_p0_population_are_exact(self) -> None:
        current = self.evidence["current_accounting"]
        self.assertEqual(current["input_document_rows"], 121354)
        self.assertEqual(current["pass_document_rows"], 119976)
        self.assertEqual(current["residual_document_rows"], 1378)
        self.assertEqual(sum(current["class_counts"].values()), 1378)
        self.assertEqual(sum(current["priority_counts"].values()), 1378)
        self.assertEqual(current["p0_safe_near_complete_count"], 21)
        self.assertEqual(current["class_counts"]["SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3"], 21)

    def test_migration_is_only_two_recovered_exits(self) -> None:
        migration = self.evidence["migration_from_v17_21_classifier"]
        self.assertEqual(migration["previous_residual_rows"], 1380)
        self.assertEqual(migration["current_residual_rows"], 1378)
        self.assertEqual(migration["unchanged_common_residuals"], 1378)
        self.assertEqual(migration["common_residual_reclassification_count"], 0)
        self.assertEqual(migration["new_residual_count"], 0)
        self.assertEqual(migration["recovered_exit_count"], 2)
        self.assertEqual(migration["recovered_exit_announcement_ids"], ["1207035181", "1221568845"])
        self.assertEqual(migration["p0_count_change"], "23_TO_21")
        self.assertIs(migration["all_other_class_counts_unchanged"], True)

    def test_output_hashes_are_frozen(self) -> None:
        hashes = self.evidence["output_hashes"]
        expected = {
            "classification_ledger_plaintext_sha256": "d685467918213b5b5b333dd7f893d633aebce9dd0d7d738082241e74a3519009",
            "classification_ledger_gzip_sha256": "e39fdc8dea8639bf00d56f80a00cfba842c6194a787736bdcf40b2ab1accea89",
            "p0_ledger_plaintext_sha256": "3500694439fc4573b1546c001b647ecb0bee6804691df8306727255debbeef49",
            "p0_ledger_gzip_sha256": "75f41b4576fc843b93bca6ac98f12a12e72475daaa0f00473e2a6edae5fdcf90",
            "migration_ledger_plaintext_sha256": "275e8a25490d324bfe69e76e9945f5193199697f5661e3555aa3ed8c305319f4",
            "migration_ledger_gzip_sha256": "88fc642649f2c6448edcc9d5b8ae09753042b4b5086b43ca9af8677aabf7aa38",
        }
        for key, value in expected.items():
            self.assertEqual(hashes[key], value)
        self.assertEqual(hashes["gzip_mtime"], 0)
        self.assertEqual(hashes["gzip_embedded_filename"], "")

    def test_activation_retains_diagnostic_without_rewriting_history(self) -> None:
        self.assertEqual(self.activation["schema_version"], 15)
        accepted = self.activation["accepted_v17_26_residual_classification"]
        self.assertEqual(accepted["run"], 30734063100)
        self.assertEqual(accepted["artifact_id"], 8828913247)
        self.assertEqual(accepted["residual_document_rows"], 1378)
        self.assertEqual(accepted["p0_safe_near_complete_count"], 21)
        self.assertIs(accepted["diagnostic_only"], True)
        self.assertIs(accepted["parser_changed"], False)
        self.assertIs(accepted["runtime_authority_changed"], False)
        self.assertIs(accepted["one_shot_workflow_retired_after_acceptance"], True)
        self.assertIs(accepted["evidence_contract_active"], True)
        self.assertFalse(ONE_SHOT.exists())
        self.assertTrue(LONG_LIVED_CONTRACT.exists())
        self.assertIn(".github/workflows/stage3-s3g1j-v17-26-residual-classifier.yml", self.activation["removed_one_shot_workflows"])

        runtime = self.activation["accepted_production_runtime"]
        self.assertEqual(runtime["generation"], "V17.29")
        self.assertIs(runtime["full_basis_execution_pending"], False)
        self.assertEqual(runtime["last_completed_full_basis_generation"], "V17.29")
        self.assertEqual(runtime["last_completed_full_basis_run"], 31389854868)
        self.assertEqual(runtime["last_completed_document_error_count"], 1364)
        self.assertEqual(runtime["last_completed_unresolved_tie_count"], 1281)
        self.assertEqual(runtime["execution_verdict"], "PASS")
        self.assertEqual(runtime["data_verdict"], "FAIL_CLOSED")

        historical = self.activation["accepted_v17_26_full_basis_evidence"]
        self.assertEqual(historical["run"], 30733013665)
        self.assertEqual(historical["document_error_count"], 1378)
        self.assertIs(historical["historical_full_basis_authority_retained"], True)
        boundaries = self.activation["hard_boundaries"]
        self.assertIs(boundaries["v17_29_full_basis_execution_pending"], False)
        self.assertEqual(boundaries["remaining_document_errors"], 1364)
        self.assertEqual(boundaries["remaining_unresolved_ties"], 1281)
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["committed_production_data_changed"], False)
        self.assertIs(boundaries["trained_model_changed"], False)
        self.assertIs(boundaries["main_changed"], False)


if __name__ == "__main__":
    unittest.main()
