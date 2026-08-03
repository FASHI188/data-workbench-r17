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
    """Retain the completed V17.26 authority after V17.27 full-basis acceptance."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
        cls.activation = json.loads(ACTIVATION_MANIFEST.read_text(encoding="utf-8"))
        cls.evidence = json.loads(EVIDENCE_MANIFEST.read_text(encoding="utf-8"))

    def test_v17_26_manifest_is_retained_as_historical_authority(self) -> None:
        self.assertEqual(self.runtime["schema_version"], 9)
        previous = self.runtime["previous_manifest"]
        self.assertEqual(previous["schema_version"], 8)
        historical = self.runtime["historical_full_basis_final"]
        self.assertEqual(historical["generation"], "V17.26")
        self.assertEqual(historical["run"], 30733013665)
        self.assertEqual(
            historical["head_sha"],
            "ed81a8f167c7b158167a8bdafa1799b7047666af",
        )
        self.assertEqual(historical["artifact_id"], 8828600783)
        self.assertEqual(
            historical["artifact_digest"],
            "sha256:7f2e707e9192af527ff0444b48caf6bebfbfa1ef7559ec2810b6f47b1790567b",
        )
        self.assertEqual(historical["document_rows"], 121354)
        self.assertEqual(historical["numeric_observations"], 1051778)
        self.assertEqual(historical["document_error_count"], 1378)
        self.assertEqual(historical["unresolved_tie_count"], 1295)
        self.assertEqual(historical["verdict"], "FAIL_CLOSED")
        self.assertIs(historical["retained"], True)

    def test_v17_27_is_now_last_completed_full_basis(self) -> None:
        full = self.runtime["full_basis_last_completed_final"]
        self.assertEqual(full["generation"], "V17.27")
        self.assertEqual(full["run"], 30806818977)
        self.assertEqual(full["document_rows"], 121354)
        self.assertEqual(full["numeric_observations"], 1051793)
        self.assertEqual(full["document_error_count"], 1373)
        self.assertEqual(full["unresolved_tie_count"], 1290)
        self.assertEqual(full["verdict"], "FAIL_CLOSED")

    def test_v17_26_parser_and_extractor_contract_remain_importable(self) -> None:
        self.assertEqual(extractor.RUNTIME_GENERATION, "V17.26")
        self.assertEqual(
            extractor.SHARD_GATE, "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_26"
        )
        self.assertEqual(
            extractor.METHOD,
            "CNINFO_ORIGINAL_PDF_PYMUPDF_V16_V17_26_EXACT_SOURCE_BALANCE_ONLY_PRODUCTION",
        )
        self.assertEqual(extractor.METHODOLOGY_VERSION, "V3.3.6-V17.26")
        self.assertEqual(parser.METHOD, "V17_26_EXACT_SOURCE_BALANCE_ONLY_PRODUCTION")
        self.assertEqual(
            set(parser.TARGETS),
            {
                "320e3a950a4768e73766d57a09bcf34d893d4da949b8ed5a1b2f887852e76229",
                "fa72059d35715f20df620691538528f720fe3ae42581c172c853f26799befb93",
            },
        )
        self.assertEqual(
            set(parser.ALLOWED_CONCEPTS),
            {"TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"},
        )

    def test_v17_26_exact_source_scope_is_retained(self) -> None:
        gates = self.runtime["inherited_v17_26_exact_source_gates"]
        self.assertEqual(
            gates["allowed_concepts"],
            ["TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"],
        )
        self.assertIs(gates["non_balance_concepts_fail_closed"], True)
        self.assertEqual(set(gates["targets"]), {"1207035181", "1221568845"})
        self.assertTrue(
            all(target["numeric_observations"] == 3 for target in gates["targets"].values())
        )

    def test_activation_manifest_retains_v17_26_full_basis_evidence(self) -> None:
        self.assertEqual(self.activation["schema_version"], 11)
        current = self.activation["accepted_production_runtime"]
        self.assertEqual(current["generation"], "V17.27")
        self.assertIs(current["full_basis_execution_pending"], False)
        historical = self.activation["accepted_v17_26_full_basis_evidence"]
        self.assertEqual(historical["run"], 30733013665)
        self.assertEqual(
            historical["artifact_digest"],
            self.evidence["accepted_run"]["artifact_digest"],
        )
        self.assertEqual(historical["document_count"], 121354)
        self.assertEqual(historical["numeric_observation_count"], 1051778)
        self.assertEqual(historical["document_error_count"], 1378)
        self.assertEqual(historical["final_data_verdict"], "FAIL_CLOSED")
        self.assertIs(historical["historical_full_basis_authority_retained"], True)
        boundaries = self.activation["hard_boundaries"]
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["committed_production_data_changed"], False)
        self.assertIs(boundaries["trained_model_changed"], False)
        self.assertIs(boundaries["main_changed"], False)


if __name__ == "__main__":
    unittest.main()
