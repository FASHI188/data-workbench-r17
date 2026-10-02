from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class V1730RuntimePromotionTest(unittest.TestCase):
    def load(self, path: str) -> dict:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))

    def test_runtime_promotion_manifest_preserves_full_basis_boundary(self) -> None:
        p = self.load("governance/stage3_s3g1j_v17_30_runtime_promotion.json")
        self.assertEqual(p["schema_version"], 1)
        self.assertEqual(p["generation"], "V17.30")
        self.assertTrue(p["wrapper_acceptance"]["execution_pr_closed_without_merge"])
        self.assertEqual(p["wrapper_acceptance"]["execution_pr"], 123)
        self.assertEqual(p["wrapper_acceptance"]["execution_head_sha"], "d26d7f543c20d717ed8c8a421e28838feecd7a03")
        self.assertEqual(p["wrapper_acceptance"]["acceptance_run"], 31458469699)
        self.assertEqual(p["wrapper_acceptance"]["artifact_id"], 9088925988)
        self.assertEqual(p["wrapper_acceptance"]["artifact_digest"], "sha256:232b2e4a6c64b271193853d4e8fd32c0fdfd367344ecec720902fe8f090333dc")
        code = p["accepted_code_identity"]
        self.assertEqual(code["promotion_safety_parser_git_blob"], "1a4364d5cde7881455902f6fa1dbe5e68f3843a6")
        self.assertEqual(code["production_parser_git_blob"], "cc782817e5ee73fcae085d71f4896a0adc004dcd")
        self.assertEqual(code["extractor_git_blob"], "d74a2b1f8f0ec3af8d89ce259e83392d7f8cc20c")
        self.assertEqual(code["runtime_regression_test_git_blob"], "c7ddfd881010361485f6d4942831d9655bcb3d2c")
        self.assertTrue(code["copied_from_exact_accepted_head_without_algorithm_rewrite"])
        formal = p["formal_runtime_after_governance"]
        self.assertEqual(formal["runtime_generation"], "V17.30")
        self.assertTrue(formal["non_target_delegates_v17_29_exactly"])
        self.assertEqual(formal["target_announcement_ids"], ["1223347318", "1223407043"])
        last = p["last_completed_full_basis"]
        self.assertEqual(last["generation"], "V17.29")
        self.assertEqual(last["run"], 31389854868)
        self.assertEqual(last["artifact_id"], 9063271903)
        self.assertEqual(last["numeric_rows"], 1051820)
        self.assertEqual(last["document_errors"], 1364)
        self.assertEqual(last["unresolved_ties"], 1281)
        self.assertEqual(last["data_verdict"], "FAIL_CLOSED")
        nxt = p["next_full_basis"]
        self.assertEqual(nxt["generation"], "V17.30")
        self.assertEqual(nxt["status"], "REQUIRED_NOT_STARTED")
        self.assertEqual(nxt["expected_numeric_rows"], 1051826)
        self.assertEqual(nxt["expected_document_errors"], 1362)
        self.assertEqual(nxt["expected_unresolved_ties"], 1279)
        self.assertTrue(nxt["expected_values_are_not_production_acceptance"])
        self.assertTrue(nxt["wrapper_or_shadow_results_are_not_full_basis_acceptance"])
        hard = p["hard_boundaries"]
        self.assertFalse(hard["fresh_64_shard_execution_started"])
        self.assertFalse(hard["production_data_changed"])
        self.assertFalse(hard["trained_model_changed"])
        self.assertFalse(hard["live_configuration_changed"])
        self.assertEqual(hard["stage3_status"], "NOT_READY")
        self.assertTrue(hard["stage4_alpha_live_locked"])
        self.assertFalse(hard["main_changed"])


if __name__ == "__main__":
    unittest.main()
