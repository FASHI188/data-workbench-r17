from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_26_full_final.json"
ACTIVATION = ROOT / "governance/stage3_workflow_activation_manifest.json"
RETIRED_WORKFLOW = (
    ROOT / ".github/workflows/stage3-s3g1j-v17-25-full-final-v2.yml"
)
EVIDENCE_CONTRACT = (
    ROOT / ".github/workflows/stage3-s3g1j-v17-26-evidence-contract.yml"
)
EVIDENCE_CONTRACT_NAME = (
    ".github/workflows/stage3-s3g1j-v17-26-evidence-contract.yml"
)


class V1726FullFinalEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        cls.activation = json.loads(ACTIVATION.read_text(encoding="utf-8"))

    def test_machine_artifact_identity_is_frozen(self) -> None:
        run = self.evidence["accepted_run"]
        self.assertEqual(run["run_id"], 30733013665)
        self.assertEqual(
            run["head_sha"], "ed81a8f167c7b158167a8bdafa1799b7047666af"
        )
        self.assertEqual(run["conclusion"], "SUCCESS")
        self.assertEqual(run["artifact_id"], 8828600783)
        self.assertEqual(
            run["artifact_digest"],
            "sha256:7f2e707e9192af527ff0444b48caf6bebfbfa1ef7559ec2810b6f47b1790567b",
        )

    def test_full_basis_accounting_and_verdict_are_frozen(self) -> None:
        result = self.evidence["full_basis_result"]
        self.assertEqual(result["canonical_version_count"], 121354)
        self.assertEqual(result["document_count"], 121354)
        self.assertEqual(result["numeric_observation_count"], 1051778)
        self.assertEqual(result["document_error_count"], 1378)
        self.assertEqual(result["unresolved_tie_count"], 1295)
        self.assertEqual(
            result["changed_announcement_ids"], ["1207035181", "1221568845"]
        )
        self.assertEqual(result["unexpected_document_regression_count"], 0)
        self.assertIs(result["final_data_gate_pass"], False)
        self.assertEqual(result["final_data_verdict"], "FAIL_CLOSED")

    def test_target_scope_is_exactly_balance_sheet_totals(self) -> None:
        repair = self.evidence["exact_source_scope_repair"]
        self.assertIs(repair["candidate_resolver_reused"], False)
        self.assertIs(repair["selected_source_lock_pass"], True)
        self.assertIs(repair["non_balance_target_concepts_promoted"], False)
        self.assertEqual(
            repair["allowed_concepts"],
            ["TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"],
        )
        self.assertEqual(set(repair["targets"]), {"1207035181", "1221568845"})
        self.assertTrue(
            all(target["numeric_observations"] == 3 for target in repair["targets"].values())
        )

    def test_non_target_semantic_hash_is_unchanged(self) -> None:
        numeric = self.evidence["numeric_non_regression"]
        expected = "f9f7751943b113db9488b0b7b1d33ffbd93e1e3eb56486ca8e399f252a5953b4"
        self.assertIs(numeric["pass"], True)
        self.assertEqual(numeric["previous_non_target_row_count"], 1051772)
        self.assertEqual(numeric["current_non_target_row_count"], 1051772)
        self.assertEqual(numeric["previous_non_target_semantic_sha256"], expected)
        self.assertEqual(numeric["current_non_target_semantic_sha256"], expected)
        self.assertEqual(numeric["non_target_value_drift"], 0)

    def test_activation_manifest_retains_v17_26_after_v17_27_promotion(self) -> None:
        self.assertEqual(self.activation["schema_version"], 10)
        accepted = self.activation["accepted_v17_26_full_basis_evidence"]
        self.assertEqual(accepted["run"], 30733013665)
        self.assertEqual(accepted["final_data_verdict"], "FAIL_CLOSED")
        self.assertEqual(accepted["stage3_status"], "NOT_READY")
        self.assertIs(accepted["historical_full_basis_authority_retained"], True)
        self.assertIs(accepted["one_shot_workflow_retired_after_acceptance"], True)
        self.assertIs(accepted["evidence_contract_active"], True)
        self.assertEqual(
            accepted["evidence_contract_workflow"], EVIDENCE_CONTRACT_NAME
        )
        self.assertIn(EVIDENCE_CONTRACT_NAME, self.activation["active_stage3_workflows"])
        self.assertTrue(EVIDENCE_CONTRACT.exists())
        self.assertIn(
            ".github/workflows/stage3-s3g1j-v17-25-full-final-v2.yml",
            self.activation["removed_one_shot_workflows"],
        )
        self.assertFalse(RETIRED_WORKFLOW.exists())
        runtime = self.activation["accepted_production_runtime"]
        self.assertEqual(runtime["generation"], "V17.27")
        self.assertIs(runtime["full_basis_execution_pending"], True)
        self.assertEqual(runtime["last_completed_full_basis_generation"], "V17.26")
        self.assertEqual(runtime["last_completed_full_basis_run"], 30733013665)
        self.assertEqual(runtime["data_verdict"], "FAIL_CLOSED")
        classification = self.activation["accepted_v17_26_residual_classification"]
        self.assertIs(classification["diagnostic_only"], True)
        self.assertIs(classification["runtime_authority_changed"], False)
        boundaries = self.activation["hard_boundaries"]
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["committed_production_data_changed"], False)
        self.assertIs(boundaries["trained_model_changed"], False)
        self.assertIs(boundaries["main_changed"], False)


if __name__ == "__main__":
    unittest.main()
