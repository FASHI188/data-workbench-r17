from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_29_production_promotion_safety.json"


class V1729ProductionPromotionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.e = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_exact_run_and_artifact(self) -> None:
        run = self.e["accepted_run"]
        self.assertEqual(run["run_id"], 31311296836)
        self.assertEqual(run["head_sha"], "4ea4ac01bcca3e580d73fc37378c2658df8f4b28")
        self.assertEqual(run["artifact_id"], 9037500964)
        self.assertEqual(run["artifact_digest"], "sha256:967727cf95d9cd5d923e4f59f9cbedfe3e17599ceb31a1df06fa607ab75c4d12")
        self.assertEqual(run["conclusion"], "SUCCESS")

    def test_full_basis_population_and_ties(self) -> None:
        r = self.e["full_basis_result"]
        self.assertEqual((r["source_document_rows"], r["promotion_document_rows"]), (121354, 121354))
        self.assertEqual((r["source_numeric_rows"], r["promotion_numeric_rows"]), (1051799, 1051820))
        self.assertEqual((r["source_document_errors"], r["promotion_document_errors"]), (1371, 1364))
        self.assertEqual((r["source_unresolved_ties"], r["promotion_unresolved_ties"]), (1288, 1281))
        self.assertEqual(r["source_tie_taxonomy"], {"TIE_SOURCE_INCOMPLETE": 1274, "TIE_VALUE_CONFLICT": 14})
        self.assertEqual(r["promotion_tie_taxonomy"], {"TIE_SOURCE_INCOMPLETE": 1267, "TIE_VALUE_CONFLICT": 14})

    def test_non_target_and_candidate_semantic_non_regression(self) -> None:
        r = self.e["full_basis_result"]
        self.assertEqual(r["non_target_document_rows"], 121347)
        self.assertIs(r["non_target_document_exact_equal"], True)
        self.assertIs(r["existing_numeric_exact_equal"], True)
        self.assertIs(r["candidate_target_document_semantic_equal"], True)
        self.assertIs(r["candidate_target_numeric_semantic_equal"], True)
        self.assertEqual(r["candidate_target_document_semantic_sha256"], r["promotion_target_document_semantic_sha256"])
        self.assertEqual(r["candidate_target_numeric_semantic_sha256"], r["promotion_target_numeric_semantic_sha256"])

    def test_exact_target_distribution_and_identity(self) -> None:
        r = self.e["full_basis_result"]
        ids = ["1215186538","1219426855","1219792633","1219840508","1219879687","1220087244","1221006100"]
        self.assertEqual(r["target_announcement_ids"], ids)
        self.assertEqual(r["target_numeric_distribution"], {aid: 3 for aid in ids})
        self.assertEqual(r["target_concept_distribution"], {"TOTAL_ASSETS": 7, "TOTAL_LIABILITIES": 7, "TOTAL_EQUITY": 7})
        self.assertEqual(r["split_equity_pattern"], "SPLIT_LABEL_1_BEFORE_1_AFTER_AMOUNT")
        self.assertIs(r["all_current_identity_residuals_zero"], True)
        self.assertIs(r["all_prior_identity_residuals_zero"], True)
        self.assertEqual(r["accounting_tolerance"], "0.005")

    def test_independent_implementation_and_recheck(self) -> None:
        implementation = self.e["independent_implementation"]
        self.assertIs(implementation["imports_closed_candidate_implementation"], False)
        self.assertIs(implementation["reimplements_exact_source_rule_on_formal_v17_28"], True)
        self.assertIs(implementation["accepted_candidate_artifact_used_as_external_gold_standard"], True)
        verification = self.e["independent_verification"]
        self.assertEqual(verification["non_target_document_difference_count"], 0)
        self.assertEqual(verification["source_promotion_existing_numeric_difference_count"], 0)
        self.assertEqual(verification["promotion_target_numeric_rows"], 21)
        self.assertEqual(verification["errors"], [])

    def test_output_hashes_are_frozen(self) -> None:
        hashes = self.e["output_hashes"]
        self.assertEqual(hashes["promotion_documents_gzip_sha256"], "4e5d853ae9ba16dbfd6f0ca11e2310f00539ad18c8dfdc2b654f601ccf876e40")
        self.assertEqual(hashes["promotion_values_gzip_sha256"], "2bfdd607580f474a5d5b1c1acb80468bd31906ebdc1235c798c58e12afd30fef")
        self.assertEqual(hashes["promotion_safety_report_sha256"], "adcf8ad787957e1d9fba1961218de5919bbd202d33c51120dc811b0ed1de25fe")

    def test_runtime_remains_unpromoted(self) -> None:
        h = self.e["hard_boundaries"]
        self.assertIs(h["production_promotion_safety_machine_accepted"], True)
        self.assertEqual(h["formal_runtime_generation"], "V17.28")
        self.assertIs(h["runtime_promotion_authorized"], False)
        self.assertIs(h["formal_runtime_changed"], False)
        self.assertIs(h["runtime_authority_changed"], False)
        self.assertIs(h["production_data_changed"], False)
        self.assertIs(h["ocr_enabled"], False)
        self.assertIs(h["equity_inferred_as_assets_minus_liabilities"], False)
        self.assertIs(h["fuzzy_alias_matching_enabled"], False)
        self.assertEqual(h["stage3_status"], "NOT_READY")
        self.assertEqual(h["s3g1j_data_verdict"], "FAIL_CLOSED")
        self.assertIs(h["stage4_alpha_live_locked"], True)
        self.assertIs(h["main_changed"], False)
        self.assertIs(h["merge_to_main_authorized"], False)


if __name__ == "__main__":
    unittest.main()
