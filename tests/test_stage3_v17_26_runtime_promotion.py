from __future__ import annotations

import json
import unittest
from pathlib import Path

import extract_stage3_financial_pdf_values_v16 as extractor
import stage3_financial_pdf_parser_v18 as parser


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MANIFEST = ROOT / "governance/stage3_s3g1j_runtime_manifest.json"
ACTIVATION_MANIFEST = ROOT / "governance/stage3_workflow_activation_manifest.json"
EVIDENCE_MANIFEST = ROOT / "governance/stage3_s3g1j_v17_26_full_final.json"


class V1726RuntimePromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
        cls.activation = json.loads(ACTIVATION_MANIFEST.read_text(encoding="utf-8"))
        cls.evidence = json.loads(EVIDENCE_MANIFEST.read_text(encoding="utf-8"))

    def test_previous_v17_25_manifest_is_frozen(self) -> None:
        self.assertEqual(self.runtime["schema_version"], 7)
        previous = self.runtime["previous_manifest"]
        self.assertEqual(previous["schema_version"], 6)
        self.assertEqual(
            previous["source_head_sha"],
            "153634a632d7df1c8a8dc94602e52c6a862dd188",
        )
        self.assertEqual(
            previous["git_blob_sha"],
            "53b0d4bf68b3425aa1403e93a3d2db0922ed9860",
        )
        self.assertEqual(previous["formal_runtime_generation"], "V17.25")
        self.assertEqual(previous["accepted_production_run"], 30691109646)

    def test_formal_runtime_is_exact_v17_26(self) -> None:
        authority = self.runtime["current_production_authority"]
        self.assertEqual(authority["generation"], "V17.26")
        self.assertEqual(
            authority["status"], "FULL_BASIS_EXECUTION_ACCEPTED_FAIL_CLOSED"
        )
        acceptance = authority["full_basis_acceptance"]
        self.assertEqual(acceptance["run"], 30733013665)
        self.assertEqual(
            acceptance["head_sha"],
            "ed81a8f167c7b158167a8bdafa1799b7047666af",
        )
        self.assertEqual(acceptance["artifact_id"], 8828600783)
        self.assertEqual(
            acceptance["artifact_digest"],
            "sha256:7f2e707e9192af527ff0444b48caf6bebfbfa1ef7559ec2810b6f47b1790567b",
        )
        self.assertIs(acceptance["execution_pass"], True)
        self.assertIs(acceptance["document_non_regression_pass"], True)
        self.assertIs(acceptance["numeric_non_regression_pass"], True)
        self.assertIs(acceptance["final_data_gate_pass"], False)
        self.assertEqual(acceptance["final_data_verdict"], "FAIL_CLOSED")

        formal = self.runtime["formal_runtime"]
        self.assertEqual(formal["runtime_generation"], "V17.26")
        self.assertEqual(
            formal["shard_gate"],
            "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_26",
        )
        self.assertEqual(
            formal["extractor_path"],
            "scripts/extract_stage3_financial_pdf_values_v16.py",
        )
        self.assertEqual(formal["extractor_method"], extractor.METHOD)
        self.assertEqual(
            formal["parser_path"], "scripts/stage3_financial_pdf_parser_v18.py"
        )
        self.assertEqual(formal["parser_method"], parser.METHOD)
        self.assertEqual(formal["methodology_version"], "V3.3.6-V17.26")
        self.assertEqual(formal["gzip_mtime"], 0)
        self.assertEqual(formal["gzip_embedded_filename"], "")
        self.assertIs(formal["mixed_runtime_generation_forbidden"], True)

    def test_exact_source_scope_remains_a_l_e_only(self) -> None:
        gates = self.runtime["v17_26_exact_source_gates"]
        self.assertEqual(
            gates["allowed_concepts"],
            ["TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"],
        )
        self.assertIs(gates["non_balance_concepts_fail_closed"], True)
        self.assertEqual(set(gates["targets"]), {"1207035181", "1221568845"})
        self.assertTrue(
            all(target["numeric_observations"] == 3 for target in gates["targets"].values())
        )
        invariants = self.runtime["hard_invariants"]
        self.assertIs(invariants["candidate_resolver_reused_for_v17_26_targets"], False)
        self.assertIs(invariants["non_balance_target_concepts_promoted"], False)
        self.assertIs(invariants["previous_v17_25_non_target_values_required_equal"], True)
        self.assertIs(invariants["stage4_alpha_locked"], True)

    def test_full_basis_final_is_accepted_but_fail_closed(self) -> None:
        full = self.runtime["full_basis_last_completed_final"]
        self.assertEqual(full["generation"], "V17.26")
        self.assertEqual(full["run"], 30733013665)
        self.assertEqual(full["canonical_report_version_moments"], 121354)
        self.assertEqual(full["document_rows"], 121354)
        self.assertEqual(full["numeric_observations"], 1051778)
        self.assertEqual(full["document_error_count"], 1378)
        self.assertEqual(full["unresolved_tie_count"], 1295)
        self.assertEqual(
            full["changed_announcement_ids"], ["1207035181", "1221568845"]
        )
        self.assertEqual(full["unexpected_regression_count"], 0)
        self.assertEqual(full["verdict"], "FAIL_CLOSED")
        self.assertEqual(
            self.runtime["production_final_status"],
            "FULL_BASIS_EXECUTION_ACCEPTED_FAIL_CLOSED",
        )

    def test_activation_manifest_preserves_runtime_under_diagnostic_evidence(self) -> None:
        self.assertEqual(self.activation["schema_version"], 9)
        accepted = self.activation["accepted_production_runtime"]
        self.assertEqual(accepted["generation"], "V17.26")
        self.assertEqual(accepted["runtime_manifest_schema"], 7)
        self.assertIs(accepted["runtime_manifest_promotion_pending"], False)
        self.assertEqual(accepted["execution_verdict"], "PASS")
        self.assertEqual(accepted["data_verdict"], "FAIL_CLOSED")
        evidence = self.activation["accepted_v17_26_full_basis_evidence"]
        self.assertIs(evidence["runtime_manifest_promotion_pending"], False)
        self.assertEqual(
            evidence["artifact_digest"],
            self.evidence["accepted_run"]["artifact_digest"],
        )
        classification = self.activation["accepted_v17_26_residual_classification"]
        self.assertIs(classification["diagnostic_only"], True)
        self.assertIs(classification["runtime_authority_changed"], False)
        self.assertEqual(classification["residual_document_rows"], 1378)
        boundaries = self.activation["hard_boundaries"]
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["committed_production_data_changed"], False)
        self.assertIs(boundaries["trained_model_changed"], False)
        self.assertIs(boundaries["main_changed"], False)
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


if __name__ == "__main__":
    unittest.main()
