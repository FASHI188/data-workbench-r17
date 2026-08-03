from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_28_candidate_safety.json"


class V1728CandidateEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_candidate_pr_is_non_merge_evidence(self) -> None:
        pr = self.evidence["candidate_evidence_pr"]
        self.assertEqual(pr["number"], 92)
        self.assertEqual(
            pr["head_sha"], "08ddddca5effac0f416b68ac2f4c07cdec99dfb2"
        )
        self.assertIs(pr["merge_authorized"], False)
        self.assertEqual(
            pr["disposition"], "CLOSE_WITHOUT_MERGE_AFTER_GOVERNANCE_REGISTRATION"
        )

    def test_accepted_run_and_artifact_are_frozen(self) -> None:
        run = self.evidence["accepted_run"]
        self.assertEqual(run["run_id"], 30827493788)
        self.assertEqual(
            run["head_sha"], "08ddddca5effac0f416b68ac2f4c07cdec99dfb2"
        )
        self.assertEqual(run["conclusion"], "SUCCESS")
        self.assertEqual(run["artifact_id"], 8861519922)
        self.assertEqual(
            run["artifact_digest"],
            "sha256:d2146e772b676e01f54be4d134931d66ea96a845da59fe3e0c5806bfa3c582d",
        )

    def test_failed_contract_iterations_are_not_data_failures(self) -> None:
        rows = self.evidence["failed_contract_iterations"]
        self.assertEqual([row["run_id"] for row in rows], [30826748684, 30827069588])
        self.assertTrue(
            all(row["candidate_parser_or_data_failure"] is False for row in rows)
        )
        self.assertIn("TIE_VALUE_CONFLICT", rows[0]["reason"])
        self.assertIn("1,051,778-row", rows[1]["reason"])

    def test_full_basis_accounting_and_non_regression_are_exact(self) -> None:
        result = self.evidence["full_basis_result"]
        self.assertIs(result["pass"], True)
        self.assertEqual(result["source_document_rows"], 121354)
        self.assertEqual(result["candidate_document_rows"], 121354)
        self.assertEqual(result["source_numeric_rows"], 1051793)
        self.assertEqual(result["candidate_numeric_rows"], 1051799)
        self.assertEqual(result["source_document_errors"], 1373)
        self.assertEqual(result["candidate_document_errors"], 1371)
        self.assertEqual(result["document_error_reduction"], 2)
        self.assertEqual(result["source_unresolved_ties"], 1290)
        self.assertEqual(result["candidate_unresolved_ties"], 1288)
        self.assertEqual(result["unresolved_tie_reduction"], 2)
        self.assertEqual(result["target_count"], 2)
        self.assertEqual(result["target_numeric_rows"], 6)
        self.assertEqual(result["non_target_document_rows"], 121352)
        self.assertIs(result["non_target_document_exact_equal"], True)
        self.assertEqual(result["existing_numeric_rows"], 1051793)
        self.assertIs(result["existing_numeric_exact_equal"], True)
        self.assertEqual(result["stable_numeric_field_count"], 22)
        self.assertIs(result["non_balance_values_promoted"], False)
        self.assertEqual(result["final_data_verdict"], "FAIL_CLOSED")

    def test_complete_and_inherited_numeric_semantic_scopes_are_distinct(self) -> None:
        scope = self.evidence["numeric_semantic_identity_scope"]
        self.assertEqual(scope["full_v17_27_rows"], 1051793)
        self.assertEqual(
            scope["full_v17_27_semantic_sha256"],
            "bcb154cc4d80a81acd409e64dc35c2902a5aeb37726b313df936717caf400672",
        )
        self.assertEqual(scope["candidate_existing_rows"], 1051793)
        self.assertEqual(
            scope["candidate_existing_semantic_sha256"],
            scope["full_v17_27_semantic_sha256"],
        )
        self.assertEqual(scope["inherited_pre_v17_27_rows"], 1051778)
        self.assertEqual(
            scope["inherited_pre_v17_27_semantic_sha256"],
            "05b914b03dbcc23d3f6eca560189afbfe6ea427913f9cf1380fa09cdea6aa8d7",
        )
        self.assertEqual(scope["v17_27_added_rows"], 15)
        self.assertIs(scope["populations_must_not_be_interchanged"], True)
        self.assertNotEqual(
            scope["full_v17_27_semantic_sha256"],
            scope["inherited_pre_v17_27_semantic_sha256"],
        )

    def test_exact_target_values_and_explicit_equity_are_frozen(self) -> None:
        targets = self.evidence["targets"]
        self.assertEqual(set(targets), {"1207621057", "1209825769"})
        expected = {
            "1207621057": {
                "TOTAL_ASSETS": "5470381065.66",
                "TOTAL_LIABILITIES": "2220814468.73",
                "TOTAL_EQUITY": "3249566596.93",
            },
            "1209825769": {
                "TOTAL_ASSETS": "1615699540.62",
                "TOTAL_LIABILITIES": "312375993.81",
                "TOTAL_EQUITY": "1303323546.81",
            },
        }
        for aid, values in expected.items():
            self.assertEqual(targets[aid]["current_values"], values)
            self.assertEqual(targets[aid]["current_identity_residual_cny"], "0.00")
            self.assertEqual(targets[aid]["prior_identity_residual_cny"], "0.00")
            self.assertIs(targets[aid]["explicit_equity_pdf_text"], True)
            self.assertIs(
                targets[aid]["equity_value_inferred_as_assets_minus_liabilities"],
                False,
            )

    def test_output_and_independent_verification_identities_are_frozen(self) -> None:
        hashes = self.evidence["output_hashes"]
        self.assertEqual(
            hashes["candidate_documents_gzip_sha256"],
            "818f08602792dec73c4f6c84e9dd41e8633e7f4d56edecc2e0336e71d898491c",
        )
        self.assertEqual(
            hashes["candidate_values_gzip_sha256"],
            "960926aa46e01182d30d97a552f674002f09303f73f142645374ba1a6116af65",
        )
        self.assertEqual(
            hashes["candidate_report_json_sha256"],
            "42fd39956ea3c2dafba98b4d5c1697c15a797099011b4d8ed531cead264e4b21",
        )
        independent = self.evidence["independent_verification"]
        self.assertEqual(independent["source_rows_missing_from_candidate"], 0)
        self.assertEqual(independent["candidate_extra_numeric_rows"], 6)
        self.assertEqual(independent["non_target_document_exact_equal_count"], 121352)
        self.assertEqual(
            independent["changed_announcement_ids"],
            ["1207621057", "1209825769"],
        )
        self.assertIs(independent["numeric_raw_row_multiset_compared"], True)
        self.assertEqual(independent["errors"], [])

    def test_candidate_promotion_and_project_unlock_remain_forbidden(self) -> None:
        boundaries = self.evidence["hard_boundaries"]
        for key in (
            "formal_parser_changed",
            "runtime_authority_changed",
            "production_data_changed",
            "trained_model_changed",
            "live_configuration_changed",
            "source_policy_changed",
            "point_in_time_policy_changed",
            "issuer_gate_changed",
            "accounting_tolerance_changed",
            "ocr_enabled",
            "fuzzy_alias_matching_enabled",
            "equity_inference_enabled",
            "candidate_promotion_authorized",
            "main_changed",
        ):
            self.assertIs(boundaries[key], False, key)
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)


if __name__ == "__main__":
    unittest.main()
