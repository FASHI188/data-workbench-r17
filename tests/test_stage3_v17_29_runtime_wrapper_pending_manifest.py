from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class V1729RuntimeWrapperPendingManifestTest(unittest.TestCase):
    def test_pending_manifest_preserves_v17_28_authority(self) -> None:
        pending = json.loads(
            (ROOT / "governance/stage3_s3g1j_v17_29_runtime_wrapper_pending.json").read_text(
                encoding="utf-8"
            )
        )
        runtime = json.loads(
            (ROOT / "governance/stage3_s3g1j_runtime_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        activation = json.loads(
            (ROOT / "governance/stage3_workflow_activation_manifest.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(pending["schema_version"], 1)
        self.assertEqual(pending["status"], "IMPLEMENTATION_UNDER_REVIEW_NOT_ACTIVATED")
        self.assertEqual(pending["generation"], "V17.29")
        self.assertEqual(
            pending["integration_base"],
            "5b416a6cfa017593d585b51eff6db1d88296dc4f",
        )
        self.assertEqual(pending["promotion_safety_evidence"]["execution_pr"], 107)
        self.assertEqual(
            pending["promotion_safety_evidence"]["execution_head"],
            "4ea4ac01bcca3e580d73fc37378c2658df8f4b28",
        )
        self.assertEqual(pending["promotion_safety_evidence"]["execution_run"], 31311296836)
        self.assertEqual(pending["promotion_safety_evidence"]["artifact_id"], 9037500964)
        self.assertEqual(pending["promotion_safety_evidence"]["governance_pr"], 108)
        self.assertEqual(
            pending["promotion_safety_evidence"]["governance_merge_commit"],
            "5b416a6cfa017593d585b51eff6db1d88296dc4f",
        )
        self.assertEqual(
            pending["implementation"]["production_parser"],
            "scripts/stage3_financial_pdf_parser_v21.py",
        )
        self.assertEqual(
            pending["implementation"]["extractor"],
            "scripts/extract_stage3_financial_pdf_values_v19.py",
        )
        self.assertTrue(pending["implementation"]["non_target_delegates_v17_28_exactly"])
        self.assertEqual(pending["implementation"]["accounting_tolerance"], "0.005")
        expected = pending["expected_fresh_full_basis_after_activation"]
        self.assertEqual(expected["status"], "REQUIRED_NOT_STARTED")
        self.assertTrue(expected["expected_values_are_not_production_acceptance"])
        self.assertTrue(expected["promotion_safety_is_not_full_basis_acceptance"])
        self.assertEqual(expected["numeric_observations"], 1051820)
        self.assertEqual(expected["document_errors"], 1364)
        self.assertEqual(expected["unresolved_ties"], 1281)

        boundaries = pending["hard_boundaries"]
        for key in (
            "runtime_authority_changed",
            "workflow_activation_manifest_changed",
            "authority_map_changed",
            "project_status_changed",
            "final_lock_changed",
            "fresh_64_shard_execution_started",
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
            self.assertFalse(boundaries[key], key)
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertTrue(boundaries["stage4_alpha_live_locked"])

        self.assertEqual(runtime["schema_version"], 11)
        self.assertEqual(runtime["current_production_authority"]["generation"], "V17.28")
        self.assertEqual(runtime["formal_runtime"]["runtime_generation"], "V17.28")
        self.assertEqual(runtime["full_basis_last_completed_final"]["generation"], "V17.28")
        self.assertEqual(runtime["full_basis_last_completed_final"]["run"], 30997260730)
        self.assertEqual(runtime["full_basis_last_completed_final"]["numeric_observations"], 1051799)
        self.assertEqual(runtime["full_basis_last_completed_final"]["document_error_count"], 1371)
        self.assertEqual(runtime["full_basis_last_completed_final"]["unresolved_tie_count"], 1288)
        self.assertIsNone(runtime["next_full_basis_required"]["generation"])
        self.assertEqual(
            runtime["next_full_basis_required"]["status"],
            "NONE_CURRENT_RUNTIME_ACCEPTED",
        )

        self.assertEqual(activation["schema_version"], 13)
        accepted = activation["accepted_production_runtime"]
        self.assertEqual(accepted["generation"], "V17.28")
        self.assertFalse(accepted["full_basis_execution_pending"])
        self.assertEqual(accepted["last_completed_full_basis_generation"], "V17.28")
        self.assertEqual(accepted["last_completed_full_basis_run"], 30997260730)


if __name__ == "__main__":
    unittest.main()
