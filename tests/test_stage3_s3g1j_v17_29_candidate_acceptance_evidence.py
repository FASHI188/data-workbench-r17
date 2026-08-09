from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_29_candidate_acceptance.json"


class V1729CandidateAcceptanceEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.e = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_exact_candidate_run_and_artifact(self) -> None:
        run = self.e["accepted_run"]
        self.assertEqual(run["run_id"], 31310230656)
        self.assertEqual(run["head_sha"], "51bd3ccc0013c2c9a6a55bbb54a1d82dcbd2974e")
        self.assertEqual(run["artifact_id"], 9037206225)
        self.assertEqual(
            run["artifact_digest"],
            "sha256:fc8ff09522b67df8e8209f7e5d88a0d768ef68987201dbb8087df2b6424bb99c",
        )
        self.assertEqual(run["conclusion"], "SUCCESS")

    def test_exact_population_and_non_regression(self) -> None:
        r = self.e["candidate_result"]
        self.assertEqual(r["source_document_rows"], 121354)
        self.assertEqual(r["candidate_document_rows"], 121354)
        self.assertEqual(r["source_numeric_rows"], 1051799)
        self.assertEqual(r["candidate_numeric_rows"], 1051820)
        self.assertEqual(r["target_numeric_rows"], 21)
        self.assertEqual(r["source_document_errors"], 1371)
        self.assertEqual(r["candidate_document_errors"], 1364)
        self.assertEqual(r["source_unresolved_ties"], 1288)
        self.assertEqual(r["candidate_unresolved_ties"], 1281)
        self.assertEqual(r["non_target_document_rows"], 121347)
        self.assertIs(r["non_target_document_exact_equal"], True)
        self.assertIs(r["existing_numeric_exact_equal"], True)
        self.assertEqual(
            r["source_tie_taxonomy"],
            {"TIE_SOURCE_INCOMPLETE": 1274, "TIE_VALUE_CONFLICT": 14},
        )
        self.assertEqual(
            r["candidate_tie_taxonomy"],
            {"TIE_SOURCE_INCOMPLETE": 1267, "TIE_VALUE_CONFLICT": 14},
        )

    def test_exact_target_population_and_distribution(self) -> None:
        ids = [
            "1215186538",
            "1219426855",
            "1219792633",
            "1219840508",
            "1219879687",
            "1220087244",
            "1221006100",
        ]
        self.assertEqual(self.e["targets"], ids)
        r = self.e["candidate_result"]
        self.assertEqual(r["changed_document_ids"], ids)
        self.assertEqual(r["target_numeric_distribution"], {aid: 3 for aid in ids})
        self.assertEqual(
            r["target_concept_distribution"],
            {"TOTAL_ASSETS": 7, "TOTAL_LIABILITIES": 7, "TOTAL_EQUITY": 7},
        )
        self.assertEqual(r["split_equity_pattern"], "SPLIT_LABEL_1_BEFORE_1_AFTER_AMOUNT")
        self.assertIs(r["all_current_identity_residuals_zero"], True)
        self.assertIs(r["all_prior_identity_residuals_zero"], True)
        self.assertEqual(r["accounting_tolerance"], "0.005")

    def test_geometry_fix_is_narrow_and_fail_closed(self) -> None:
        g = self.e["geometry_closure"]
        self.assertEqual(g["initial_run"], 31309637804)
        self.assertEqual(g["initial_result"], "FAIL_CLOSED")
        self.assertEqual(g["diagnostic_target"], "1215186538")
        self.assertEqual(
            g["observed_exact_sequence"],
            ["所有者权益（或股东权", "EXACT_TWO_COLUMN_EQUITY_AMOUNTS", "益）合计"],
        )
        self.assertIs(g["fuzzy_matching_added"], False)
        self.assertIs(g["global_geometry_tolerance_changed"], False)

    def test_deterministic_internal_output_hashes(self) -> None:
        hashes = self.e["output_hashes"]
        self.assertEqual(
            hashes["candidate_documents_gzip_sha256"],
            "343ef55dc8bcf0eb53e8eda2d77f58ddfc48c5c6d13011d02a12d00bd836179e",
        )
        self.assertEqual(
            hashes["candidate_values_gzip_sha256"],
            "31479f232fa2708b411730aa0e0513892a0e42359f0a0e80f4325af3f8b9de2a",
        )
        self.assertEqual(
            hashes["candidate_safety_report_sha256"],
            "f0eaf3a6529eeba4b6347e2f046fb66ca497a118aa6faaa84b4b7e989307c059",
        )
        repeat = self.e["deterministic_repeat"]
        self.assertEqual(repeat["prior_success_run"], 31309996060)
        self.assertIs(repeat["internal_candidate_files_byte_identical"], True)
        self.assertIs(repeat["transport_digest_is_not_semantic_identity"], True)

    def test_independent_recheck_is_frozen(self) -> None:
        v = self.e["independent_verification"]
        self.assertIs(v["final_artifact_downloaded_and_inspected"], True)
        self.assertIs(v["github_artifact_digest_matches_downloaded_archive"], True)
        self.assertEqual(v["non_target_document_difference_count"], 0)
        self.assertEqual(v["existing_numeric_difference_count"], 0)
        self.assertEqual(v["appended_target_numeric_rows"], 21)
        self.assertEqual(v["review_threads"], 0)
        self.assertEqual(v["review_submissions"], 0)
        self.assertEqual(v["errors"], [])

    def test_authority_remains_fail_closed(self) -> None:
        a = self.e["authorization_boundary"]
        self.assertIs(a["candidate_implementation_machine_accepted"], True)
        self.assertIs(a["candidate_full_basis_non_regression_pass"], True)
        self.assertIs(a["candidate_runtime_promotion_authorized"], False)
        self.assertIs(a["formal_runtime_changed"], False)
        self.assertIs(a["runtime_authority_changed"], False)
        self.assertIs(a["production_data_changed"], False)
        self.assertIs(a["ocr_enabled"], False)
        self.assertIs(a["equity_inferred_as_assets_minus_liabilities"], False)
        self.assertIs(a["fuzzy_alias_matching_enabled"], False)
        self.assertIs(a["source_policy_relaxed"], False)
        self.assertIs(a["point_in_time_policy_relaxed"], False)
        self.assertIs(a["issuer_gate_relaxed"], False)
        self.assertIs(a["accounting_tolerance_changed"], False)
        self.assertEqual(a["stage3_status"], "NOT_READY")
        self.assertEqual(a["s3g1j_data_verdict"], "FAIL_CLOSED")
        self.assertIs(a["stage4_alpha_live_locked"], True)
        self.assertIs(a["main_changed"], False)
        self.assertIs(a["merge_to_main_authorized"], False)


if __name__ == "__main__":
    unittest.main()
