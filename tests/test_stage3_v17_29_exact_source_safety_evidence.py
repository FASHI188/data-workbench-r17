from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_29_exact_source_safety.json"
SAFE_IDS = [
    "1215186538",
    "1219426855",
    "1219792633",
    "1219840508",
    "1219879687",
    "1220087244",
    "1221006100",
]


class V1729ExactSourceSafetyEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_exact_diagnostic_run_and_artifact_are_frozen(self) -> None:
        pr = self.evidence["diagnostic_pr"]
        run = self.evidence["accepted_run"]
        self.assertEqual(pr["number"], 103)
        self.assertEqual(pr["head_sha"], "2fa1ae921059350d20c29bd8c31a3a2a48b4abf5")
        self.assertIs(pr["merge_authorized"], False)
        self.assertEqual(run["run_id"], 31113755244)
        self.assertEqual(run["head_sha"], pr["head_sha"])
        self.assertEqual(run["conclusion"], "SUCCESS")
        self.assertEqual(run["artifact_id"], 8972793068)
        self.assertEqual(
            run["artifact_digest"],
            "sha256:8fa30957758fcbc94fa77214a4a52f3a97335fbf27dda3d44e89afb81c2abf6d",
        )

    def test_full_population_routing_is_exact(self) -> None:
        routing = self.evidence["full_population_routing"]
        self.assertEqual(routing["document_rows"], 121354)
        self.assertEqual(routing["candidate_evidence_rows"], 121985)
        self.assertEqual(
            routing["route_counts"],
            {
                "DELEGATE_FORMAL_V17_28_UNCHANGED": 121347,
                "V17_29_PRE_CANDIDATE_EXACT_SOURCE_DIAGNOSTIC": 7,
            },
        )
        self.assertEqual(
            routing["routing_semantic_sha256"],
            "1fcc01726482afc7a5d08e33b68013140d7344a24b93b2b8953c7475c8e2cc1c",
        )
        self.assertEqual(routing["target_population_match_count"], 7)
        self.assertIs(routing["all_target_population_matches_unique"], True)
        self.assertIs(routing["all_non_targets_delegate_formal_v17_28_unchanged"], True)
        self.assertEqual(routing["formal_existing_target_overlap_count"], 0)

    def test_exact_seven_target_identity_set_is_frozen(self) -> None:
        targets = self.evidence["targets"]
        self.assertEqual([row["announcement_id"] for row in targets], SAFE_IDS)
        self.assertEqual(len({row["source_sha256"] for row in targets}), 7)
        for row in targets:
            self.assertEqual(len(row["source_sha256"]), 64)
            self.assertGreater(row["source_bytes"], 0)
            self.assertGreater(row["page_count"], 0)
            self.assertEqual(row["current_identity_residual"], "0.00")
            self.assertEqual(row["prior_identity_residual"], "0.00")
            self.assertEqual(row["population_match_count"], 1)
            self.assertIs(row["candidate_experiment_eligible"], True)
            self.assertIs(row["candidate_parser_implementation_authorized"], False)

    def test_activation_and_negative_routes_are_fail_closed(self) -> None:
        activation = self.evidence["activation_contract"]
        self.assertEqual(
            activation["identity_fields"],
            ["source_sha256", "source_bytes", "economic_date"],
        )
        self.assertEqual(activation["scope"], "EXACT_ALLOWLIST_ONLY")
        self.assertEqual(
            activation["non_target_behavior"],
            "RETURN_FORMAL_V17_28_OBJECT_UNCHANGED",
        )
        self.assertEqual(activation["mutated_sha_delegated"], 7)
        self.assertEqual(activation["wrong_bytes_delegated"], 7)
        self.assertEqual(activation["wrong_date_delegated"], 7)
        self.assertEqual(activation["accounting_tolerance"], "0.005")

    def test_output_hashes_and_independent_recheck_are_frozen(self) -> None:
        hashes = self.evidence["output_hashes"]
        self.assertEqual(hashes["target_ledger_gzip_sha256"], "1621f7ee78056cebc04c435a267205ced088fcb6163ace7d485991d57fdc9470")
        self.assertEqual(hashes["target_ledger_plaintext_sha256"], "2066886c7eb032d8dd7752d5cc94d06ef78bd435e4ca9a76b863e5e4e8750056")
        self.assertEqual(hashes["contract_json_sha256"], "b8ed3394953c3ae9e8cfe111cb0e9ef57514a80c86940b0becb873404ac9cfc2")
        self.assertEqual(hashes["summary_json_sha256"], "7505ac47be1d83335842fd04768393389917e6ce380539fc5779bf796d2348b8")
        verification = self.evidence["independent_verification"]
        self.assertIs(verification["artifact_downloaded_and_inspected"], True)
        self.assertIs(verification["machine_outputs_byte_equal_local_read_only_reproduction"], True)
        self.assertEqual(verification["target_rows_recounted"], 7)
        self.assertEqual(verification["errors"], [])

    def test_experiment_eligibility_is_not_parser_authorization(self) -> None:
        boundary = self.evidence["authorization_boundary"]
        self.assertIs(boundary["candidate_experiment_eligible"], True)
        self.assertIs(boundary["candidate_parser_implementation_authorized"], False)
        self.assertIs(boundary["candidate_parser_promotion_authorized"], False)
        self.assertIs(boundary["parser_implemented"], False)

    def test_all_project_locks_remain_fail_closed(self) -> None:
        boundary = self.evidence["hard_boundaries"]
        self.assertIs(boundary["diagnostic_only"], True)
        self.assertIs(boundary["formal_parser_changed"], False)
        self.assertIs(boundary["runtime_authority_changed"], False)
        self.assertIs(boundary["production_data_changed"], False)
        self.assertIs(boundary["pdf_binaries_redownloaded"], False)
        self.assertIs(boundary["ocr_enabled"], False)
        self.assertIs(boundary["equity_inference_enabled"], False)
        self.assertIs(boundary["accounting_tolerance_changed"], False)
        self.assertEqual(boundary["stage3_status"], "NOT_READY")
        self.assertIs(boundary["stage4_alpha_live_locked"], True)
        self.assertIs(boundary["main_changed"], False)
        self.assertIs(boundary["merge_to_main_authorized"], False)


if __name__ == "__main__":
    unittest.main()
