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
        cls.v17_28 = load("governance/stage3_s3g1j_v17_28_full_final.json")

    def test_wrapper_acceptance_identity_is_exact(self) -> None:
        wrapper = self.promotion["wrapper_implementation"]
        self.assertEqual(wrapper["pr"], 109)
        self.assertTrue(wrapper["closed_without_merge"])
        self.assertEqual(wrapper["head_sha"], "04a014f852bff57aef57542553864fcd3f1df13d")
        self.assertEqual(wrapper["acceptance_run"], 31312709490)
        self.assertEqual(wrapper["pending_authority_run"], 31312709486)
        self.assertEqual(wrapper["repository_safety_run"], 31312709472)
        self.assertEqual(wrapper["runtime_reproducibility_run"], 31312709475)
        self.assertEqual(wrapper["clean_s3g1j_run"], 31312709497)
        self.assertEqual(wrapper["acceptance_artifact_id"], 9037869497)
        self.assertEqual(
            wrapper["acceptance_artifact_digest"],
            "sha256:4f9940513c2d0ef5250b8874b32f68655badfe4a695a2fe2c3da0a54d2a01670",
        )
        self.assertEqual(
            wrapper["acceptance_report_sha256"],
            "29fc2947008e26b8c17ab5c9013a31c5e283c2d89aa37a8f7de2e1da5658a406",
        )
        self.assertTrue(wrapper["all_required_machine_gates_success"])
        self.assertTrue(wrapper["real_source_runtime_wrapper_pass"])
        self.assertTrue(wrapper["non_target_v17_28_delegation_pass"])
        self.assertTrue(wrapper["independent_artifact_recheck_pass"])

    def test_formal_runtime_is_v17_29(self) -> None:
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
        self.assertEqual(extractor.SHARD_GATE, formal["shard_gate"])

    def test_v17_28_remains_last_completed_full_basis(self) -> None:
        previous = self.promotion["last_completed_full_basis"]
        self.assertEqual(previous["generation"], "V17.28")
        self.assertEqual(previous["run"], 30997260730)
        self.assertEqual(previous["artifact_id"], 8927455692)
        self.assertEqual(
            previous["artifact_digest"],
            "sha256:82375169faada969ceafd4356ab0a2707aa14592d5db090c5d3910863d571c8b",
        )
        self.assertEqual(previous["numeric_rows"], 1051799)
        self.assertEqual(previous["document_errors"], 1371)
        self.assertEqual(previous["unresolved_ties"], 1288)
        self.assertEqual(previous["data_verdict"], "FAIL_CLOSED")
        accepted = self.v17_28["accepted_run"]
        result = self.v17_28["full_basis_result"]
        self.assertEqual(accepted["run_id"], previous["run"])
        self.assertEqual(accepted["artifact_id"], previous["artifact_id"])
        self.assertEqual(result["numeric_observation_count"], previous["numeric_rows"])
        self.assertEqual(result["document_error_count"], previous["document_errors"])
        self.assertEqual(result["unresolved_tie_count"], previous["unresolved_ties"])

    def test_fresh_v17_29_full_basis_is_required_not_started(self) -> None:
        nxt = self.promotion["next_full_basis"]
        self.assertEqual(nxt["generation"], "V17.29")
        self.assertEqual(nxt["status"], "REQUIRED_NOT_STARTED")
        self.assertEqual(nxt["expected_document_rows"], 121354)
        self.assertEqual(nxt["expected_numeric_rows"], 1051820)
        self.assertEqual(nxt["expected_document_errors"], 1364)
        self.assertEqual(nxt["expected_unresolved_ties"], 1281)
        self.assertEqual(nxt["expected_target_numeric_rows"], 21)
        self.assertTrue(nxt["expected_values_are_not_production_acceptance"])
        self.assertTrue(nxt["candidate_or_promotion_safety_results_are_not_full_basis_acceptance"])

    def test_authority_surfaces_agree(self) -> None:
        current = self.runtime["current_production_authority"]
        self.assertEqual(self.runtime["schema_version"], 12)
        self.assertEqual(current["generation"], "V17.29")
        self.assertEqual(current["status"], "RUNTIME_PROMOTED_FULL_BASIS_PENDING_FAIL_CLOSED")
        self.assertIsNone(current["full_basis_evidence_manifest"])
        self.assertEqual(self.runtime["formal_runtime"]["runtime_generation"], "V17.29")
        self.assertEqual(self.runtime["full_basis_last_completed_final"]["generation"], "V17.28")
        self.assertEqual(self.runtime["next_full_basis_required"]["generation"], "V17.29")
        self.assertEqual(self.runtime["next_full_basis_required"]["status"], "REQUIRED_NOT_STARTED")

        self.assertEqual(self.activation["schema_version"], 14)
        active = self.activation["accepted_production_runtime"]
        self.assertEqual(active["generation"], "V17.29")
        self.assertTrue(active["full_basis_execution_pending"])
        self.assertEqual(active["last_completed_full_basis_generation"], "V17.28")
        self.assertEqual(active["execution_verdict"], "PENDING")
        self.assertTrue(active["expected_values_are_not_production_acceptance"])

        g1j = self.authority["authoritative_components"]["S3G1J_FINANCIAL_RAW_VALUES"]
        self.assertEqual(self.authority["schema_version"], 5)
        self.assertEqual(g1j["formal_runtime_generation"], "V17.29")
        self.assertEqual(g1j["last_completed_full_basis_generation"], "V17.28")
        self.assertEqual(g1j["next_full_basis_status"], "REQUIRED_NOT_STARTED")
        self.assertFalse(g1j["final_gate"])

        project_g1j = self.project["stage3"]["s3g1j"]
        self.assertEqual(self.project["schema_version"], 5)
        self.assertEqual(project_g1j["formal_runtime_generation"], "V17.29")
        self.assertEqual(project_g1j["last_completed_full_basis_generation"], "V17.28")
        self.assertEqual(project_g1j["next_full_basis_status"], "REQUIRED_NOT_STARTED")
        self.assertFalse(project_g1j["final_gate_pass"])

        lock_g1j = self.lock["required_gates"]["S3G1J_FINANCIAL_RAW_VALUES"]
        self.assertEqual(self.lock["version"], "V3.3.12-stage3-final-lock")
        self.assertEqual(lock_g1j["formal_runtime_generation"], "V17.29")
        self.assertEqual(lock_g1j["last_completed_full_basis_generation"], "V17.28")
        self.assertEqual(lock_g1j["next_full_basis_status"], "REQUIRED_NOT_STARTED")
        self.assertFalse(lock_g1j["final_gate_pass"])

    def test_project_and_policy_stay_fail_closed(self) -> None:
        boundaries = self.promotion["hard_boundaries"]
        for key in (
            "source_policy_changed",
            "point_in_time_policy_changed",
            "issuer_gate_changed",
            "accounting_tolerance_changed",
            "ocr_enabled",
            "fuzzy_alias_matching_enabled",
            "e_equals_a_minus_l_inference",
            "fresh_64_shard_execution_started",
            "production_data_changed",
            "trained_model_changed",
            "live_configuration_changed",
            "main_changed",
            "merge_to_main_authorized",
        ):
            self.assertFalse(boundaries[key], key)
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertTrue(boundaries["stage4_alpha_live_locked"])
        self.assertEqual(self.project["stage3"]["status"], "NOT_READY")
        self.assertFalse(self.project["stage4_unlocked"])
        self.assertFalse(self.project["alpha_training_allowed"])
        self.assertFalse(self.project["live_signal_allowed"])
        self.assertEqual(self.lock["status"], "NOT_READY")


if __name__ == "__main__":
    unittest.main()
