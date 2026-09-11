from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_29_cross_page_production_promotion_safety.json"


class CrossPageProductionPromotionSafetyEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.e = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_exact_diagnostic_and_artifact(self) -> None:
        self.assertEqual(self.e["diagnostic_pr"]["number"], 121)
        self.assertEqual(self.e["diagnostic_pr"]["head_sha"], "2cd84a81b3d4f291aae2ae2cb5b6daf8629ad030")
        self.assertIs(self.e["diagnostic_pr"]["closed_without_merge"], True)
        run=self.e["accepted_run"]
        self.assertEqual(run["run_id"],31452374012)
        self.assertEqual(run["artifact_id"],9086776910)
        self.assertEqual(run["artifact_digest"],"sha256:d3bb089c7e0524a39b62016f6b6b41539aec99894b874c2940678bee24edebc4")

    def test_full_shadow_basis_is_exactly_two_target_delta(self) -> None:
        r=self.e["shadow_full_basis_result"]
        self.assertEqual(r["document_rows"],121354)
        self.assertEqual(r["numeric_rows"],1051826)
        self.assertEqual(r["document_errors"],1362)
        self.assertEqual(r["unresolved_ties"],1279)
        self.assertEqual(r["unresolved_tie_taxonomy"],{"TIE_SOURCE_INCOMPLETE":1265,"TIE_VALUE_CONFLICT":14})
        self.assertEqual(r["target_numeric_rows_added"],6)
        self.assertEqual(r["target_numeric_distribution"],{"1223347318":3,"1223407043":3})
        self.assertEqual(r["non_target_document_rows"],121352)
        self.assertIs(r["non_target_document_exact_equal"],True)
        self.assertEqual(r["existing_numeric_rows"],1051820)
        self.assertIs(r["existing_numeric_exact_equal"],True)
        self.assertEqual(r["final_data_verdict"],"FAIL_CLOSED")

    def test_output_hashes_are_frozen(self) -> None:
        h=self.e["output_identities"]
        self.assertEqual(h["documents_gzip_sha256"],"4710d20d2d4eb19d003ee64aa97f789e3eff79ce464e955ba568fe8d81f499d8")
        self.assertEqual(h["documents_plaintext_sha256"],"c48f5d1c2d27395486e731f75d77afdae5fc61186ec7049aa03ec746ef38beef")
        self.assertEqual(h["values_gzip_sha256"],"5a4e9e4c901419886f4eb932653314ccebacdb261ec39f516a11bfd81be1904d")
        self.assertEqual(h["values_plaintext_sha256"],"e7ee38b910cae7de91ba5f0ee7c6c4cf77a62a943b512291151252756ada9d73")
        self.assertEqual(h["report_sha256"],"854d79ff1a826b13579ef5014d666994f7b5520f5a0c35dfc7f3d93f5eb41a16")

    def test_target_rows_and_identities_are_exact(self) -> None:
        rows={x["announcement_id"]:x for x in self.e["accepted_target_shadow_rows"]}
        self.assertEqual(set(rows),{"1223347318","1223407043"})
        for row in rows.values():
            self.assertEqual(row["document_status"],"PASS")
            self.assertEqual(row["tie_resolution"],"SINGLE_CANONICAL")
            self.assertEqual(row["tier2_found"],3)
            self.assertEqual(row["numeric_observations"],3)
            self.assertEqual(set(row["values"]),{"TOTAL_ASSETS","TOTAL_LIABILITIES","TOTAL_EQUITY"})
            self.assertEqual(row["current_identity_residual_cny"],"0.00")
            self.assertEqual(row["prior_identity_residual_cny"],"0.00")

    def test_no_runtime_or_policy_authority(self) -> None:
        b=self.e["method_boundaries"]
        self.assertIs(b["formal_parser_changed"],False)
        self.assertIs(b["runtime_authority_changed"],False)
        self.assertIs(b["production_data_changed"],False)
        self.assertIs(b["ocr_enabled"],False)
        self.assertIs(b["fuzzy_alias_matching_enabled"],False)
        self.assertIs(b["equity_inferred_from_assets_minus_liabilities"],False)
        self.assertIs(b["source_policy_relaxed"],False)
        self.assertIs(b["point_in_time_policy_relaxed"],False)
        self.assertIs(b["issuer_gate_relaxed"],False)
        self.assertEqual(b["accounting_tolerance"],"0.005")
        self.assertIs(b["accounting_tolerance_relaxed"],False)
        a=self.e["authorization"]
        self.assertIs(a["production_promotion_safety_pass"],True)
        self.assertIs(a["runtime_wrapper_candidate_experiment_eligible"],True)
        self.assertEqual(a["formal_runtime_generation_remains"],"V17.29")
        self.assertEqual(a["proposed_next_generation_label"],"V17.30_NOT_AUTHORIZED")
        self.assertIs(a["formal_parser_implementation_authorized"],False)
        self.assertIs(a["runtime_promotion_authorized"],False)
        self.assertIs(a["fresh_full_basis_execution_authorized"],False)
        self.assertIs(a["stage3_gate_pass"],False)


if __name__ == "__main__":
    unittest.main()
