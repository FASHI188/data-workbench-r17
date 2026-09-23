from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_28_p0_pdf_root_cause.json"

SAFE_IDS = [
    "1215186538",
    "1219426855",
    "1219792633",
    "1219840508",
    "1219879687",
    "1220087244",
    "1221006100",
]
DIAGNOSTIC_IDS = [
    "1202799494",
    "1204077386",
    "1205543437",
    "1209806910",
    "1223347318",
    "1223407043",
]


class V1728P0PdfRootCauseEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_exact_pr_run_and_artifact_identity(self) -> None:
        pr = self.evidence["diagnostic_pr"]
        run = self.evidence["accepted_run"]
        self.assertEqual(pr["number"], 101)
        self.assertEqual(pr["head_sha"], "c1e1a99533498c9e4eba7ae95323cc80586474c4")
        self.assertIs(pr["merge_authorized"], False)
        self.assertEqual(run["run_id"], 31111116235)
        self.assertEqual(run["head_sha"], pr["head_sha"])
        self.assertEqual(run["conclusion"], "SUCCESS")
        self.assertEqual(run["artifact_id"], 8971708686)
        self.assertEqual(
            run["artifact_digest"],
            "sha256:c743dc725e15037eb761244e5e0e88d37075a1cf5eab366e5d64c9d7ac0627b8",
        )

    def test_exact_classification_population(self) -> None:
        result = self.evidence["classification_result"]
        self.assertEqual(result["target_count"], 14)
        self.assertEqual(
            result["classification_counts"],
            {
                "SAFE_EXACT_SOURCE_CANDIDATE": 7,
                "DIAGNOSTIC_ONLY": 6,
                "DO_NOT_PROMOTE": 1,
            },
        )
        self.assertEqual(result["safe_exact_source_announcement_ids"], SAFE_IDS)
        self.assertEqual(result["diagnostic_only_announcement_ids"], DIAGNOSTIC_IDS)
        self.assertEqual(result["do_not_promote_announcement_ids"], ["1219834247"])
        self.assertEqual(result["safe_current_identity_zero_residual_count"], 7)
        self.assertEqual(result["safe_prior_identity_zero_residual_count"], 7)

    def test_safe_targets_are_sha_bound_but_not_parser_authorized(self) -> None:
        targets = self.evidence["safe_exact_source_targets"]
        self.assertEqual([row["announcement_id"] for row in targets], SAFE_IDS)
        self.assertEqual(len({row["source_sha256"] for row in targets}), 7)
        for row in targets:
            self.assertEqual(len(row["source_sha256"]), 64)
            self.assertGreater(row["source_bytes"], 0)
            self.assertGreater(row["page_count"], 0)
            self.assertIs(row["formal_group_title_proven"], True)
            self.assertIs(row["role_local_period_and_cny_unit_proven"], True)
            self.assertIs(row["explicit_group_assets_liabilities_equity_proven"], True)
            self.assertEqual(row["current_identity_residual"], "0.00")
            self.assertEqual(row["prior_identity_residual"], "0.00")
            self.assertIs(row["candidate_parser_authorized"], False)

    def test_non_promoted_targets_preserve_fail_closed_root_causes(self) -> None:
        rows = {row["announcement_id"]: row for row in self.evidence["non_promoted_targets"]}
        self.assertEqual(set(rows), set(DIAGNOSTIC_IDS + ["1219834247"]))
        self.assertEqual(rows["1204077386"]["root_cause"], "GENERIC_GROUP_WITNESS_PRESENT_BUT_ROLE_LOCAL_PERIOD_MISSING")
        self.assertEqual(rows["1205543437"]["root_cause"], "GENERIC_GROUP_WITNESS_PRESENT_BUT_ROLE_LOCAL_PERIOD_MISSING")
        self.assertEqual(rows["1223347318"]["root_cause"], "FORMAL_GROUP_A_L_PRESENT_BUT_EXPLICIT_GROUP_EQUITY_PAIR_NOT_PROVEN")
        self.assertEqual(rows["1223407043"]["root_cause"], "FORMAL_GROUP_A_L_PRESENT_BUT_EXPLICIT_GROUP_EQUITY_PAIR_NOT_PROVEN")
        self.assertEqual(rows["1219834247"]["classification"], "DO_NOT_PROMOTE")
        self.assertEqual(rows["1219834247"]["root_cause"], "BANK_SPECIFIC_STATEMENT_WITHOUT_FORMAL_GROUP_ALE_ROLE_BINDING")
        self.assertTrue(all(row["candidate_parser_authorized"] is False for row in rows.values()))

    def test_output_hashes_and_independent_verification_are_frozen(self) -> None:
        hashes = self.evidence["output_hashes"]
        self.assertEqual(hashes["root_cause_ledger_gzip_sha256"], "e3ba4e23b81dcb24d24def114cd6a70289c2f7df654b1d81238638675ec1a92c")
        self.assertEqual(hashes["root_cause_ledger_plaintext_sha256"], "0861076fdf2547d1269df2b6c6000fbf1ea3b5998ad1658ae3c7fa028157ce1a")
        self.assertEqual(hashes["safe_target_manifest_sha256"], "c3ed36d0bd79c0dacfbc3e5375612619c7cc429a09eb3c4b10fcde77886c8a34")
        self.assertEqual(hashes["summary_json_sha256"], "2caaadaa1dec8faea6fb0b4c36cc5a0dd539b1738b1e788e1ec40a71ba8a476e")
        verification = self.evidence["independent_verification"]
        self.assertIs(verification["artifact_downloaded_and_inspected"], True)
        self.assertEqual(verification["target_rows_recounted"], 14)
        self.assertEqual(verification["errors"], [])

    def test_evidence_does_not_claim_new_pdf_or_ocr_review(self) -> None:
        boundary = self.evidence["evidence_boundary"]
        self.assertIs(boundary["pdf_binaries_redownloaded"], False)
        self.assertEqual(boundary["evidence_source"], "ACCEPTED_FROZEN_EXACT_PDF_LAYOUT_ARTIFACTS")
        self.assertIs(boundary["ocr_used"], False)
        self.assertIs(boundary["equity_inferred_from_assets_minus_liabilities"], False)
        self.assertIs(boundary["explicit_equity_amount_and_label_required"], True)

    def test_diagnostic_keeps_all_formal_locks(self) -> None:
        boundaries = self.evidence["hard_boundaries"]
        self.assertIs(boundaries["diagnostic_only"], True)
        self.assertIs(boundaries["candidate_parser_authorized"], False)
        self.assertIs(boundaries["formal_parser_changed"], False)
        self.assertIs(boundaries["runtime_authority_changed"], False)
        self.assertIs(boundaries["production_data_changed"], False)
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["main_changed"], False)
        self.assertIs(boundaries["merge_to_main_authorized"], False)


if __name__ == "__main__":
    unittest.main()
