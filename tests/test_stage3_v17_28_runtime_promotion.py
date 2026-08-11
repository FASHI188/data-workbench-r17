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
    observations = {c:{"concept":c,"status":"FOUND","normalized_cny_value":target["values"][c][0],"extraction_scope":"V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_CANDIDATE"} for c in parser.ALLOWED_CONCEPTS}
    return {"parser_version":parser.candidate.METHOD,"tier1_found":0,"tier2_found":3,"validation_errors":[],"observations":observations,"balance_sheet_block":{"candidate_only":True,"exact_source_sha256":digest,"column_role_gate_pass":True,"split_equity_pattern":target["split_pattern"],"explicit_equity_pdf_text":True,"equity_value_inferred_as_assets_minus_liabilities":False,"non_balance_values_promoted":False,"ocr_enabled":False,"fuzzy_alias_matching_enabled":False,"dual_column_identity":{"columns":[{"column":"CURRENT","identity_residual_cny":"0.00","identity_relative_error":"0"},{"column":"PRIOR","identity_residual_cny":"0.00","identity_relative_error":"0"}]}}}


class V1728RuntimePromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime=json.loads(RUNTIME.read_text(encoding="utf-8"))
        cls.activation=json.loads(ACTIVATION.read_text(encoding="utf-8"))
        cls.promotion=json.loads(PROMOTION.read_text(encoding="utf-8"))
        cls.full=json.loads(FULL_FINAL.read_text(encoding="utf-8"))

    def test_v17_28_is_retained_as_previous_completed_full_basis(self) -> None:
        self.assertGreaterEqual(self.runtime["schema_version"],14)
        self.assertEqual(self.runtime["formal_runtime"]["runtime_generation"],"V17.30")
        latest=self.runtime["full_basis_last_completed_final"]
        self.assertEqual((latest["generation"],latest["run"]),("V17.29",31389854868))
        previous=self.runtime["previous_last_completed_full_basis_final"]
        self.assertEqual(previous["generation"],"V17.28")
        self.assertEqual(previous["run"],30997260730)
        self.assertEqual(previous["artifact_id"],8927455692)
        self.assertEqual(previous["numeric_observations"],1051799)
        self.assertEqual(previous["document_error_count"],1371)
        self.assertEqual(previous["unresolved_tie_count"],1288)
        self.assertEqual(previous["verdict"],"FAIL_CLOSED")
        self.assertTrue(previous["retained"])
        nxt=self.runtime["next_full_basis_required"]
        self.assertEqual(nxt["generation"],"V17.30")
        self.assertEqual(nxt["status"],"REQUIRED_NOT_STARTED")

    def test_historical_v17_28_runtime_identity_is_exact(self) -> None:
        historical=self.activation["accepted_v17_28_runtime_wrapper"]
        self.assertEqual(historical["run"],30978715158)
        self.assertEqual(historical["artifact_id"],8919289427)
        self.assertEqual(historical["artifact_digest"],"sha256:f8639b4a2eac2d09b16586365b7932d255457ce66aad2484547bb517d0d185a6")
        self.assertTrue(historical["runtime_promoted"])
        self.assertTrue(historical["historical_runtime_generation_retained"])
        self.assertFalse(historical["full_basis_execution_pending"])
        self.assertEqual(extractor.RUNTIME_GENERATION,"V17.28")
        self.assertEqual(parser.METHOD,"V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION")

    def test_v17_28_full_basis_acceptance_is_exact_and_historical(self) -> None:
        registered=self.activation["accepted_v17_28_full_basis_evidence"]
        self.assertEqual(registered["run"],30997260730)
        self.assertEqual(registered["artifact_id"],8927455692)
        self.assertEqual(registered["artifact_digest"],"sha256:82375169faada969ceafd4356ab0a2707aa14592d5db090c5d3910863d571c8b")
        self.assertEqual(registered["numeric_observation_count"],1051799)
        self.assertEqual(registered["document_error_count"],1371)
        self.assertEqual(registered["unresolved_tie_count"],1288)
        self.assertEqual(registered["final_data_verdict"],"FAIL_CLOSED")
        self.assertTrue(registered["historical_full_basis_authority_retained"])
        self.assertFalse(registered["last_completed_full_basis_authority"])
        result=self.full["full_basis_result"]
        self.assertEqual(result["numeric_observation_count"],1051799)
        self.assertEqual(result["document_error_count"],1371)
        self.assertEqual(result["unresolved_tie_count"],1288)

    def test_v17_28_exact_source_scope_is_frozen(self) -> None:
        expected_ids={"1207621057","1209825769"}
        self.assertEqual({target["announcement_id"] for target in parser.TARGETS.values()},expected_ids)
        gates=self.runtime["v17_28_exact_source_gates"]
        self.assertEqual(set(gates["targets"]),expected_ids)
        self.assertTrue(gates["formal_group_role_required"])
        self.assertTrue(gates["role_local_period_and_unit_required"])
        self.assertTrue(gates["split_row_geometry_required"])
        self.assertTrue(gates["explicit_equity_pdf_text_required"])
        self.assertFalse(gates["e_equals_a_minus_l_inference"])

    def test_non_target_output_remains_exact_v17_27_inside_historical_parser(self) -> None:
        inherited={"parser_version":"V17_27_EXACT_SOURCE_NORMAL_EQUITY_IDENTITY_PRODUCTION","observations":{"TOTAL_ASSETS":{"status":"NOT_FOUND"}},"validation_errors":["retained-fail-closed"]}
        expected=copy.deepcopy(inherited)
        with mock.patch.object(parser.candidate,"parse_pdf_bytes",return_value=copy.deepcopy(inherited)):
            actual=parser.parse_pdf_bytes(b"not-a-target","2020-03-31")
        self.assertEqual(actual,expected)

    def test_historical_target_promotes_only_three_balance_totals(self) -> None:
        digest,target=next(iter(parser.TARGETS.items()))
        accepted=accepted_candidate(digest,target)
        with mock.patch.object(parser.hashlib,"sha256",return_value=_Digest(digest)), mock.patch.object(parser.candidate,"parse_pdf_bytes",return_value=copy.deepcopy(accepted)):
            actual=parser.parse_pdf_bytes(b"target",target["economic_date"])
        self.assertEqual(actual["parser_version"],parser.METHOD)
        found={c for c,row in actual["observations"].items() if row.get("status")=="FOUND"}
        self.assertEqual(found,set(parser.ALLOWED_CONCEPTS))
        self.assertEqual(actual["balance_sheet_block"]["formal_runtime_generation"],"V17.28")

    def test_activation_keeps_v17_28_historical_under_v17_30_runtime(self) -> None:
        self.assertGreaterEqual(self.activation["schema_version"],16)
        current=self.activation["accepted_production_runtime"]
        self.assertEqual(current["generation"],"V17.30")
        self.assertTrue(current["full_basis_execution_pending"])
        self.assertEqual(current["last_completed_full_basis_generation"],"V17.29")
        self.assertEqual(current["last_completed_full_basis_run"],31389854868)
        self.assertEqual(current["data_verdict"],"FAIL_CLOSED")
        historical=self.activation["accepted_v17_28_full_basis_evidence"]
        self.assertTrue(historical["historical_full_basis_authority_retained"])
        self.assertFalse(historical["last_completed_full_basis_authority"])

    def test_historical_promotion_manifest_is_not_rewritten(self) -> None:
        self.assertEqual(self.promotion["status"],"RUNTIME_PROMOTION_PROPOSED_FULL_BASIS_PENDING")
        self.assertEqual(self.promotion["formal_runtime"]["runtime_generation"],"V17.28")
        self.assertEqual(self.promotion["last_completed_full_basis"]["generation"],"V17.27")
        self.assertEqual(self.promotion["next_full_basis"]["status"],"REQUIRED_NOT_STARTED")
        boundaries=self.promotion["hard_boundaries"]
        self.assertFalse(boundaries["production_data_changed"])
        self.assertFalse(boundaries["trained_model_changed"])
        self.assertFalse(boundaries["main_changed"])

    def test_project_locks_remain_closed(self) -> None:
        boundaries=self.full["hard_boundaries"]
        self.assertEqual(boundaries["stage3_status"],"NOT_READY")
        self.assertTrue(boundaries["stage4_alpha_live_locked"])
        self.assertTrue(boundaries["s3g4_full_final_pending"])
        self.assertTrue(boundaries["freshness_gate_pending"])


if __name__ == "__main__":
    unittest.main()
