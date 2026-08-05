from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

import stage3_financial_pdf_parser_v19 as parser


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MANIFEST = ROOT / "governance/stage3_s3g1j_runtime_manifest.json"
ACTIVATION_MANIFEST = ROOT / "governance/stage3_workflow_activation_manifest.json"
CANDIDATE_EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_27_candidate_safety.json"
FULL_FINAL_EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_27_full_final.json"


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

    def test_v17_27_is_retained_as_last_completed_full_basis(self) -> None:
        self.assertEqual(self.runtime["schema_version"], 10)
        self.assertEqual(self.runtime["formal_runtime"]["runtime_generation"], "V17.28")
        full = self.runtime["full_basis_last_completed_final"]
        self.assertEqual(full["generation"], "V17.27")
        self.assertEqual(full["run"], 30806818977)
        self.assertEqual(full["artifact_id"], 8854139999)
        self.assertEqual(
            full["artifact_digest"],
            "sha256:410e257d7a3ada353926970f806abc3e970e5638f55c1dec7b47c71c57777721",
        )
        self.assertEqual(full["document_rows"], 121354)
        self.assertEqual(full["numeric_observations"], 1051793)
        self.assertEqual(full["document_error_count"], 1373)
        self.assertEqual(full["unresolved_tie_count"], 1290)
        self.assertEqual(full["target_numeric_rows"], 15)
        self.assertEqual(full["verdict"], "FAIL_CLOSED")

        retained = self.runtime["current_production_authority"]["full_basis_acceptance"]
        self.assertEqual(retained["generation"], "V17.27")
        self.assertEqual(retained["authority_scope"], "LAST_COMPLETED_FULL_BASIS_ONLY")
        self.assertEqual(retained["run"], 30806818977)
        self.assertEqual(retained["final_data_verdict"], "FAIL_CLOSED")

    def test_v17_27_full_final_evidence_remains_immutable(self) -> None:
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
        result = self.full_final["full_basis_result"]
        self.assertEqual(result["target_numeric_rows"], 15)
        self.assertEqual(result["document_error_count"], 1373)
        self.assertEqual(result["unresolved_tie_count"], 1290)
        self.assertIs(self.full_final["numeric_non_regression"]["pass"], True)
        self.assertIs(result["non_balance_target_concepts_promoted"], False)

    def test_v17_27_parser_still_preserves_non_target_output(self) -> None:
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

    def test_v17_27_exact_target_production_behavior_is_retained(self) -> None:
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
        self.assertEqual(actual["balance_sheet_block"]["formal_runtime_generation"], "V17.27")

    def test_activation_manifest_retains_v17_27_as_last_completed_basis(self) -> None:
        self.assertEqual(self.activation["schema_version"], 12)
        current = self.activation["accepted_production_runtime"]
        self.assertEqual(current["generation"], "V17.28")
        self.assertIs(current["full_basis_execution_pending"], True)
        self.assertEqual(current["last_completed_full_basis_generation"], "V17.27")
        self.assertEqual(current["last_completed_full_basis_run"], 30806818977)
        retained = self.activation["accepted_v17_27_full_basis_evidence"]
        self.assertIs(retained["last_completed_full_basis_authority"], True)
        self.assertEqual(retained["run"], 30806818977)
        self.assertEqual(retained["data_verdict" if "data_verdict" in retained else "final_data_verdict"], "FAIL_CLOSED")
        boundaries = self.activation["hard_boundaries"]
        self.assertIs(boundaries["v17_28_full_basis_execution_pending"], True)
        self.assertEqual(boundaries["last_completed_document_errors"], 1373)
        self.assertEqual(boundaries["last_completed_unresolved_ties"], 1290)
        self.assertIs(boundaries["expected_values_are_not_production_acceptance"], True)
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["main_changed"], False)


if __name__ == "__main__":
    unittest.main()
