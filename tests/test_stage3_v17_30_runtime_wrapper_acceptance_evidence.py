from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_30_runtime_wrapper_acceptance.json"


class V1730RuntimeWrapperAcceptanceEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.e = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_exact_execution_identity(self) -> None:
        self.assertEqual(self.e["execution_pr"]["number"], 123)
        self.assertEqual(self.e["execution_pr"]["final_head_sha"], "d26d7f543c20d717ed8c8a421e28838feecd7a03")
        self.assertIs(self.e["execution_pr"]["closed_without_merge"], True)
        run = self.e["accepted_run"]
        self.assertEqual(run["run_id"], 31458469699)
        self.assertEqual(run["head_sha"], "d26d7f543c20d717ed8c8a421e28838feecd7a03")
        self.assertEqual(run["artifact_id"], 9088925988)
        self.assertEqual(run["artifact_digest"], "sha256:232b2e4a6c64b271193853d4e8fd32c0fdfd367344ecec720902fe8f090333dc")
        self.assertEqual(run["report_sha256"], "8e07e885bfdabc009b82ce791f2ce10c48f92111bf8956891af273e6d9221411")

    def test_real_and_delegation_machine_result(self) -> None:
        r = self.e["machine_result"]
        self.assertEqual(r["target_count"], 2)
        self.assertEqual(r["target_announcement_ids"], ["1223347318", "1223407043"])
        self.assertIs(r["real_source_runtime_wrapper_pass"], True)
        self.assertIs(r["real_formal_v17_29_non_target_delegation_pass"], True)
        self.assertIs(r["synthetic_wrong_identity_delegation_contract_pass"], True)
        self.assertIs(r["target_output_matches_registered_shadow"], True)
        self.assertEqual(r["formal_runtime_authority_before_activation"], "V17.29")
        self.assertIs(r["v17_30_authority_activated"], False)
        self.assertIs(r["fresh_full_basis_execution_started"], False)
        self.assertIs(r["shadow_expected_values_are_not_production_acceptance"], True)

    def test_exact_two_target_values_and_identity(self) -> None:
        targets = {x["announcement_id"]: x for x in self.e["targets"]}
        self.assertEqual(set(targets), {"1223347318", "1223407043"})
        for row in targets.values():
            self.assertEqual(row["equity_amount_page"] + 1, row["equity_suffix_page"])
            self.assertEqual(row["equity_label_prefix"] + row["equity_label_suffix"], "所有者权益（或股东权益）合计")
            self.assertEqual(row["current_identity_residual_cny"], "0.00")
            self.assertEqual(row["prior_identity_residual_cny"], "0.00")
            self.assertEqual(set(row["values"]), {"TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"})

    def test_merge_ref_is_not_authority(self) -> None:
        note = self.e["artifact_head_note"]
        self.assertIs(note["report_implementation_head_is_pr_merge_ref"], True)
        self.assertEqual(note["report_implementation_head"], "2f5de9a8eade4d90eb3e2df66669b830d86e9262")
        self.assertEqual(note["authoritative_branch_head_source"], "GitHub workflow_run.head_sha")
        self.assertEqual(note["authoritative_branch_head"], "d26d7f543c20d717ed8c8a421e28838feecd7a03")

    def test_no_authority_or_policy_relaxation(self) -> None:
        h = self.e["hard_boundaries"]
        self.assertEqual(h["formal_runtime_generation_remains"], "V17.29")
        for key in (
            "runtime_authority_changed",
            "production_data_changed",
            "trained_model_changed",
            "live_configuration_changed",
            "fresh_full_basis_execution_started",
            "ocr_enabled",
            "fuzzy_alias_matching_enabled",
            "equity_inferred_from_assets_minus_liabilities",
            "source_policy_relaxed",
            "point_in_time_policy_relaxed",
            "issuer_gate_relaxed",
            "accounting_tolerance_changed",
            "main_changed",
        ):
            self.assertIs(h[key], False, key)
        self.assertEqual(h["stage3_status"], "NOT_READY")
        self.assertIs(h["stage4_alpha_live_locked"], True)
        a = self.e["authorization"]
        self.assertIs(a["inactive_runtime_wrapper_acceptance_pass"], True)
        self.assertIs(a["formal_v17_30_runtime_promotion_governance_eligible"], True)
        self.assertIs(a["v17_30_runtime_authority_activated"], False)
        self.assertIs(a["fresh_v17_30_full_basis_execution_authorized"], False)
        self.assertIs(a["stage3_gate_pass"], False)


if __name__ == "__main__":
    unittest.main()
