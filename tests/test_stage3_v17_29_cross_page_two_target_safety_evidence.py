from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_29_cross_page_two_target_safety.json"


class CrossPageTwoTargetSafetyEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.e = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_exact_run_and_artifact(self) -> None:
        self.assertEqual(self.e["diagnostic_pr"]["number"], 119)
        self.assertEqual(self.e["diagnostic_pr"]["head_sha"], "ceccffd577d27ac9dad1722a8b77b2e6c891f3a2")
        self.assertIs(self.e["diagnostic_pr"]["closed_without_merge"], True)
        run=self.e["accepted_run"]
        self.assertEqual(run["run_id"], 31451602128)
        self.assertEqual(run["artifact_id"], 9086511255)
        self.assertEqual(run["artifact_digest"], "sha256:09a74424d8fcbbe4fe29523128752fc33b0a2c937d57f0d75dceccfd8261ffe4")
        self.assertEqual(run["report_sha256"], "cff12bf13793bc20094c8940065de1e4bbc8905d013f6126c1060d34425c4daf")

    def test_full_population_routing_is_exactly_two(self) -> None:
        r=self.e["full_population_routing"]
        self.assertEqual(r["input_document_rows"], 121354)
        self.assertEqual(r["candidate_route_count"], 2)
        self.assertEqual(r["formal_v17_29_delegate_count"], 121352)
        self.assertEqual(r["candidate_route_announcement_ids"], ["1223347318","1223407043"])
        self.assertEqual(r["residual_source_identity_origin"], "SINGLE_CANDIDATE_EVIDENCE_JSON")
        self.assertIs(r["wrong_sha_delegates"], True)
        self.assertIs(r["wrong_bytes_delegates"], True)
        self.assertIs(r["wrong_economic_date_delegates"], True)

    def test_exact_alias_continuation_and_identity(self) -> None:
        rows={x["announcement_id"]:x for x in self.e["accepted_candidate_recoveries"]}
        self.assertEqual(set(rows), {"1223347318","1223407043"})
        for row in rows.values():
            self.assertEqual(row["equity_amount_page"]+1, row["suffix_page"])
            self.assertEqual(row["equity_label_prefix"]+row["next_page_exact_suffix"], "所有者权益（或股东权益）合计")
            self.assertEqual(row["current"]["identity_residual_cny"], "0.00")
            self.assertEqual(row["prior"]["identity_residual_cny"], "0.00")
            self.assertEqual(row["formal_v17_29_before_candidate"], "FAIL_CLOSED_NO_VALIDATED_BALANCE_SHEET_BLOCK")

    def test_no_relaxation_or_promotion_authority(self) -> None:
        s=self.e["safety_properties"]
        self.assertIs(s["same_formal_group_statement_event_required"], True)
        self.assertIs(s["role_local_period_required"], True)
        self.assertIs(s["explicit_cny_unit_required"], True)
        self.assertIs(s["exact_full_alias_after_concatenation_required"], True)
        self.assertIs(s["dual_column_identity_required"], True)
        self.assertEqual(s["identity_tolerance"], "0.005")
        self.assertIs(s["observed_identity_residuals_are_exact_zero"], True)
        self.assertIs(s["raw_numeric_value_uniqueness_not_used"], True)
        self.assertIs(s["ocr_used"], False)
        self.assertIs(s["fuzzy_alias_matching_used"], False)
        self.assertIs(s["equity_inferred_from_assets_minus_liabilities"], False)
        self.assertIs(s["accounting_tolerance_relaxed"], False)
        a=self.e["authorization"]
        self.assertIs(a["candidate_safety_pass"], True)
        self.assertIs(a["production_promotion_safety_experiment_eligible"], True)
        self.assertIs(a["formal_parser_implementation_authorized"], False)
        self.assertIs(a["runtime_promotion_authorized"], False)
        self.assertIs(a["full_basis_execution_authorized"], False)
        self.assertIs(a["stage3_gate_pass"], False)

    def test_downstream_locks_remain(self) -> None:
        h=self.e["hard_boundaries"]
        self.assertIs(h["formal_parser_changed"], False)
        self.assertIs(h["runtime_authority_changed"], False)
        self.assertIs(h["production_data_changed"], False)
        self.assertEqual(h["stage3_status"], "NOT_READY")
        self.assertIs(h["stage4_alpha_live_locked"], True)
        self.assertIs(h["main_changed"], False)


if __name__ == "__main__":
    unittest.main()
