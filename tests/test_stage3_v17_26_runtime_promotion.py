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
    """Retain completed V17.26 evidence after later runtime generations advance."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
        cls.activation = json.loads(ACTIVATION_MANIFEST.read_text(encoding="utf-8"))
        cls.evidence = json.loads(EVIDENCE_MANIFEST.read_text(encoding="utf-8"))

    def test_v17_26_manifest_is_retained_as_historical_authority(self) -> None:
        self.assertEqual(self.runtime["schema_version"], 13)
        historical = self.runtime["historical_full_basis_final"]
        self.assertEqual(historical["generation"], "V17.26")
        self.assertEqual(historical["run"], 30733013665)
        self.assertEqual(historical["head_sha"], "ed81a8f167c7b158167a8bdafa1799b7047666af")
        self.assertEqual(historical["artifact_id"], 8828600783)
        self.assertEqual(historical["artifact_digest"], "sha256:7f2e707e9192af527ff0444b48caf6bebfbfa1ef7559ec2810b6f47b1790567b")
        self.assertEqual(historical["document_rows"], 121354)
        self.assertEqual(historical["numeric_observations"], 1051778)
        self.assertEqual(historical["document_error_count"], 1378)
        self.assertEqual(historical["unresolved_tie_count"], 1295)
        self.assertEqual(historical["verdict"], "FAIL_CLOSED")
        self.assertIs(historical["retained"], True)

    def test_v17_29_is_latest_completed_full_basis(self) -> None:
        self.assertEqual(self.runtime["formal_runtime"]["runtime_generation"], "V17.29")
        full = self.runtime["full_basis_last_completed_final"]
        self.assertEqual(full["generation"], "V17.29")
        self.assertEqual(full["run"], 31389854868)
        self.assertEqual(full["document_rows"], 121354)
        self.assertEqual(full["numeric_observations"], 1051820)
        self.assertEqual(full["document_error_count"], 1364)
        self.assertEqual(full["unresolved_tie_count"], 1281)
        self.assertEqual(full["verdict"], "FAIL_CLOSED")
        previous = self.runtime["previous_last_completed_full_basis_final"]
        self.assertEqual(previous["generation"], "V17.28")
        self.assertEqual(previous["run"], 30997260730)
        self.assertIs(previous["retained"], True)
        next_basis = self.runtime["next_full_basis_required"]
        self.assertIsNone(next_basis["generation"])
        self.assertEqual(next_basis["status"], "NONE_CURRENT_RUNTIME_ACCEPTED")

    def test_v17_26_parser_and_extractor_contract_remain_importable(self) -> None:
        self.assertEqual(extractor.RUNTIME_GENERATION, "V17.26")
        self.assertEqual(extractor.SHARD_GATE, "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_26")
        self.assertEqual(extractor.METHOD, "CNINFO_ORIGINAL_PDF_PYMUPDF_V16_V17_26_EXACT_SOURCE_BALANCE_ONLY_PRODUCTION")
        self.assertEqual(extractor.METHODOLOGY_VERSION, "V3.3.6-V17.26")
        self.assertEqual(parser.METHOD, "V17_26_EXACT_SOURCE_BALANCE_ONLY_PRODUCTION")
        self.assertEqual(
            set(parser.TARGETS),
            {
                "320e3a950a4768e73766d57a09bcf34d893d4da949b8ed5a1b2f887852e76229",
                "fa72059d35715f20df620691538528f720fe3ae42581c172c853f26799befb93",
            },
        )
        self.assertEqual(set(parser.ALLOWED_CONCEPTS), {"TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"})

    def test_v17_26_exact_source_scope_is_retained(self) -> None:
        gates = self.runtime["inherited_v17_26_exact_source_gates"]
        self.assertEqual(gates["allowed_concepts"], ["TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"])
        self.assertIs(gates["non_balance_concepts_fail_closed"], True)
        self.assertEqual(set(gates["targets"]), {"1207035181", "1221568845"})
        self.assertTrue(all(target["numeric_observations"] == 3 for target in gates["targets"].values()))

    def test_activation_manifest_retains_v17_26_full_basis_evidence(self) -> None:
        self.assertEqual(self.activation["schema_version"], 15)
        current = self.activation["accepted_production_runtime"]
        self.assertEqual(current["generation"], "V17.29")
        self.assertIs(current["full_basis_execution_pending"], False)
        self.assertEqual(current["last_completed_full_basis_generation"], "V17.29")
        self.assertEqual(current["last_completed_full_basis_run"], 31389854868)
        self.assertEqual(current["execution_verdict"], "PASS")
        self.assertEqual(current["data_verdict"], "FAIL_CLOSED")

        historical = self.activation["accepted_v17_26_full_basis_evidence"]
        self.assertEqual(historical["run"], 30733013665)
        self.assertEqual(historical["artifact_digest"], self.evidence["accepted_run"]["artifact_digest"])
        self.assertEqual(historical["document_count"], 121354)
        self.assertEqual(historical["numeric_observation_count"], 1051778)
        self.assertEqual(historical["document_error_count"], 1378)
        self.assertEqual(historical["unresolved_tie_count"], 1295)
        self.assertEqual(historical["final_data_verdict"], "FAIL_CLOSED")
        self.assertIs(historical["historical_full_basis_authority_retained"], True)
        boundaries = self.activation["hard_boundaries"]
        self.assertIs(boundaries["v17_29_full_basis_execution_pending"], False)
        self.assertEqual(boundaries["remaining_document_errors"], 1364)
        self.assertEqual(boundaries["remaining_unresolved_ties"], 1281)
        self.assertEqual(boundaries["stage3_status"], "NOT_READY")
        self.assertIs(boundaries["stage4_alpha_live_locked"], True)
        self.assertIs(boundaries["committed_production_data_changed"], False)
        self.assertIs(boundaries["trained_model_changed"], False)
        self.assertIs(boundaries["main_changed"], False)


if __name__ == "__main__":
    unittest.main()
