from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_29_full_final.json"


class V1729FullFinalEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_exact_run_and_artifact_identity(self) -> None:
        accepted = self.evidence["accepted_run"]
        self.assertEqual(accepted["run_id"], 31389854868)
        self.assertEqual(accepted["head_sha"], "22fa37064eeb8a49ad5292dd2be48bd7b674c673")
        self.assertEqual(accepted["artifact_id"], 9063271903)
        self.assertEqual(accepted["artifact_name"], "stage3-s3g1j-v17-29-full-final")
        self.assertEqual(accepted["artifact_digest"], "sha256:71a4daa6c8372f3d64080b5fa5b787914292d889da7051de699eb6610189c726")
        self.assertEqual(accepted["conclusion"], "SUCCESS")

    def test_source_execution_is_complete_and_non_merge(self) -> None:
        source = self.evidence["source_execution"]
        self.assertEqual(source["execution_pr"], 113)
        self.assertEqual(source["run_id"], 31365802099)
        self.assertEqual(source["head_sha"], "2b48694391e2a6cdbd6972b68844c1253b3c55d9")
        self.assertEqual(source["shard_count"], 64)
        self.assertEqual(source["unique_artifact_ids"], 64)
        self.assertEqual(source["unique_artifact_digests"], 64)
        self.assertIs(source["execution_pr_closed_without_merge"], True)
        self.assertIs(source["all_artifacts_bound_to_exact_head"], True)
        self.assertIs(source["all_shard_identity_enforcement_passed"], True)

    def test_full_basis_counts_and_fail_closed_boundary(self) -> None:
        result = self.evidence["full_basis_result"]
        self.assertIs(result["execution_pass"], True)
        self.assertIs(result["document_non_regression_pass"], True)
        self.assertIs(result["numeric_non_regression_pass"], True)
        self.assertIs(result["promotion_gold_equality_pass"], True)
        self.assertEqual(result["document_count"], 121354)
        self.assertEqual(result["numeric_observation_count"], 1051820)
        self.assertEqual(result["document_error_count"], 1364)
        self.assertEqual(result["unresolved_tie_count"], 1281)
        self.assertEqual(result["target_document_count"], 7)
        self.assertEqual(result["target_numeric_rows"], 21)
        self.assertEqual(result["non_target_document_count"], 121347)
        self.assertEqual(result["unexpected_document_regression_count"], 0)
        self.assertIs(result["final_data_gate_pass"], False)
        self.assertEqual(result["final_data_verdict"], "FAIL_CLOSED")

    def test_exact_target_set_and_tie_taxonomy(self) -> None:
        result = self.evidence["full_basis_result"]
        self.assertEqual(result["changed_announcement_ids"], [
            "1215186538", "1219426855", "1219792633", "1219840508",
            "1219879687", "1220087244", "1221006100",
        ])
        self.assertEqual(result["tie_taxonomy_previous"], {"TIE_SOURCE_INCOMPLETE": 1274, "TIE_VALUE_CONFLICT": 14})
        self.assertEqual(result["tie_taxonomy_current"], {"TIE_SOURCE_INCOMPLETE": 1267, "TIE_VALUE_CONFLICT": 14})

    def test_existing_numeric_identity_and_gold_equality(self) -> None:
        numeric = self.evidence["numeric_non_regression"]
        existing = "2fa6a5bf2044a3fd46ed8599d31b07a512f2acb377b76d5cdbcea0e0dbb006ea"
        full = "0457d2c4601e7356c842eebfab5b6b52e851da26f2508f8c38d3833f9ef6fa51"
        self.assertIs(numeric["pass"], True)
        self.assertEqual(numeric["stable_field_count"], 22)
        self.assertEqual(numeric["previous_existing_row_count"], 1051799)
        self.assertEqual(numeric["current_existing_row_count"], 1051799)
        self.assertEqual(numeric["previous_existing_semantic_sha256"], existing)
        self.assertEqual(numeric["current_existing_semantic_sha256"], existing)
        self.assertEqual(numeric["fresh_full_semantic_sha256"], full)
        self.assertEqual(numeric["promotion_gold_semantic_sha256"], full)
        self.assertEqual(numeric["existing_numeric_value_drift"], 0)
        self.assertEqual(numeric["additional_numeric_rows"], 21)

    def test_project_locks_remain_closed(self) -> None:
        boundaries = self.evidence["hard_boundaries"]
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertEqual(boundaries["remaining_document_errors"], 1364)
        self.assertEqual(boundaries["remaining_unresolved_ties"], 1281)
        self.assertIs(boundaries["s3g4_full_final_pending"], True)
        self.assertIs(boundaries["freshness_gate_pending"], True)
        self.assertIs(boundaries["committed_production_data_changed"], False)
        self.assertIs(boundaries["trained_model_changed"], False)
        self.assertIs(boundaries["main_changed"], False)
        self.assertIs(boundaries["merge_to_main_authorized"], False)


if __name__ == "__main__":
    unittest.main()
