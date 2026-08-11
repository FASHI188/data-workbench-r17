from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"governance/stage3_s3g1j_v17_27_full_final.json"
RUNTIME=ROOT/"governance/stage3_s3g1j_runtime_manifest.json"
ACTIVATION=ROOT/"governance/stage3_workflow_activation_manifest.json"
RETIRED_WORKFLOW=ROOT/".github/workflows/stage3-s3g1j-v17-27-full-final-acceptance.yml"
EVIDENCE_CONTRACT=ROOT/".github/workflows/stage3-s3g1j-v17-27-evidence-contract.yml"
EVIDENCE_CONTRACT_NAME=".github/workflows/stage3-s3g1j-v17-27-evidence-contract.yml"


class V1727FullFinalEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls)->None:
        cls.evidence=json.loads(EVIDENCE.read_text(encoding="utf-8"))
        cls.runtime=json.loads(RUNTIME.read_text(encoding="utf-8"))
        cls.activation=json.loads(ACTIVATION.read_text(encoding="utf-8"))

    def test_machine_artifact_identity_is_frozen(self)->None:
        run=self.evidence["accepted_run"]
        self.assertEqual(run["run_id"],30806818977)
        self.assertEqual(run["head_sha"],"fa77d30a2ccdd3664beab01fd7ff7b5d16761726")
        self.assertEqual(run["artifact_id"],8854139999)
        self.assertEqual(run["artifact_digest"],"sha256:410e257d7a3ada353926970f806abc3e970e5638f55c1dec7b47c71c57777721")

    def test_full_basis_accounting_and_verdict_are_frozen(self)->None:
        result=self.evidence["full_basis_result"]
        self.assertTrue(result["execution_pass"])
        self.assertTrue(result["document_non_regression_pass"])
        self.assertTrue(result["numeric_non_regression_pass"])
        self.assertEqual(result["document_count"],121354)
        self.assertEqual(result["numeric_observation_count"],1051793)
        self.assertEqual(result["document_error_count"],1373)
        self.assertEqual(result["unresolved_tie_count"],1290)
        self.assertEqual(result["target_document_count"],5)
        self.assertEqual(result["target_numeric_rows"],15)
        self.assertEqual(result["unexpected_document_regression_count"],0)
        self.assertFalse(result["final_data_gate_pass"])
        self.assertEqual(result["final_data_verdict"],"FAIL_CLOSED")

    def test_exact_target_population_and_numeric_identity_are_frozen(self)->None:
        self.assertEqual(self.evidence["full_basis_result"]["changed_announcement_ids"],["1200907104","1201708762","1202195310","1202774611","1203358200"])
        numeric=self.evidence["numeric_non_regression"]
        expected="05b914b03dbcc23d3f6eca560189afbfe6ea427913f9cf1380fa09cdea6aa8d7"
        self.assertTrue(numeric["pass"])
        self.assertEqual(numeric["previous_existing_row_count"],1051778)
        self.assertEqual(numeric["current_existing_row_count"],1051778)
        self.assertEqual(numeric["previous_existing_semantic_sha256"],expected)
        self.assertEqual(numeric["current_existing_semantic_sha256"],expected)
        self.assertEqual(numeric["existing_numeric_value_drift"],0)

    def test_output_hashes_are_frozen(self)->None:
        hashes=self.evidence["output_hashes"]
        self.assertEqual(hashes["financial_values_gzip_sha256"],"4c518fbca2ece45ed535789d4cf66dd86d2717d6499f872234c5d3ece09280fe")
        self.assertEqual(hashes["financial_documents_gzip_sha256"],"c2abe07baaa76efb80a30cfdd4e762ad07814f6aa795a92b9c0504f7944ab99a")
        self.assertEqual(hashes["raw_audit_json_sha256"],"80809e9d9b24b365420849430eb5d61e261a15e790b56f29babf39ca2f914092")
        self.assertEqual(hashes["execution_json_sha256"],"5582eb95e86aa4e4e35a14fab9f4cf0aea5c6396dc023dbc47e115c99b11a7ec")

    def test_v17_27_is_historical_under_current_v17_30_runtime(self)->None:
        self.assertGreaterEqual(self.runtime["schema_version"],14)
        self.assertEqual(self.runtime["formal_runtime"]["runtime_generation"],"V17.30")
        latest=self.runtime["full_basis_last_completed_final"]
        self.assertEqual((latest["generation"],latest["run"]),("V17.29",31389854868))
        previous=self.runtime["previous_full_basis_final"]
        self.assertEqual((previous["generation"],previous["run"]),("V17.27",30806818977))
        self.assertEqual(previous["artifact_id"],8854139999)
        self.assertEqual(previous["document_error_count"],1373)
        self.assertEqual(previous["unresolved_tie_count"],1290)
        self.assertEqual(previous["verdict"],"FAIL_CLOSED")
        self.assertTrue(previous["retained"])
        self.assertGreaterEqual(self.activation["schema_version"],16)
        accepted=self.activation["accepted_v17_27_full_basis_evidence"]
        self.assertEqual(accepted["run"],30806818977)
        self.assertEqual(accepted["artifact_id"],8854139999)
        self.assertTrue(accepted["historical_full_basis_authority_retained"])
        self.assertFalse(accepted["last_completed_full_basis_authority"])
        current=self.activation["accepted_production_runtime"]
        self.assertEqual(current["generation"],"V17.30")
        self.assertTrue(current["full_basis_execution_pending"])
        self.assertEqual(current["last_completed_full_basis_generation"],"V17.29")
        self.assertEqual(current["data_verdict"],"FAIL_CLOSED")

    def test_one_shot_is_retired_and_long_lived_contract_remains(self)->None:
        retired=".github/workflows/stage3-s3g1j-v17-27-full-final-acceptance.yml"
        self.assertIn(retired,self.activation["removed_one_shot_workflows"])
        self.assertFalse(RETIRED_WORKFLOW.exists())
        self.assertIn(EVIDENCE_CONTRACT_NAME,self.activation["active_stage3_workflows"])
        self.assertTrue(EVIDENCE_CONTRACT.exists())
        boundaries=self.activation["hard_boundaries"]
        self.assertFalse(boundaries["v17_27_full_basis_execution_pending"])
        self.assertFalse(boundaries["v17_28_full_basis_execution_pending"])
        self.assertFalse(boundaries["v17_29_full_basis_execution_pending"])
        self.assertTrue(boundaries["v17_30_full_basis_execution_pending"])
        self.assertFalse(boundaries["v17_30_full_basis_execution_started"])
        self.assertEqual(boundaries["remaining_document_errors_last_completed_basis"],1364)
        self.assertEqual(boundaries["remaining_unresolved_ties_last_completed_basis"],1281)
        self.assertEqual(boundaries["stage3_status"],"NOT_READY")
        self.assertTrue(boundaries["stage4_alpha_live_locked"])
        self.assertFalse(boundaries["committed_production_data_changed"])
        self.assertFalse(boundaries["trained_model_changed"])
        self.assertFalse(boundaries["main_changed"])


if __name__=="__main__":unittest.main()
