from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_29_residual_classification.json"
ROOT_CAUSE = ROOT / "governance/stage3_s3g1j_v17_28_p0_pdf_root_cause.json"
RUNTIME = ROOT / "governance/stage3_s3g1j_runtime_manifest.json"
PROJECT = ROOT / "data/project_status.json"


class V1729ResidualClassificationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        cls.root_cause = json.loads(ROOT_CAUSE.read_text(encoding="utf-8"))
        cls.runtime = json.loads(RUNTIME.read_text(encoding="utf-8"))
        cls.project = json.loads(PROJECT.read_text(encoding="utf-8"))

    def test_exact_diagnostic_run_and_artifact_identity(self) -> None:
        pr = self.evidence["diagnostic_pr"]
        run = self.evidence["accepted_run"]
        self.assertEqual(pr["number"], 115)
        self.assertEqual(pr["head_sha"], "fe9ee8ab95bf0b8aac12f0461929c03c7ea5dfbf")
        self.assertTrue(pr["closed_without_merge"])
        self.assertFalse(pr["merge_authorized"])
        self.assertEqual(run["run_id"], 31397106544)
        self.assertEqual(run["head_sha"], "fe9ee8ab95bf0b8aac12f0461929c03c7ea5dfbf")
        self.assertEqual(run["artifact_id"], 9066068547)
        self.assertEqual(run["artifact_name"], "stage3-s3g1j-v17-29-residual-classification-v1")
        self.assertEqual(run["artifact_digest"], "sha256:7b6f6347367e51c0130e2415dd908f8dc17848851cc6e51814dcd9aaf0173e7e")
        self.assertEqual(run["conclusion"], "SUCCESS")

    def test_exact_residual_population(self) -> None:
        r = self.evidence["classification_result"]
        self.assertEqual(r["input_document_rows"], 121354)
        self.assertEqual(r["pass_document_rows"], 119990)
        self.assertEqual(r["residual_document_rows"], 1364)
        self.assertEqual(sum(r["class_counts"].values()), 1364)
        self.assertEqual(sum(r["priority_counts"].values()), 1364)
        self.assertEqual(r["tie_taxonomy"], {"TIE_SOURCE_INCOMPLETE": 1267, "TIE_VALUE_CONFLICT": 14})
        self.assertEqual(r["single_canonical_residual_count"], 1180)
        self.assertEqual(r["multi_candidate_source_incomplete_count"], 87)
        self.assertEqual(r["issuer_mismatch_count"], 83)
        self.assertEqual(r["value_conflict_count"], 14)
        self.assertEqual(r["p0_safe_near_complete_count"], 7)
        self.assertEqual(r["p0_announcement_ids"], ["1202799494", "1204077386", "1205543437", "1209806910", "1219834247", "1223347318", "1223407043"])

    def test_migration_is_exact_seven_recovered_exits(self) -> None:
        m = self.evidence["migration_from_v17_28"]
        self.assertEqual(m["previous_residual_rows"], 1371)
        self.assertEqual(m["current_residual_rows"], 1364)
        self.assertEqual(m["unchanged_common_residuals"], 1364)
        self.assertEqual(m["recovered_exit_count"], 7)
        self.assertEqual(m["new_residual_count"], 0)
        self.assertEqual(m["common_residual_reclassification_count"], 0)
        self.assertEqual(m["p0_count_change"], "14_TO_7")
        self.assertTrue(m["all_surviving_classifications_unchanged"])
        self.assertEqual(m["recovered_exit_announcement_ids"], ["1215186538", "1219426855", "1219792633", "1219840508", "1219879687", "1220087244", "1221006100"])

    def test_surviving_p0_has_no_authorized_ordinary_repair(self) -> None:
        boundary = self.evidence["surviving_p0_root_cause_boundary"]
        self.assertEqual(boundary["diagnostic_only_count"], 6)
        self.assertEqual(boundary["do_not_promote_count"], 1)
        self.assertEqual(boundary["safe_exact_source_candidate_count"], 0)
        diagnostic_ids = {row["announcement_id"] for row in boundary["diagnostic_only"]}
        bank_ids = {row["announcement_id"] for row in boundary["do_not_promote"]}
        self.assertEqual(diagnostic_ids, {"1202799494", "1204077386", "1205543437", "1209806910", "1223347318", "1223407043"})
        self.assertEqual(bank_ids, {"1219834247"})
        self.assertTrue(all(row["root_cause"] for row in boundary["diagnostic_only"]))
        self.assertEqual(boundary["do_not_promote"][0]["root_cause"], "BANK_SPECIFIC_STATEMENT_WITHOUT_FORMAL_GROUP_ALE_ROLE_BINDING")
        old = self.root_cause["classification_result"]
        old_safe = set(old["safe_exact_source_announcement_ids"])
        old_diag = set(old["diagnostic_only_announcement_ids"])
        old_block = set(old["do_not_promote_announcement_ids"])
        self.assertEqual(old_diag, diagnostic_ids)
        self.assertEqual(old_block, bank_ids)
        self.assertEqual(old_safe, set(self.evidence["migration_from_v17_28"]["recovered_exit_announcement_ids"]))
        self.assertTrue(old_safe.isdisjoint(diagnostic_ids | bank_ids))

    def test_fixed_gzip_and_plaintext_hashes_are_frozen(self) -> None:
        h = self.evidence["output_hashes"]
        self.assertEqual(h["gzip_encoding"], "FIXED_RFC1951_STORED_BLOCKS")
        self.assertEqual(h["classification_ledger_plaintext_sha256"], "31be1e40330be6b149e4eb630339131258b4212d1639e13bead207feae50afe5")
        self.assertEqual(h["classification_ledger_gzip_sha256"], "34483c4096e21d943321bc12961a35a0685393401ee64b226a9a079255433bab")
        self.assertEqual(h["p0_ledger_plaintext_sha256"], "6c5866e3fdbf6381bb0b982b8642aa9c4d5ce9833469a97bcceda6dbea1d5633")
        self.assertEqual(h["p0_ledger_gzip_sha256"], "a64a1ce56761b3c135e68cd89b79cb458f8fc65f6f8b5b8255dfb8b18f45c61b")
        self.assertEqual(h["migration_ledger_plaintext_sha256"], "c63b792afc9e3a29c073fa284ba5e7c4059426c16d40c4855bc39c904f29abe4")
        self.assertEqual(h["migration_ledger_gzip_sha256"], "ca09698316d5c0460e926a1d5d2d33a46f3c78720ca9b1b9c2d32a800a05f784")

    def test_diagnostic_remains_non_authoritative_while_later_runtime_advances(self) -> None:
        boundaries = self.evidence["hard_boundaries"]
        self.assertTrue(boundaries["diagnostic_only"])
        self.assertFalse(boundaries["candidate_parser_authorized"])
        self.assertFalse(boundaries["formal_parser_changed"])
        self.assertFalse(boundaries["runtime_authority_changed"])
        self.assertFalse(boundaries["production_data_changed"])
        # This is the immutable historical status recorded when the diagnostic ran.
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertTrue(boundaries["stage4_alpha_live_locked"])
        latest = self.runtime["full_basis_last_completed_final"]
        self.assertGreaterEqual(self.runtime["schema_version"], 15)
        self.assertEqual(self.runtime["formal_runtime"]["runtime_generation"], "V17.30")
        self.assertEqual(latest["generation"], "V17.30")
        self.assertEqual(latest["run"], 31518370789)
        self.assertEqual(latest["artifact_id"], 9112098872)
        self.assertEqual(latest["numeric_observations"], 1051826)
        self.assertEqual(latest["document_error_count"], 1362)
        self.assertEqual(latest["unresolved_tie_count"], 1279)
        self.assertEqual(latest["verdict"], "FAIL_CLOSED")
        previous = self.runtime["previous_last_completed_full_basis_final"]
        self.assertEqual(previous["generation"], "V17.29")
        self.assertEqual(previous["run"], 31389854868)
        self.assertEqual(previous["artifact_id"], 9063271903)
        next_basis = self.runtime["next_full_basis_required"]
        self.assertEqual(next_basis["status"], "NONE_CURRENT_RUNTIME_ACCEPTED")
        # Current project state may advance to the historical final freeze; this
        # must not retroactively change the diagnostic evidence above.
        self.assertIn(self.project["stage3"]["status"], {"NOT_READY", "PASS_FROZEN_HISTORICAL"})
        self.assertEqual(self.project["stage3"]["pending_final_gates"], [])
        self.assertFalse(self.project["stage4_unlocked"])
        self.assertFalse(self.project["alpha_training_allowed"])
        self.assertFalse(self.project["live_signal_allowed"])
        self.assertEqual(self.project["freshness"]["status"], "STALE")


if __name__ == "__main__":
    unittest.main()
