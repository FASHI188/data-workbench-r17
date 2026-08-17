from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_26_p0_diagnostic.json"
EVIDENCE_CONTRACT = (
    ROOT / ".github/workflows/stage3-s3g1j-v17-26-evidence-contract.yml"
)
RETIRED_WORKFLOWS = (
    ROOT / ".github/workflows/stage3-s3g1j-v17-26-p0-diagnostic.yml",
    ROOT / ".github/workflows/stage3-s3g1j-v17-26-p0-candidate-detail-v3.yml",
)
EXPECTED_IDENTITY_IDS = [
    "1200907104",
    "1201708762",
    "1202195310",
    "1202774611",
    "1203358200",
]
EXPECTED_PERIOD_IDS = ["1204077386", "1205543437"]


class V1726P0DiagnosticEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_machine_artifact_identities_are_frozen(self) -> None:
        base = self.evidence["accepted_base_diagnostic"]
        self.assertEqual(base["run"], 30734944468)
        self.assertEqual(
            base["head_sha"], "57cca23e3d7b390a93446dbd99438e3fcb7f6a6c"
        )
        self.assertEqual(base["artifact_id"], 8829316913)
        self.assertEqual(
            base["artifact_digest"],
            "sha256:08afc1cde3e48243a7914320baa6ef96b64cf41d55b000063091b3805d171046",
        )
        detail = self.evidence["accepted_candidate_detail"]
        self.assertEqual(detail["run"], 30746041129)
        self.assertEqual(
            detail["head_sha"], "49a05c1b02bc6d4b49e8d825c3e23a092187f8db"
        )
        self.assertEqual(detail["artifact_id"], 8832931244)
        self.assertEqual(
            detail["artifact_digest"],
            "sha256:2b6a0086b8180c305531309fe76879d950c53169a46715a232802fe7eef26db5",
        )
        self.assertEqual(
            detail["accepted_report_sha256"],
            "b3ab013938ad41c673e1125336b2abda1fde8edff68e21f8ef3ba8cbdee00b54",
        )
        self.assertEqual(
            detail["raw_report_sha256"],
            "8a958ad58a89d6b911358aff472018dc39a62b2d3d3547ae7808db1b8fdbbfbe",
        )

    def test_source_locked_population_and_old_runtime_stability(self) -> None:
        base = self.evidence["accepted_base_diagnostic"]
        self.assertEqual(base["target_count"], 21)
        self.assertEqual(base["processed_count"], 21)
        self.assertEqual(base["source_sha_match_count"], 21)
        self.assertEqual(base["current_recovered_count"], 0)
        self.assertEqual(base["v17_26_equals_v17_25_count"], 21)
        self.assertEqual(base["generic_group_witness_count"], 7)
        self.assertEqual(
            base["generic_group_witness_announcement_ids"],
            EXPECTED_IDENTITY_IDS + EXPECTED_PERIOD_IDS,
        )

    def test_five_normal_equity_identities_are_exact_but_public_gate_rejects(self) -> None:
        detail = self.evidence["accepted_candidate_detail"]
        self.assertIs(detail["prior_hypothesis_rejected"], True)
        self.assertEqual(detail["identity_tolerance"], "0.005")
        self.assertEqual(
            detail["identity_present_but_public_gate_rejected_announcement_ids"],
            EXPECTED_IDENTITY_IDS,
        )
        rows = self.evidence["exact_identity_evidence"]
        self.assertEqual([row["announcement_id"] for row in rows], EXPECTED_IDENTITY_IDS)
        for row in rows:
            assets = Decimal(row["total_assets_cny"])
            liabilities = Decimal(row["total_liabilities_cny"])
            equity = Decimal(row["total_equity_cny"])
            self.assertEqual(assets, liabilities + equity)
            self.assertEqual(Decimal(row["identity_residual_cny"]), Decimal("0"))
            self.assertEqual(Decimal(row["identity_relative_error"]), Decimal("0"))
            self.assertEqual(row["source_code"], "000708")
            self.assertEqual(row["asset_alias"], "资产总计")
            self.assertEqual(row["liability_alias"], "负债合计")
            self.assertEqual(row["equity_alias"], "所有者权益合计")
            self.assertEqual(row["statement_role"], ["GROUP"])
            self.assertEqual(row["asset_page"], 9)
            self.assertEqual(row["liability_page"], 10)
            self.assertEqual(row["equity_page"], 11)
            self.assertEqual(row["statement_anchor_page"], 8)
            self.assertIs(row["equity_strict_corrupted_alias"], False)
            self.assertIs(row["public_candidate_recovered"], False)
            self.assertIs(row["public_identity_recovered_before_column_gate"], False)

    def test_two_documents_are_blocked_at_expected_period_gate(self) -> None:
        rows = self.evidence["period_or_role_gate_evidence"]
        self.assertEqual([row["announcement_id"] for row in rows], EXPECTED_PERIOD_IDS)
        for row in rows:
            self.assertEqual(
                row["candidate_counts"],
                {"TOTAL_ASSETS": 0, "TOTAL_LIABILITIES": 0, "TOTAL_EQUITY": 0},
            )
            self.assertEqual(row["assets_wrong_or_missing_period"], 3)
            self.assertEqual(row["liabilities_wrong_or_missing_period"], 1)
            self.assertEqual(row["equity_wrong_or_missing_period"], 2)

    def test_fail_closed_boundaries_and_workflow_retirement(self) -> None:
        boundaries = self.evidence["boundaries"]
        self.assertIs(boundaries["diagnostic_only"], True)
        self.assertIs(boundaries["parser_changed"], False)
        self.assertIs(boundaries["runtime_authority_changed"], False)
        self.assertIs(boundaries["production_data_changed"], False)
        self.assertIs(boundaries["trained_model_changed"], False)
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["main_changed"], False)
        self.assertIs(boundaries["automatic_recovery_authorized"], False)
        self.assertTrue(EVIDENCE_CONTRACT.exists())
        for workflow in RETIRED_WORKFLOWS:
            self.assertFalse(workflow.exists(), str(workflow))


if __name__ == "__main__":
    unittest.main()
