from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_29_six_source_diagnostic.json"


class V1729SixSourceDiagnosticEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.e = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_exact_diagnostic_run_and_artifact(self) -> None:
        self.assertEqual(self.e["diagnostic_pr"]["number"], 117)
        self.assertEqual(self.e["diagnostic_pr"]["head_sha"], "bdbd4b197956206ce56cc21768a97cb8c27eb183")
        self.assertIs(self.e["diagnostic_pr"]["closed_without_merge"], True)
        run = self.e["accepted_run"]
        self.assertEqual(run["run_id"], 31450849437)
        self.assertEqual(run["artifact_id"], 9086284056)
        self.assertEqual(run["artifact_digest"], "sha256:a4a3b97bf82aebe85d9f3947307224d7d18df15ccd387aeb11bbbe61d21ed411")

    def test_four_remain_diagnostic_only_and_two_are_experiment_eligible(self) -> None:
        result = self.e["classification_result"]
        self.assertEqual(result["diagnostic_only_no_safe_ordinary_candidate_count"], 4)
        self.assertEqual(result["cross_page_exact_source_candidate_experiment_eligible_count"], 2)
        self.assertEqual(result["bank_specific_do_not_promote_count"], 1)
        self.assertIs(result["candidate_parser_implementation_authorized"], False)
        self.assertIs(result["candidate_parser_promotion_authorized"], False)
        self.assertEqual(
            [x["announcement_id"] for x in self.e["cross_page_exact_source_candidates"]],
            ["1223347318", "1223407043"],
        )

    def test_cross_page_alias_completion_and_identity_are_exact(self) -> None:
        targets = {x["announcement_id"]: x for x in self.e["cross_page_exact_source_candidates"]}
        self.assertEqual(targets["1223347318"]["equity_label_prefix"] + targets["1223347318"]["next_page_exact_suffix"], "所有者权益（或股东权益）合计")
        self.assertEqual(targets["1223407043"]["equity_label_prefix"] + targets["1223407043"]["next_page_exact_suffix"], "所有者权益（或股东权益）合计")
        for row in targets.values():
            self.assertEqual(row["current_values"]["identity_residual"], "0.00")
            self.assertEqual(row["prior_values"]["identity_residual"], "0.00")
            self.assertEqual(row["classification"], "CROSS_PAGE_EXACT_SOURCE_CANDIDATE_EXPERIMENT_ELIGIBLE")

    def test_source_and_runtime_boundaries_remain_fail_closed(self) -> None:
        source = self.e["source_identity_result"]
        self.assertEqual(source["target_count"], 6)
        self.assertIs(source["all_exact_source_sha_and_bytes_verified"], True)
        self.assertIs(source["accepted_document_ledger_mutated"], False)
        self.assertIs(source["formal_parser_remained_fail_closed_on_all_six"], True)
        self.assertEqual(source["formal_parser_required_error"], "NO_VALIDATED_BALANCE_SHEET_BLOCK")
        hard = self.e["hard_boundaries"]
        self.assertIs(hard["formal_parser_changed"], False)
        self.assertIs(hard["runtime_authority_changed"], False)
        self.assertIs(hard["production_data_changed"], False)
        self.assertIs(hard["ocr_enabled"], False)
        self.assertIs(hard["fuzzy_alias_matching_enabled"], False)
        self.assertIs(hard["equity_inference_enabled"], False)
        self.assertEqual(hard["stage3_status"], "NOT_READY")
        self.assertIs(hard["stage4_alpha_live_locked"], True)

    def test_bank_remains_isolated(self) -> None:
        bank = self.e["bank_specific_isolation"]
        self.assertEqual(bank["announcement_id"], "1219834247")
        self.assertEqual(bank["classification"], "DO_NOT_PROMOTE_ORDINARY_PATH")
        self.assertIs(bank["included_in_six_source_diagnostic"], False)


if __name__ == "__main__":
    unittest.main()
