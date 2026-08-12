from __future__ import annotations

import json
import unittest
from pathlib import Path

import extract_stage3_financial_pdf_values_v19 as extractor
import stage3_financial_pdf_parser_v21 as parser

ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class V1729RuntimePromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.promotion = load("governance/stage3_s3g1j_v17_29_runtime_promotion.json")
        cls.runtime = load("governance/stage3_s3g1j_runtime_manifest.json")
        cls.activation = load("governance/stage3_workflow_activation_manifest.json")
        cls.authority = load("governance/stage3_authority_map.json")
        cls.project = load("data/project_status.json")
        cls.lock = load("config/stage3_final_lock.json")
        cls.retention = load("governance/stage3_s3g1j_v17_30_residual_retention.json")
        cls.v17_28 = load("governance/stage3_s3g1j_v17_28_full_final.json")
        cls.v17_29 = load("governance/stage3_s3g1j_v17_29_full_final.json")

    def test_wrapper_acceptance_identity_is_exact(self) -> None:
        wrapper = self.promotion["wrapper_implementation"]
        self.assertEqual(wrapper["pr"], 109)
        self.assertTrue(wrapper["closed_without_merge"])
        self.assertEqual(wrapper["head_sha"], "04a014f852bff57aef57542553864fcd3f1df13d")
        self.assertEqual(wrapper["acceptance_run"], 31312709490)
        self.assertEqual(wrapper["acceptance_artifact_id"], 9037869497)
        self.assertEqual(wrapper["acceptance_artifact_digest"], "sha256:4f9940513c2d0ef5250b8874b32f68655badfe4a695a2fe2c3da0a54d2a01670")
        self.assertTrue(wrapper["all_required_machine_gates_success"])
        self.assertTrue(wrapper["real_source_runtime_wrapper_pass"])
        self.assertTrue(wrapper["non_target_v17_28_delegation_pass"])
        self.assertTrue(wrapper["independent_artifact_recheck_pass"])

    def test_historical_v17_29_runtime_identity_is_exact(self) -> None:
        formal = self.promotion["formal_runtime"]
        self.assertEqual(formal["runtime_generation"], "V17.29")
        self.assertEqual(formal["shard_gate"], "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_29")
        self.assertEqual(formal["parser_path"], "scripts/stage3_financial_pdf_parser_v21.py")
        self.assertEqual(formal["extractor_path"], "scripts/extract_stage3_financial_pdf_values_v19.py")
        self.assertEqual(formal["methodology_version"], "V3.3.13-V17.29")
        self.assertEqual(formal["accounting_tolerance"], "0.005")
        self.assertTrue(formal["non_target_delegates_v17_28_exactly"])
        self.assertEqual(len(formal["target_announcement_ids"]), 7)
        self.assertEqual(parser.METHOD, formal["parser_method"])
        self.assertEqual(extractor.METHOD, formal["extractor_method"])
        self.assertEqual(extractor.RUNTIME_GENERATION, "V17.29")

    def test_promotion_evidence_preserves_pre_execution_checkpoint(self) -> None:
        previous = self.promotion["last_completed_full_basis"]
        self.assertEqual(previous["generation"], "V17.28")
        self.assertEqual(previous["run"], 30997260730)
        self.assertEqual(previous["artifact_id"], 8927455692)
        self.assertEqual(previous["numeric_rows"], 1051799)
        self.assertEqual(previous["document_errors"], 1371)
        self.assertEqual(previous["unresolved_ties"], 1288)
        self.assertEqual(previous["data_verdict"], "FAIL_CLOSED")
        nxt = self.promotion["next_full_basis"]
        self.assertEqual(nxt["generation"], "V17.29")
        self.assertEqual(nxt["status"], "REQUIRED_NOT_STARTED")
        self.assertEqual(nxt["expected_numeric_rows"], 1051820)
        self.assertTrue(nxt["expected_values_are_not_production_acceptance"])

    def test_v17_29_is_retained_as_previous_basis_under_v17_30_formal_retention(self) -> None:
        self.assertGreaterEqual(self.runtime["schema_version"], 15)
        self.assertEqual(self.runtime["formal_runtime"]["runtime_generation"], "V17.30")
        latest = self.runtime["full_basis_last_completed_final"]
        self.assertEqual((latest["generation"], latest["run"]), ("V17.30", 31518370789))
        self.assertEqual(latest["numeric_observations"], 1051826)
        self.assertEqual(latest["document_error_count"], 1362)
        self.assertEqual(latest["unresolved_tie_count"], 1279)
        self.assertEqual(latest["verdict"], "FAIL_CLOSED")
        previous = self.runtime["previous_last_completed_full_basis_final"]
        self.assertEqual((previous["generation"], previous["run"]), ("V17.29", 31389854868))
        self.assertEqual(previous["artifact_id"], 9063271903)
        self.assertEqual(previous["numeric_observations"], 1051820)
        self.assertEqual(previous["document_error_count"], 1364)
        self.assertEqual(previous["unresolved_tie_count"], 1281)
        self.assertEqual(previous["verdict"], "FAIL_CLOSED")
        self.assertTrue(previous["retained"])
        next_basis = self.runtime["next_full_basis_required"]
        self.assertIsNone(next_basis["generation"])
        self.assertEqual(next_basis["status"], "NONE_CURRENT_RUNTIME_ACCEPTED")

        active = self.activation["accepted_production_runtime"]
        self.assertEqual(active["generation"], "V17.30")
        self.assertFalse(active["full_basis_execution_pending"])
        self.assertEqual(active["last_completed_full_basis_generation"], "V17.30")
        self.assertEqual(active["last_completed_full_basis_run"], 31518370789)
        self.assertEqual(active["data_verdict"], "FAIL_CLOSED")
        retained29 = self.activation["accepted_v17_29_full_basis_evidence"]
        self.assertFalse(retained29["last_completed_full_basis_authority"])
        self.assertTrue(retained29["historical_runtime_generation_retained"])
        self.assertTrue(retained29["historical_full_basis_authority_retained"])

        self.assertEqual(self.retention["accepted_run"]["run_id"], 31555404674)
        self.assertFalse(self.retention["retention_result"]["raw_errors_removed"])
        self.assertFalse(self.retention["retention_result"]["retained_rows_usable_as_numeric_truth"])

        g1j = self.authority["authoritative_components"]["S3G1J_FINANCIAL_RAW_VALUES"]
        self.assertEqual(g1j["formal_runtime_generation"], "V17.30")
        self.assertEqual(g1j["last_completed_full_basis_generation"], "V17.30")
        self.assertEqual(g1j["accepted_run_id"], 31518370789)
        self.assertEqual(g1j["previous_full_basis_authority"]["generation"], "V17.29")
        self.assertEqual(g1j["previous_full_basis_authority"]["run"], 31389854868)
        self.assertEqual(g1j["raw_data_verdict"], "FAIL_CLOSED")
        self.assertEqual(g1j["residual_retention_run_id"], 31555404674)
        self.assertTrue(g1j["residual_retention_gate_pass"])
        self.assertTrue(g1j["final_gate"])

        project_g1j = self.project["stage3"]["s3g1j"]
        self.assertEqual(project_g1j["formal_runtime_generation"], "V17.30")
        self.assertEqual(project_g1j["last_completed_full_basis_generation"], "V17.30")
        self.assertEqual(project_g1j["accepted_run_id"], 31518370789)
        self.assertEqual(project_g1j["previous_full_basis_authority"]["generation"], "V17.29")
        self.assertEqual(project_g1j["previous_full_basis_authority"]["run"], 31389854868)
        self.assertEqual(project_g1j["raw_data_verdict"], "FAIL_CLOSED")
        self.assertEqual(project_g1j["residual_retention_run_id"], 31555404674)
        self.assertTrue(project_g1j["final_gate_pass"])

        lock_g1j = self.lock["required_gates"]["S3G1J_FINANCIAL_RAW_VALUES"]
        self.assertEqual(lock_g1j["formal_runtime_generation"], "V17.30")
        self.assertEqual(lock_g1j["last_completed_full_basis_generation"], "V17.30")
        self.assertEqual(lock_g1j["run_id"], 31518370789)
        self.assertEqual(lock_g1j["previous_full_basis_authority"]["generation"], "V17.29")
        self.assertEqual(lock_g1j["previous_full_basis_authority"]["run"], 31389854868)
        self.assertEqual(lock_g1j["raw_data_verdict"], "FAIL_CLOSED")
        self.assertEqual(lock_g1j["residual_retention_run_id"], 31555404674)
        self.assertTrue(lock_g1j["final_gate_pass"])

    def test_project_and_historical_evidence_stay_fail_closed(self) -> None:
        boundaries = self.promotion["hard_boundaries"]
        self.assertFalse(boundaries["production_data_changed"])
        self.assertFalse(boundaries["trained_model_changed"])
        self.assertFalse(boundaries["live_configuration_changed"])
        self.assertFalse(boundaries["main_changed"])
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertTrue(boundaries["stage4_alpha_live_locked"])
        accepted29 = self.v17_29["accepted_run"]
        result29 = self.v17_29["full_basis_result"]
        self.assertEqual(accepted29["run_id"], 31389854868)
        self.assertEqual(result29["numeric_observation_count"], 1051820)
        self.assertEqual(result29["document_error_count"], 1364)
        self.assertEqual(result29["unresolved_tie_count"], 1281)
        self.assertEqual(result29["final_data_verdict"], "FAIL_CLOSED")
        self.assertEqual(self.project["stage3"]["status"], "NOT_READY")
        self.assertFalse(self.project["stage4_unlocked"])
        self.assertFalse(self.project["alpha_training_allowed"])
        self.assertFalse(self.project["live_signal_allowed"])


if __name__ == "__main__":
    unittest.main()
