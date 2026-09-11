from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_28_full_final.json"


class V1728FullFinalEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_exact_run_and_artifact_identity(self) -> None:
        accepted = self.evidence["accepted_run"]
        self.assertEqual(accepted["run_id"], 30997260730)
        self.assertEqual(accepted["head_sha"], "611d402c3b61a35644a27fd33d3955b9976dec7c")
        self.assertEqual(accepted["artifact_id"], 8927455692)
        self.assertEqual(accepted["artifact_name"], "stage3-s3g1j-v17-28-full-final")
        self.assertEqual(
            accepted["artifact_digest"],
            "sha256:82375169faada969ceafd4356ab0a2707aa14592d5db090c5d3910863d571c8b",
        )
        self.assertEqual(accepted["conclusion"], "SUCCESS")

    def test_source_execution_is_complete_and_non_merge(self) -> None:
        source = self.evidence["source_execution"]
        self.assertEqual(source["run_id"], 30981127011)
        self.assertEqual(source["head_sha"], "7dd3e14ccdd9574ce7f4a8f716026ececf254541")
        self.assertEqual(source["shard_count"], 64)
        self.assertEqual(source["unique_artifact_ids"], 64)
        self.assertEqual(source["unique_artifact_digests"], 64)
        self.assertIs(source["execution_pr_closed_without_merge"], True)
        self.assertIs(source["all_artifacts_non_expired"], True)
        self.assertIs(source["all_artifacts_bound_to_exact_head"], True)

    def test_full_basis_counts_and_fail_closed_boundary(self) -> None:
        result = self.evidence["full_basis_result"]
        self.assertIs(result["execution_pass"], True)
        self.assertIs(result["document_non_regression_pass"], True)
        self.assertIs(result["numeric_non_regression_pass"], True)
        self.assertEqual(result["document_count"], 121354)
        self.assertEqual(result["numeric_observation_count"], 1051799)
        self.assertEqual(result["document_error_count"], 1371)
        self.assertEqual(result["unresolved_tie_count"], 1288)
        self.assertEqual(result["changed_announcement_ids"], ["1207621057", "1209825769"])
        self.assertEqual(result["target_numeric_rows"], 6)
        self.assertEqual(result["non_target_document_count"], 121352)
        self.assertEqual(result["unexpected_document_regression_count"], 0)
        self.assertIs(result["final_data_gate_pass"], False)
        self.assertEqual(result["final_data_verdict"], "FAIL_CLOSED")

    def test_tie_taxonomy_is_exact(self) -> None:
        result = self.evidence["full_basis_result"]
        self.assertEqual(
            result["tie_taxonomy_previous"],
            {"TIE_SOURCE_INCOMPLETE": 1276, "TIE_VALUE_CONFLICT": 14},
        )
        self.assertEqual(
            result["tie_taxonomy_current"],
            {"TIE_SOURCE_INCOMPLETE": 1274, "TIE_VALUE_CONFLICT": 14},
        )

    def test_existing_numeric_identity_is_unchanged(self) -> None:
        numeric = self.evidence["numeric_non_regression"]
        expected = "bcb154cc4d80a81acd409e64dc35c2902a5aeb37726b313df936717caf400672"
        self.assertIs(numeric["pass"], True)
        self.assertEqual(numeric["stable_field_count"], 22)
        self.assertEqual(numeric["previous_existing_row_count"], 1051793)
        self.assertEqual(numeric["current_existing_row_count"], 1051793)
        self.assertEqual(numeric["previous_existing_semantic_sha256"], expected)
        self.assertEqual(numeric["current_existing_semantic_sha256"], expected)
        self.assertEqual(numeric["existing_numeric_value_drift"], 0)
        self.assertEqual(numeric["additional_numeric_rows"], 6)

    def test_project_locks_remain_closed(self) -> None:
        boundaries = self.evidence["hard_boundaries"]
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["s3g4_full_final_pending"], True)
        self.assertIs(boundaries["freshness_gate_pending"], True)
        self.assertIs(boundaries["committed_production_data_changed"], False)
        self.assertIs(boundaries["trained_model_changed"], False)
        self.assertIs(boundaries["main_changed"], False)
        self.assertIs(boundaries["merge_to_main_authorized"], False)


if __name__ == "__main__":
    unittest.main()
