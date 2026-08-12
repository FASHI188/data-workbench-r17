from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class V1730AuthorityStateTest(unittest.TestCase):
    def load(self, path: str) -> dict:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))

    def test_v17_30_is_latest_raw_basis_with_formal_retained_residual_closure(self) -> None:
        runtime = self.load("governance/stage3_s3g1j_runtime_manifest.json")
        activation = self.load("governance/stage3_workflow_activation_manifest.json")
        authority = self.load("governance/stage3_authority_map.json")
        retention = self.load("governance/stage3_s3g1j_v17_30_residual_retention.json")
        lock = self.load("config/stage3_final_lock.json")
        project = self.load("data/project_status.json")

        self.assertEqual(runtime["schema_version"], 15)
        self.assertEqual(runtime["current_production_authority"]["generation"], "V17.30")
        self.assertEqual(runtime["formal_runtime"]["runtime_generation"], "V17.30")
        latest = runtime["full_basis_last_completed_final"]
        self.assertEqual((latest["generation"], latest["run"]), ("V17.30", 31518370789))
        self.assertEqual(latest["artifact_id"], 9112098872)
        self.assertEqual(latest["numeric_observations"], 1051826)
        self.assertEqual(latest["document_error_count"], 1362)
        self.assertEqual(latest["unresolved_tie_count"], 1279)
        self.assertEqual(latest["verdict"], "FAIL_CLOSED")
        previous = runtime["previous_last_completed_full_basis_final"]
        self.assertEqual((previous["generation"], previous["run"]), ("V17.29", 31389854868))
        nxt = runtime["next_full_basis_required"]
        self.assertIsNone(nxt["generation"])
        self.assertEqual(nxt["status"], "NONE_CURRENT_RUNTIME_ACCEPTED")

        self.assertGreaterEqual(activation["schema_version"], 17)
        active = activation["accepted_production_runtime"]
        self.assertEqual(active["generation"], "V17.30")
        self.assertFalse(active["full_basis_execution_pending"])
        self.assertEqual(active["last_completed_full_basis_generation"], "V17.30")
        self.assertEqual(active["last_completed_full_basis_run"], 31518370789)
        self.assertEqual(active["last_completed_numeric_observation_count"], 1051826)
        self.assertEqual(active["last_completed_document_error_count"], 1362)
        self.assertEqual(active["last_completed_unresolved_tie_count"], 1279)
        self.assertEqual(active["data_verdict"], "FAIL_CLOSED")

        self.assertEqual(retention["accepted_run"]["run_id"], 31555404674)
        self.assertEqual(retention["accepted_run"]["artifact_id"], 9125809076)
        self.assertFalse(retention["retention_result"]["raw_errors_removed"])
        self.assertFalse(retention["retention_result"]["raw_ties_removed"])
        self.assertFalse(retention["retention_result"]["retained_rows_usable_as_numeric_truth"])
        self.assertTrue(retention["retention_result"]["retained_rows_must_be_excluded_from_numeric_feature_values"])

        g1j = authority["authoritative_components"]["S3G1J_FINANCIAL_RAW_VALUES"]
        self.assertEqual(g1j["formal_runtime_generation"], "V17.30")
        self.assertEqual(g1j["last_completed_full_basis_generation"], "V17.30")
        self.assertEqual(g1j["accepted_run_id"], 31518370789)
        self.assertEqual(g1j["accepted_artifact_id"], 9112098872)
        self.assertEqual(g1j["document_error_count"], 1362)
        self.assertEqual(g1j["unresolved_tie_count"], 1279)
        self.assertEqual(g1j["raw_data_verdict"], "FAIL_CLOSED")
        self.assertEqual(g1j["residual_retention_run_id"], 31555404674)
        self.assertTrue(g1j["residual_retention_gate_pass"])
        self.assertTrue(g1j["final_gate"])

        lock_g1j = lock["required_gates"]["S3G1J_FINANCIAL_RAW_VALUES"]
        self.assertEqual(lock_g1j["run_id"], 31518370789)
        self.assertEqual(lock_g1j["artifact_id"], 9112098872)
        self.assertEqual(lock_g1j["document_error_count"], 1362)
        self.assertEqual(lock_g1j["unresolved_tie_count"], 1279)
        self.assertEqual(lock_g1j["raw_data_verdict"], "FAIL_CLOSED")
        self.assertEqual(lock_g1j["residual_retention_run_id"], 31555404674)
        self.assertTrue(lock_g1j["residual_retention_gate_pass"])
        self.assertTrue(lock_g1j["final_gate_pass"])
        self.assertEqual(lock["remaining_unlocked_gates"], ["S3G4_EARNINGS_SURPRISE"])

        pg1j = project["stage3"]["s3g1j"]
        self.assertEqual(pg1j["accepted_run_id"], 31518370789)
        self.assertEqual(pg1j["accepted_artifact_id"], 9112098872)
        self.assertEqual(pg1j["document_error_count"], 1362)
        self.assertEqual(pg1j["unresolved_tie_count"], 1279)
        self.assertEqual(pg1j["raw_data_verdict"], "FAIL_CLOSED")
        self.assertEqual(pg1j["residual_retention_run_id"], 31555404674)
        self.assertTrue(pg1j["residual_retention_gate_pass"])
        self.assertTrue(pg1j["final_gate_pass"])
        self.assertEqual(project["stage3"]["status"], "NOT_READY")
        self.assertEqual(project["stage3"]["pending_final_gates"], ["S3G4_EARNINGS_SURPRISE"])
        self.assertFalse(project["stage4_unlocked"])
        self.assertFalse(project["alpha_training_allowed"])
        self.assertFalse(project["live_signal_allowed"])


if __name__ == "__main__":
    unittest.main()
