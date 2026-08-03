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
EVIDENCE_MANIFEST = ROOT / "governance/stage3_s3g1j_v17_27_candidate_safety.json"
ONE_SHOT_WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "stage3-s3g1j-v17-27-normal-equity-candidate-safety.yml"
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
        cls.evidence = json.loads(EVIDENCE_MANIFEST.read_text(encoding="utf-8"))

    def test_formal_runtime_manifest_is_v17_27_and_fail_closed(self) -> None:
        self.assertEqual(self.runtime["schema_version"], 8)
        previous = self.runtime["previous_manifest"]
        self.assertEqual(previous["schema_version"], 7)
        self.assertEqual(
            previous["source_head_sha"],
            "30ab382cfc83ed9df4e551dac95fa07291bb91e0",
        )
        self.assertEqual(
            previous["git_blob_sha"],
            "382eab41d7bf42ea26471f8a93d4c17343804c4e",
        )
        authority = self.runtime["current_production_authority"]
        self.assertEqual(authority["generation"], "V17.27")
        self.assertEqual(
            authority["status"],
            "RUNTIME_PROMOTED_PENDING_FULL_BASIS_EXECUTION_FAIL_CLOSED",
        )
        acceptance = authority["candidate_acceptance"]
        self.assertEqual(acceptance["run"], 30747664549)
        self.assertEqual(acceptance["artifact_id"], 8833408494)
        self.assertEqual(
            acceptance["artifact_digest"], parser.CANDIDATE_ARTIFACT_DIGEST
        )
        self.assertIs(acceptance["execution_pass"], True)
        self.assertIs(acceptance["independent_artifact_recheck_pass"], True)
        self.assertEqual(acceptance["candidate_document_errors"], 1373)
        self.assertEqual(acceptance["candidate_numeric_rows"], 1051793)
        self.assertEqual(acceptance["candidate_data_verdict"], "FAIL_CLOSED")

        formal = self.runtime["formal_runtime"]
        self.assertEqual(formal["runtime_generation"], "V17.27")
        self.assertEqual(formal["shard_gate"], extractor.SHARD_GATE)
        self.assertEqual(
            formal["extractor_path"],
            "scripts/extract_stage3_financial_pdf_values_v17.py",
        )
        self.assertEqual(formal["extractor_method"], extractor.METHOD)
        self.assertEqual(
            formal["parser_path"], "scripts/stage3_financial_pdf_parser_v19.py"
        )
        self.assertEqual(formal["parser_method"], parser.METHOD)
        self.assertEqual(formal["methodology_version"], parser.METHODOLOGY_VERSION)
        self.assertEqual(
            self.runtime["production_final_status"],
            "RUNTIME_PROMOTED_PENDING_FULL_BASIS_EXECUTION_FAIL_CLOSED",
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

    def test_last_completed_full_basis_remains_v17_26(self) -> None:
        full = self.runtime["full_basis_last_completed_final"]
        self.assertEqual(full["generation"], "V17.26")
        self.assertEqual(full["run"], 30733013665)
        self.assertEqual(full["document_rows"], 121354)
        self.assertEqual(full["numeric_observations"], 1051778)
        self.assertEqual(full["document_error_count"], 1378)
        self.assertEqual(full["unresolved_tie_count"], 1295)
        self.assertEqual(full["verdict"], "FAIL_CLOSED")
        pending = self.runtime["next_full_basis_required"]
        self.assertEqual(pending["generation"], "V17.27")
        self.assertEqual(pending["status"], "PENDING_MACHINE_EXECUTION_AND_ACCEPTANCE")
        self.assertIs(pending["expected_values_are_not_yet_production_acceptance"], True)

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
        self.assertEqual(
            set(self.runtime["v17_27_exact_source_gates"]["targets"]), expected_ids
        )
        self.assertEqual(set(self.evidence["exact_source_targets"]), expected_ids)
        self.assertEqual(
            self.evidence["accepted_run"]["artifact_digest"],
            parser.CANDIDATE_ARTIFACT_DIGEST,
        )
        self.assertEqual(self.evidence["result"]["target_numeric_rows"], 15)
        self.assertEqual(self.evidence["result"]["candidate_document_errors"], 1373)
        self.assertIs(self.evidence["result"]["existing_numeric_rows_exact_equal"], True)
        self.assertIs(self.evidence["result"]["non_balance_values_promoted"], False)
        self.assertEqual(
            self.runtime["v17_27_exact_source_gates"][
                "excluded_fail_closed_announcement_ids"
            ],
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
                "extraction_scope": (
                    "V17_27_EXACT_SOURCE_NORMAL_EQUITY_IDENTITY_CANDIDATE"
                ),
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
        self.assertEqual(actual["tier1_found"], 0)
        self.assertEqual(actual["tier2_found"], 3)
        self.assertEqual(
            {
                concept
                for concept, row in actual["observations"].items()
                if row.get("status") == "FOUND"
            },
            set(parser.ALLOWED_CONCEPTS),
        )
        for concept in parser.ALLOWED_CONCEPTS:
            self.assertEqual(
                actual["observations"][concept]["normalized_cny_value"],
                target["values"][concept],
            )
            self.assertEqual(
                actual["observations"][concept]["extraction_scope"],
                parser.PRODUCTION_SCOPE,
            )
        block = actual["balance_sheet_block"]
        self.assertIs(block["candidate_only"], False)
        self.assertIs(block["candidate_safety_promoted"], True)
        self.assertEqual(block["formal_runtime_generation"], "V17.27")
        self.assertEqual(block["production_runtime_generation"], "V17.27")
        self.assertEqual(block["candidate_acceptance_run"], 30747664549)
        self.assertEqual(
            block["candidate_acceptance_artifact_digest"],
            parser.CANDIDATE_ARTIFACT_DIGEST,
        )

    def test_activation_manifest_and_one_shot_retirement(self) -> None:
        self.assertEqual(self.activation["schema_version"], 10)
        accepted = self.activation["accepted_production_runtime"]
        self.assertEqual(accepted["generation"], "V17.27")
        self.assertEqual(accepted["runtime_manifest_schema"], 8)
        self.assertIs(accepted["full_basis_execution_pending"], True)
        self.assertEqual(accepted["data_verdict"], "FAIL_CLOSED")
        self.assertIn(
            ".github/workflows/stage3-s3g1j-v17-27-evidence-contract.yml",
            self.activation["active_stage3_workflows"],
        )
        one_shot = (
            ".github/workflows/"
            "stage3-s3g1j-v17-27-normal-equity-candidate-safety.yml"
        )
        self.assertNotIn(one_shot, self.activation["active_stage3_workflows"])
        self.assertIn(one_shot, self.activation["removed_one_shot_workflows"])
        self.assertFalse(ONE_SHOT_WORKFLOW.exists())
        boundaries = self.activation["hard_boundaries"]
        self.assertIs(boundaries["v17_27_full_basis_execution_pending"], True)
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["committed_production_data_changed"], False)
        self.assertIs(boundaries["trained_model_changed"], False)
        self.assertIs(boundaries["main_changed"], False)


if __name__ == "__main__":
    unittest.main()
