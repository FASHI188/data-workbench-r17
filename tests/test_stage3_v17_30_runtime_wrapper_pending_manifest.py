from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class V1730RuntimeWrapperPendingManifestTest(unittest.TestCase):
    def test_pending_manifest_preserves_v17_29_authority(self) -> None:
        pending = json.loads((ROOT / "governance/stage3_s3g1j_v17_30_runtime_wrapper_pending.json").read_text(encoding="utf-8"))
        runtime = json.loads((ROOT / "governance/stage3_s3g1j_runtime_manifest.json").read_text(encoding="utf-8"))
        project = json.loads((ROOT / "data/project_status.json").read_text(encoding="utf-8"))

        self.assertEqual(pending["schema_version"], 1)
        self.assertEqual(pending["status"], "IMPLEMENTATION_UNDER_REVIEW_NOT_ACTIVATED")
        self.assertEqual(pending["generation"], "V17.30")
        self.assertEqual(pending["integration_base"], "62c6da875650d1aa3a06dcc13751599033248e6d")

        before = pending["formal_authority_before_activation"]
        self.assertEqual(before["generation"], "V17.29")
        self.assertEqual(before["parser_git_blob"], "37ab001356c479808e3fa5f67f2270649e3130ba")
        self.assertEqual(before["extractor_git_blob"], "7be4f17357e92144c3f54ddd4951ec57a0878049")
        self.assertEqual(before["last_completed_full_basis_run"], 31389854868)
        self.assertEqual(before["last_completed_full_basis_artifact_id"], 9063271903)
        self.assertEqual(before["numeric_observations"], 1051820)
        self.assertEqual(before["document_errors"], 1364)
        self.assertEqual(before["unresolved_ties"], 1281)
        self.assertEqual(before["data_verdict"], "FAIL_CLOSED")

        evidence = pending["production_promotion_safety_evidence"]
        self.assertEqual(evidence["execution_pr"], 121)
        self.assertEqual(evidence["execution_head"], "2cd84a81b3d4f291aae2ae2cb5b6daf8629ad030")
        self.assertEqual(evidence["execution_run"], 31452374012)
        self.assertEqual(evidence["artifact_id"], 9086776910)
        self.assertEqual(evidence["governance_pr"], 122)
        self.assertEqual(evidence["governance_merge_commit"], "62c6da875650d1aa3a06dcc13751599033248e6d")

        impl = pending["implementation"]
        self.assertEqual(impl["inactive_runtime_parser"], "scripts/stage3_financial_pdf_parser_v22.py")
        self.assertEqual(impl["inactive_extractor"], "scripts/extract_stage3_financial_pdf_values_v20.py")
        self.assertEqual(impl["target_announcement_ids"], ["1223347318", "1223407043"])
        self.assertEqual(impl["activation_identity"], "source_sha256 + source_bytes + economic_date")
        self.assertTrue(impl["non_target_delegates_v17_29_exactly"])
        self.assertTrue(impl["wrong_identity_delegates_v17_29_exactly"])
        self.assertEqual(impl["cross_page_pattern"], "ONE_PAGE_EXACT_ALIAS_CONTINUATION")
        self.assertEqual(impl["accounting_tolerance"], "0.005")

        expected = pending["promotion_safety_shadow_expectation_after_activation"]
        self.assertEqual(expected["status"], "EXPECTATION_ONLY_NOT_PRODUCTION_ACCEPTANCE")
        self.assertEqual(expected["numeric_observations"], 1051826)
        self.assertEqual(expected["document_errors"], 1362)
        self.assertEqual(expected["unresolved_ties"], 1279)
        self.assertTrue(expected["expected_values_are_not_production_acceptance"])

        hard = pending["hard_boundaries"]
        self.assertEqual(hard["formal_runtime_generation_remains"], "V17.29")
        for key in (
            "v17_30_authority_activated",
            "runtime_authority_changed",
            "workflow_activation_manifest_changed",
            "authority_map_changed",
            "project_status_changed",
            "final_lock_changed",
            "fresh_full_basis_execution_started",
            "production_data_changed",
            "trained_model_changed",
            "live_configuration_changed",
            "ocr_enabled",
            "equity_inferred_as_assets_minus_liabilities",
            "fuzzy_alias_matching_enabled",
            "source_policy_relaxed",
            "point_in_time_policy_relaxed",
            "issuer_gate_relaxed",
            "accounting_tolerance_changed",
            "main_changed",
        ):
            self.assertFalse(hard[key], key)
        self.assertEqual(hard["stage3_status"], "NOT_READY")
        self.assertTrue(hard["stage4_alpha_live_locked"])

        self.assertEqual(runtime["schema_version"], 13)
        self.assertEqual(runtime["current_production_authority"]["generation"], "V17.29")
        self.assertEqual(runtime["formal_runtime"]["runtime_generation"], "V17.29")
        self.assertEqual(runtime["formal_runtime"]["parser_git_blob"], "37ab001356c479808e3fa5f67f2270649e3130ba")
        self.assertEqual(runtime["formal_runtime"]["extractor_git_blob"], "7be4f17357e92144c3f54ddd4951ec57a0878049")
        full = runtime["full_basis_last_completed_final"]
        self.assertEqual(full["generation"], "V17.29")
        self.assertEqual(full["run"], 31389854868)
        self.assertEqual(full["artifact_id"], 9063271903)
        self.assertEqual(full["numeric_observations"], 1051820)
        self.assertEqual(full["document_error_count"], 1364)
        self.assertEqual(full["unresolved_tie_count"], 1281)
        self.assertEqual(full["verdict"], "FAIL_CLOSED")

        self.assertEqual(project["stage3"]["status"], "NOT_READY")
        self.assertFalse(project["stage4_unlocked"])
        self.assertFalse(project["alpha_training_allowed"])
        self.assertFalse(project["live_signal_allowed"])


if __name__ == "__main__":
    unittest.main()
