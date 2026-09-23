from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_28_split_equity_diagnostic.json"


class V1728SplitEquityEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_evidence_pr_is_non_merge_diagnostic(self) -> None:
        pr = self.evidence["evidence_pr"]
        self.assertEqual(pr["number"], 90)
        self.assertEqual(
            pr["head_sha"], "5c3bfff81a7518c6427030677bd1d4b288104e1e"
        )
        self.assertIs(pr["merge_authorized"], False)
        self.assertEqual(
            pr["disposition"], "CLOSE_WITHOUT_MERGE_AFTER_GOVERNANCE_REGISTRATION"
        )

    def test_machine_run_and_artifact_are_frozen(self) -> None:
        run = self.evidence["accepted_run"]
        self.assertEqual(run["run_id"], 30824927082)
        self.assertEqual(
            run["head_sha"], "5c3bfff81a7518c6427030677bd1d4b288104e1e"
        )
        self.assertEqual(run["conclusion"], "SUCCESS")
        self.assertEqual(run["artifact_id"], 8860412443)
        self.assertEqual(
            run["artifact_digest"],
            "sha256:287d37e2d5972e0d8cdfb36fd987a7c7cbf239b32d6fdabd96e26da27064565d",
        )
        self.assertEqual(
            run["report_sha256"],
            "5b2610f67f3f15113a62c2172eccbbf8df362d75263ac6049cd335aae5bc49d6",
        )

    def test_failed_iteration_is_not_misreported_as_data_failure(self) -> None:
        failed = self.evidence["failed_contract_iteration"]
        self.assertEqual(failed["run_id"], 30824605254)
        self.assertEqual(failed["conclusion"], "FAILURE")
        self.assertIs(failed["data_or_parser_failure"], False)
        self.assertIn("exact statement date twice", failed["reason"])

    def test_source_authority_and_exact_population_are_frozen(self) -> None:
        source = self.evidence["locked_source_authority"]
        self.assertEqual(source["runtime_generation"], "V17.27")
        self.assertEqual(source["full_basis_run"], 30806818977)
        self.assertEqual(source["full_basis_artifact_id"], 8854139999)
        self.assertEqual(
            source["documents_gzip_sha256"],
            "c2abe07baaa76efb80a30cfdd4e762ad07814f6aa795a92b9c0504f7944ab99a",
        )
        population = self.evidence["diagnostic_population"]
        self.assertEqual(population["target_count"], 2)
        self.assertEqual(
            population["target_announcement_ids"], ["1207621057", "1209825769"]
        )
        self.assertIs(population["non_target_documents_authorized"], False)

    def test_target_source_identities_and_split_patterns_are_exact(self) -> None:
        targets = self.evidence["targets"]
        self.assertEqual(set(targets), {"1207621057", "1209825769"})
        first = targets["1207621057"]
        self.assertEqual(
            first["source_sha256"],
            "b2aa4afa67e2b02010d5ba708d4e5fe02138623ff4bc48718c03029111a64568",
        )
        self.assertEqual(first["source_bytes"], 477621)
        self.assertEqual(first["split_pattern"], "LABEL_AND_AMOUNTS_THEN_CONTINUATION")
        self.assertEqual(first["values"]["TOTAL_EQUITY"], ["3249566596.93", "3163797498.46"])
        self.assertEqual(first["asset_equity_column_x0_drift"], ["0E-13", "0E-14"])
        self.assertEqual(first["identity_residual_current"], "0.00")
        self.assertEqual(first["identity_residual_prior"], "0.00")

        second = targets["1209825769"]
        self.assertEqual(
            second["source_sha256"],
            "0bd1da8bdac0aff2a3e99b83adc29e7b60e959c99dd29b8ab88cbda1344b441c",
        )
        self.assertEqual(second["source_bytes"], 633887)
        self.assertEqual(second["split_pattern"], "LABEL_THEN_AMOUNTS_THEN_CONTINUATION")
        self.assertEqual(second["values"]["TOTAL_EQUITY"], ["1303323546.81", "1261570672.73"])
        self.assertEqual(second["asset_equity_column_x0_drift"], ["0E-13", "0E-12"])
        self.assertEqual(second["identity_residual_current"], "0.00")
        self.assertEqual(second["identity_residual_prior"], "0.00")

    def test_diagnostic_contract_requires_explicit_dual_column_evidence(self) -> None:
        contract = self.evidence["diagnostic_contract"]
        self.assertIs(contract["formal_runtime_recovered_before_diagnostic"], False)
        self.assertEqual(
            contract["existing_spatial_candidate_counts_each"],
            {"TOTAL_ASSETS": 3, "TOTAL_LIABILITIES": 1, "TOTAL_EQUITY": 0},
        )
        self.assertIs(contract["formal_group_role_required"], True)
        self.assertIs(contract["expected_period_required"], True)
        self.assertIs(contract["role_local_cny_unit_required"], True)
        self.assertIs(contract["explicit_pdf_equity_required"], True)
        self.assertIs(contract["current_and_prior_columns_required"], True)
        self.assertIs(contract["asset_equity_column_alignment_required"], True)
        self.assertIs(contract["current_and_prior_identity_each_required"], True)
        self.assertEqual(contract["identity_tolerance"], "0.005")
        self.assertIs(contract["equity_value_inferred_as_assets_minus_liabilities"], False)
        self.assertIs(contract["parent_role_fail_closed"], True)
        self.assertIs(contract["non_target_fail_closed"], True)

    def test_hard_boundaries_forbid_promotion(self) -> None:
        boundaries = self.evidence["hard_boundaries"]
        self.assertEqual(boundaries["candidate_generation"], "V17.28_DIAGNOSTIC_ONLY")
        for key in (
            "formal_parser_changed",
            "runtime_authority_changed",
            "production_data_changed",
            "trained_model_changed",
            "source_policy_changed",
            "point_in_time_policy_changed",
            "issuer_gate_changed",
            "accounting_tolerance_changed",
            "ocr_enabled",
            "fuzzy_alias_matching_enabled",
            "equity_inference_enabled",
            "automatic_recovery_authorized",
            "candidate_parser_implementation_authorized",
            "main_changed",
        ):
            self.assertIs(boundaries[key], False, key)
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)


if __name__ == "__main__":
    unittest.main()
