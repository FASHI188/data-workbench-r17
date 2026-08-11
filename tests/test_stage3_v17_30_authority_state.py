from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class V1730AuthorityStateTest(unittest.TestCase):
    def load(self, path: str) -> dict:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))

    def test_promoted_runtime_keeps_v17_29_as_last_completed_basis(self) -> None:
        runtime = self.load("governance/stage3_s3g1j_runtime_manifest.json")
        activation = self.load("governance/stage3_workflow_activation_manifest.json")
        authority = self.load("governance/stage3_authority_map.json")
        lock = self.load("config/stage3_final_lock.json")
        project = self.load("data/project_status.json")
        self.assertEqual(runtime["schema_version"], 14)
        self.assertEqual(runtime["current_production_authority"]["generation"], "V17.30")
        self.assertEqual(runtime["formal_runtime"]["runtime_generation"], "V17.30")
        self.assertEqual(runtime["full_basis_last_completed_final"]["generation"], "V17.29")
        self.assertEqual(runtime["full_basis_last_completed_final"]["run"], 31389854868)
        self.assertEqual(runtime["next_full_basis_required"]["generation"], "V17.30")
        self.assertEqual(runtime["next_full_basis_required"]["status"], "REQUIRED_NOT_STARTED")
        self.assertEqual(runtime["next_full_basis_required"]["expected_numeric_observations"], 1051826)
        self.assertTrue(runtime["next_full_basis_required"]["expected_values_are_not_production_acceptance"])
        self.assertEqual(activation["accepted_production_runtime"]["generation"], "V17.30")
        self.assertTrue(activation["accepted_production_runtime"]["full_basis_execution_pending"])
        self.assertEqual(activation["accepted_production_runtime"]["last_completed_full_basis_generation"], "V17.29")
        g1j = authority["authoritative_components"]["S3G1J_FINANCIAL_RAW_VALUES"]
        self.assertEqual(g1j["formal_runtime_generation"], "V17.30")
        self.assertEqual(g1j["last_completed_full_basis_generation"], "V17.29")
        self.assertEqual(g1j["next_full_basis_generation"], "V17.30")
        self.assertEqual(g1j["next_full_basis_status"], "REQUIRED_NOT_STARTED")
        self.assertFalse(g1j["final_gate"])
        lock_g1j = lock["required_gates"]["S3G1J_FINANCIAL_RAW_VALUES"]
        self.assertEqual(lock_g1j["formal_runtime_generation"], "V17.30")
        self.assertEqual(lock_g1j["last_completed_full_basis_generation"], "V17.29")
        self.assertEqual(lock_g1j["next_full_basis_generation"], "V17.30")
        self.assertEqual(lock_g1j["next_full_basis_status"], "REQUIRED_NOT_STARTED")
        pg1j = project["stage3"]["s3g1j"]
        self.assertEqual(pg1j["formal_runtime_generation"], "V17.30")
        self.assertEqual(pg1j["last_completed_full_basis_generation"], "V17.29")
        self.assertEqual(pg1j["next_full_basis_generation"], "V17.30")
        self.assertEqual(pg1j["next_full_basis_status"], "REQUIRED_NOT_STARTED")
        self.assertEqual(project["stage3"]["status"], "NOT_READY")
        self.assertFalse(project["stage4_unlocked"])
        self.assertFalse(project["alpha_training_allowed"])
        self.assertFalse(project["live_signal_allowed"])


if __name__ == "__main__":
    unittest.main()
