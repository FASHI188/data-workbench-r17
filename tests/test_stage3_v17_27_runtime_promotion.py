from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

import extract_stage3_financial_pdf_values_v17 as extractor
import stage3_financial_pdf_parser_v19 as parser


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MANIFEST = ROOT / "governance/stage3_s3g1j_runtime_manifest.json"
ACTIVATION_MANIFEST = ROOT / "governance/stage3_workflow_activation_manifest.json"
CANDIDATE_EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_27_candidate_safety.json"
FULL_FINAL_EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_27_full_final.json"
CANDIDATE_ONE_SHOT = (
    ROOT / ".github/workflows/stage3-s3g1j-v17-27-normal-equity-candidate-safety.yml"
)
FULL_FINAL_ONE_SHOT = (
    ROOT / ".github/workflows/stage3-s3g1j-v17-27-full-final-acceptance.yml"
)


class _Digest:
    def __init__(self, value: str) -> None:
        self.value = value

    def hexdigest(self) -> str:
        return self.value


class V1727RuntimePromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
        cls.activation = json.loads(ACTIVATION_MANIFEST.read_text(encoding="utf-8"))
        cls.candidate = json.loads(CANDIDATE_EVIDENCE.read_text(encoding="utf-8"))
        cls.full_final = json.loads(FULL_FINAL_EVIDENCE.read_text(encoding="utf-8"))

    def test_formal_runtime_manifest_is_v17_27_and_fail_closed(self) -> None:
        self.assertEqual(self.runtime["schema_version"], 9)
        previous = self.runtime["previous_manifest"]
        self.assertEqual(previous["schema_version"], 8)
        self.assertEqual(
            previous["source_head_sha"],
            "cd8495e3243e69437cf85ec9c1adf1422b958094",
        )
        self.assertEqual(
            previous["git_blob_sha"],
            "2bb1d4f7d512a5c2eab14b0894b25413e4cd334b",
        )
        authority = self.runtime["current_production_authority"]
        self.assertEqual(authority["generation"], "V17.27")
        self.assertEqual(
            authority["status"], "FULL_BASIS_EXECUTION_ACCEPTED_FAIL_CLOSED"
        )
        self.assertIs(authority["runtime_promotion"]["full_basis_execution_pending"], False)
        acceptance = authority["full_basis_acceptance"]
        self.assertEqual(acceptance["run"], 30806818977)
        self.assertEqual(acceptance["artifact_id"], 8854139999)
        self.assertEqual(
            acceptance["artifact_digest"],
            "sha256:410e257d7a3ada353926970f806abc3e970e5638f55c1dec7b47c71c57777721",
        )
        self.assertIs(acceptance["execution_pass"], True)
        self.assertIs(acceptance["independent_artifact_recheck_pass"], True)
        self.assertEqual(acceptance["document_error_count"], 1373)
        self.assertEqual(acceptance["unresolved_tie_count"], 1290)
        self.assertEqual(acceptance["numeric_observation_count"], 1051793)
        self.assertEqual(acceptance["final_data_verdict"], "FAIL_CLOSED")

        formal = self.runtime["formal_runtime"]
        self.assertEqual(formal["runtime_generation"], "V17.27")
        self.assertEqual(formal["shard_gate"], extractor.SHARD_GATE)
        self.assertEqual(formal["extractor_method"], extractor.METHOD)
        self.assertEqual(formal["parser_method"], parser.METHOD)
        self.assertEqual(formal["methodology_version"], parser.METHODOLOGY_VERSION)
        self.assertEqual(
            self.runtime["production_final_status"],
            "FULL_BASIS_EXECUTION_ACCEPTED_FAIL_CLOSED",
        )
        self.assertEqual(
            self.runtime["project_status"],
            {
                "stage3": "NOT_READY",
                "stage4": "LOCKED",
                "alpha_training": "NOT_ALLOWED",
                "live_signals": "NOT_ALLOWED",
                "main_changed": False,
            },
        )

    def test_last_completed_full_basis_is_v17_27(self) -> None:
        full = self.runtime["full_basis_last_completed_final"]
        self.assertEqual(full["generation"], "V17.27")
        self.assertEqual(full["run"], 30806818977)
        self.assertEqual(full["document_rows"], 121354)
        self.assertEqual(full["numeric_observations"], 1051793)
        self.assertEqual(full["document_error_count"], 1373)
        self.assertEqual(full["unresolved_tie_count"], 1290)
        self.assertEqual(full["target_numeric_rows"], 15)
        self.assertEqual(full["unexpected_regression_count"], 0)
        self.assertEqual(full["verdict"], "FAIL_CLOSED")
        completed = self.runtime["next_full_basis_required"]
        self.assertEqual(completed["generation"], "V17.27")
        self.assertEqual(completed["status"], "COMPLETED_AND_ACCEPTED")
        self.assertIs(completed["expected_values_are_not_yet_production_acceptance"], False)

    def test_exact_target_scope_and_evidence_are_frozen(self) -> None:
        expected_ids = {
            "1200907104",
            "1201708762",
            "1202195310",
            "1202774611",
            "1203358200",
        }
        self.assertEqual(
            {target["announcement_id"] for target in parser.TARGETS.values()},
            expected_ids,
        )
        self.assertEqual(set(self.runtime["v17_27_exact_source_gates"]["targets"]), expected_ids)
        self.assertEqual(set(self.candidate["exact_source_targets"]), expected_ids)
        self.assertEqual(self.full_final["full_basis_result"]["target_numeric_rows"], 15)
        self.assertEqual(self.full_final["full_basis_result"]["document_error_count"], 1373)
        self.assertEqual(self.full_final["full_basis_result"]["unresolved_tie_count"], 1290)
        self.assertIs(self.full_final["numeric_non_regression"]["pass"], True)
        self.assertIs(
            self.full_final["full_basis_result"]["non_balance_target_concepts_promoted"],
            False,
        )
        self.assertEqual(
            self.runtime["v17_27_exact_source_gates"]["excluded_fail_closed_announcement_ids"],
            ["1204077386", "1205543437"],
        )

    def test_non_target_output_is_exactly_inherited(self) -> None:
        inherited = {
            "parser_version": "V17_26_EXACT_SOURCE_BALANCE_ONLY_PRODUCTION",
            "observations": {"TOTAL_ASSETS": {"status": "NOT_FOUND"}},
            "validation_errors": ["kept-fail-closed"],
        }
        expected = copy.deepcopy(inherited)
        with mock.patch.object(
            parser.candidate, "parse_pdf_bytes", return_value=copy.deepcopy(inherited)
        ):
            actual = parser.parse_pdf_bytes(b"not-an-allowlisted-source", "2020-03-31")
        self.assertEqual(actual, expected)

    def test_target_candidate_is_promoted_without_value_broadening(self) -> None:
        digest, target = next(iter(parser.TARGETS.items()))
        observations = {
            concept: {
                "concept": concept,
                "status": "FOUND",
                "normalized_cny_value": target["values"][concept],
                "extraction_scope": "V17_27_EXACT_SOURCE_NORMAL_EQUITY_IDENTITY_CANDIDATE",
            }
            for concept in parser.ALLOWED_CONCEPTS
        }
        observations["NET_PROFIT"] = {
            "status": "NOT_FOUND",
            "reason": "V17_27_CANDIDATE_UNVALIDATED_NON_BALANCE_CONCEPT",
        }
        accepted = {
            "parser_version": parser.candidate.METHOD,
            "tier1_found": 0,
            "tier2_found": 3,
            "validation_errors": [],
            "observations": observations,
            "balance_sheet_block": {
                "candidate_only": True,
                "exact_source_sha256": digest,
                "column_role_gate_pass": True,
                "identity_relative_error": "0",
                "identity_residual_cny": "0.00",
                "normal_equity_alias": "所有者权益合计",
                "damaged_equity_alias_required": False,
                "production_runtime_generation": "V17.26",
                "candidate_generation": "V17.27",
            },
        }
        with mock.patch.object(
            parser.hashlib, "sha256", return_value=_Digest(digest)
        ), mock.patch.object(
            parser.candidate, "parse_pdf_bytes", return_value=copy.deepcopy(accepted)
        ):
            actual = parser.parse_pdf_bytes(b"synthetic-target", target["economic_date"])
        self.assertEqual(actual["parser_version"], parser.METHOD)
        self.assertEqual(
            {
                concept
                for concept, row in actual["observations"].items()
                if row.get("status") == "FOUND"
            },
            set(parser.ALLOWED_CONCEPTS),
        )
        self.assertIs(actual["balance_sheet_block"]["candidate_only"], False)
        self.assertIs(actual["balance_sheet_block"]["candidate_safety_promoted"], True)
        self.assertEqual(actual["balance_sheet_block"]["formal_runtime_generation"], "V17.27")

    def test_activation_manifest_and_one_shot_retirement(self) -> None:
        self.assertEqual(self.activation["schema_version"], 11)
        accepted = self.activation["accepted_production_runtime"]
        self.assertEqual(accepted["generation"], "V17.27")
        self.assertEqual(accepted["runtime_manifest_schema"], 9)
        self.assertIs(accepted["full_basis_execution_pending"], False)
        self.assertEqual(accepted["last_completed_full_basis_generation"], "V17.27")
        self.assertEqual(accepted["last_completed_full_basis_run"], 30806818977)
        self.assertEqual(accepted["data_verdict"], "FAIL_CLOSED")
        self.assertFalse(CANDIDATE_ONE_SHOT.exists())
        self.assertFalse(FULL_FINAL_ONE_SHOT.exists())
        boundaries = self.activation["hard_boundaries"]
        self.assertIs(boundaries["v17_27_full_basis_execution_pending"], False)
        self.assertEqual(boundaries["remaining_document_errors"], 1373)
        self.assertEqual(boundaries["remaining_unresolved_ties"], 1290)
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["committed_production_data_changed"], False)
        self.assertIs(boundaries["trained_model_changed"], False)
        self.assertIs(boundaries["main_changed"], False)


if __name__ == "__main__":
    unittest.main()
