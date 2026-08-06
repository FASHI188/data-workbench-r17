from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

import extract_stage3_financial_pdf_values_v18 as extractor
import stage3_financial_pdf_parser_v20 as parser


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "governance/stage3_s3g1j_runtime_manifest.json"
ACTIVATION = ROOT / "governance/stage3_workflow_activation_manifest.json"
PROMOTION = ROOT / "governance/stage3_s3g1j_v17_28_runtime_promotion.json"
FULL_FINAL = ROOT / "governance/stage3_s3g1j_v17_28_full_final.json"


class _Digest:
    def __init__(self, value: str) -> None:
        self.value = value

    def hexdigest(self) -> str:
        return self.value


def accepted_candidate(digest: str, target: dict) -> dict:
    observations = {
        concept: {
            "concept": concept,
            "status": "FOUND",
            "normalized_cny_value": target["values"][concept][0],
            "extraction_scope": "V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_CANDIDATE",
        }
        for concept in parser.ALLOWED_CONCEPTS
    }
    return {
        "parser_version": parser.candidate.METHOD,
        "tier1_found": 0,
        "tier2_found": 3,
        "validation_errors": [],
        "observations": observations,
        "balance_sheet_block": {
            "candidate_only": True,
            "exact_source_sha256": digest,
            "column_role_gate_pass": True,
            "split_equity_pattern": target["split_pattern"],
            "explicit_equity_pdf_text": True,
            "equity_value_inferred_as_assets_minus_liabilities": False,
            "non_balance_values_promoted": False,
            "ocr_enabled": False,
            "fuzzy_alias_matching_enabled": False,
            "dual_column_identity": {
                "columns": [
                    {"column": "CURRENT", "identity_residual_cny": "0.00", "identity_relative_error": "0"},
                    {"column": "PRIOR", "identity_residual_cny": "0.00", "identity_relative_error": "0"},
                ]
            },
        },
    }


class V1728RuntimePromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = json.loads(RUNTIME.read_text(encoding="utf-8"))
        cls.activation = json.loads(ACTIVATION.read_text(encoding="utf-8"))
        cls.promotion = json.loads(PROMOTION.read_text(encoding="utf-8"))
        cls.full = json.loads(FULL_FINAL.read_text(encoding="utf-8"))

    def test_formal_runtime_and_latest_full_basis_are_v17_28(self) -> None:
        self.assertEqual(self.runtime["schema_version"], 11)
        authority = self.runtime["current_production_authority"]
        self.assertEqual(authority["generation"], "V17.28")
        self.assertEqual(authority["status"], "RUNTIME_AND_FULL_BASIS_ACCEPTED_DATA_FAIL_CLOSED")
        self.assertIs(authority["runtime_promotion"]["full_basis_execution_pending"], False)
        self.assertEqual(
            authority["full_basis_evidence_manifest"],
            "governance/stage3_s3g1j_v17_28_full_final.json",
        )
        formal = self.runtime["formal_runtime"]
        self.assertEqual(formal["runtime_generation"], "V17.28")
        self.assertEqual(formal["shard_count"], 64)
        self.assertEqual(formal["shard_gate"], extractor.SHARD_GATE)
        self.assertEqual(formal["extractor_method"], extractor.METHOD)
        self.assertEqual(formal["parser_method"], parser.METHOD)
        self.assertEqual(formal["methodology_version"], parser.METHODOLOGY_VERSION)
        latest = self.runtime["full_basis_last_completed_final"]
        self.assertEqual(latest["generation"], "V17.28")
        self.assertEqual(latest["run"], 30997260730)
        self.assertEqual(latest["artifact_id"], 8927455692)
        self.assertEqual(latest["numeric_observations"], 1051799)
        self.assertEqual(latest["document_error_count"], 1371)
        self.assertEqual(latest["unresolved_tie_count"], 1288)
        self.assertEqual(latest["verdict"], "FAIL_CLOSED")
        self.assertEqual(
            self.runtime["production_final_status"],
            "RUNTIME_AND_FULL_BASIS_ACCEPTED_DATA_FAIL_CLOSED",
        )

    def test_runtime_wrapper_acceptance_is_exact(self) -> None:
        wrapper = self.runtime["current_production_authority"]["runtime_wrapper_acceptance"]
        self.assertEqual(wrapper["pr"], 94)
        self.assertEqual(wrapper["head_sha"], "6969c58ee60314e3e897e55b132266612c602777")
        self.assertEqual(wrapper["merge_commit"], "d7c38e71c9155d404df1c08feba9d66fac0a4d7a")
        self.assertEqual(wrapper["run"], 30978715158)
        self.assertEqual(wrapper["artifact_id"], 8919289427)
        self.assertEqual(
            wrapper["artifact_digest"],
            "sha256:f8639b4a2eac2d09b16586365b7932d255457ce66aad2484547bb517d0d185a6",
        )
        self.assertIs(wrapper["execution_pass"], True)
        self.assertIs(wrapper["real_source_promotion_pass"], True)
        self.assertIs(wrapper["non_target_v17_27_delegation_pass"], True)

    def test_v17_28_full_basis_acceptance_is_exact(self) -> None:
        accepted = self.runtime["current_production_authority"]["full_basis_acceptance"]
        self.assertEqual(accepted["execution_pr"], 96)
        self.assertIs(accepted["execution_pr_merged"], False)
        self.assertEqual(accepted["acceptance_pr"], 97)
        self.assertEqual(accepted["governance_pr"], 98)
        self.assertEqual(accepted["run"], 30997260730)
        self.assertEqual(accepted["artifact_id"], 8927455692)
        self.assertEqual(
            accepted["artifact_digest"],
            "sha256:82375169faada969ceafd4356ab0a2707aa14592d5db090c5d3910863d571c8b",
        )
        self.assertEqual(accepted["document_count"], 121354)
        self.assertEqual(accepted["numeric_observation_count"], 1051799)
        self.assertEqual(accepted["document_error_count"], 1371)
        self.assertEqual(accepted["unresolved_tie_count"], 1288)
        self.assertEqual(accepted["final_data_verdict"], "FAIL_CLOSED")
        self.assertIs(accepted["execution_pass"], True)
        self.assertIs(accepted["independent_artifact_recheck_pass"], True)

    def test_v17_28_exact_source_scope_is_frozen(self) -> None:
        expected_ids = {"1207621057", "1209825769"}
        self.assertEqual(
            {target["announcement_id"] for target in parser.TARGETS.values()},
            expected_ids,
        )
        gates = self.runtime["v17_28_exact_source_gates"]
        self.assertEqual(set(gates["targets"]), expected_ids)
        self.assertEqual(
            set(gates["allowed_concepts"]),
            {"TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"},
        )
        self.assertEqual(
            gates["full_basis_evidence_manifest"],
            "governance/stage3_s3g1j_v17_28_full_final.json",
        )
        self.assertIs(gates["formal_group_role_required"], True)
        self.assertIs(gates["role_local_period_and_unit_required"], True)
        self.assertIs(gates["split_row_geometry_required"], True)
        self.assertIs(gates["explicit_equity_pdf_text_required"], True)
        self.assertIs(gates["e_equals_a_minus_l_inference"], False)

    def test_non_target_output_remains_exact_v17_27(self) -> None:
        inherited = {
            "parser_version": "V17_27_EXACT_SOURCE_NORMAL_EQUITY_IDENTITY_PRODUCTION",
            "observations": {"TOTAL_ASSETS": {"status": "NOT_FOUND"}},
            "validation_errors": ["retained-fail-closed"],
        }
        expected = copy.deepcopy(inherited)
        with mock.patch.object(
            parser.candidate, "parse_pdf_bytes", return_value=copy.deepcopy(inherited)
        ):
            actual = parser.parse_pdf_bytes(b"not-a-target", "2020-03-31")
        self.assertEqual(actual, expected)

    def test_target_promotes_only_three_balance_totals(self) -> None:
        digest, target = next(iter(parser.TARGETS.items()))
        accepted = accepted_candidate(digest, target)
        with mock.patch.object(parser.hashlib, "sha256", return_value=_Digest(digest)), mock.patch.object(
            parser.candidate, "parse_pdf_bytes", return_value=copy.deepcopy(accepted)
        ):
            actual = parser.parse_pdf_bytes(b"target", target["economic_date"])
        self.assertEqual(actual["parser_version"], parser.METHOD)
        found = {
            concept
            for concept, row in actual["observations"].items()
            if row.get("status") == "FOUND"
        }
        self.assertEqual(found, set(parser.ALLOWED_CONCEPTS))
        block = actual["balance_sheet_block"]
        self.assertIs(block["candidate_only"], False)
        self.assertIs(block["candidate_safety_promoted"], True)
        self.assertEqual(block["formal_runtime_generation"], "V17.28")
        self.assertEqual(block["candidate_acceptance_run"], 30827493788)

    def test_activation_records_completed_v17_28_full_basis(self) -> None:
        self.assertEqual(self.activation["schema_version"], 13)
        current = self.activation["accepted_production_runtime"]
        self.assertEqual(current["generation"], "V17.28")
        self.assertEqual(current["runtime_manifest_schema"], 11)
        self.assertIs(current["full_basis_execution_pending"], False)
        self.assertEqual(current["last_completed_full_basis_generation"], "V17.28")
        self.assertEqual(current["last_completed_full_basis_run"], 30997260730)
        self.assertEqual(current["execution_verdict"], "PASS")
        self.assertEqual(current["data_verdict"], "FAIL_CLOSED")
        registered = self.activation["accepted_v17_28_full_basis_evidence"]
        self.assertEqual(registered["run"], 30997260730)
        self.assertIs(registered["last_completed_full_basis_authority"], True)

    def test_historical_promotion_manifest_is_not_rewritten(self) -> None:
        self.assertEqual(self.promotion["status"], "RUNTIME_PROMOTION_PROPOSED_FULL_BASIS_PENDING")
        self.assertEqual(self.promotion["formal_runtime"]["runtime_generation"], "V17.28")
        self.assertEqual(self.promotion["last_completed_full_basis"]["generation"], "V17.27")
        self.assertEqual(self.promotion["next_full_basis"]["status"], "REQUIRED_NOT_STARTED")
        boundaries = self.promotion["hard_boundaries"]
        self.assertIs(boundaries["production_data_changed"], False)
        self.assertIs(boundaries["trained_model_changed"], False)
        self.assertIs(boundaries["main_changed"], False)

    def test_project_locks_remain_closed(self) -> None:
        boundaries = self.full["hard_boundaries"]
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["s3g4_full_final_pending"], True)
        self.assertIs(boundaries["freshness_gate_pending"], True)


if __name__ == "__main__":
    unittest.main()
