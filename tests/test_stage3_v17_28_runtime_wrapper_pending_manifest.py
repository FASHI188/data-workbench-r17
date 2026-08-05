from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PENDING = ROOT / "governance/stage3_s3g1j_v17_28_runtime_wrapper_pending.json"
RUNTIME = ROOT / "governance/stage3_s3g1j_runtime_manifest.json"
ACTIVATION = ROOT / "governance/stage3_workflow_activation_manifest.json"


class V1728RuntimeWrapperPendingManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pending = json.loads(PENDING.read_text(encoding="utf-8"))
        cls.runtime = json.loads(RUNTIME.read_text(encoding="utf-8"))
        cls.activation = json.loads(ACTIVATION.read_text(encoding="utf-8"))

    def test_pending_manifest_is_not_runtime_authority(self) -> None:
        self.assertEqual(self.pending["status"], "IMPLEMENTATION_UNDER_REVIEW_NOT_ACTIVATED")
        self.assertEqual(self.pending["generation"], "V17.28")
        boundaries = self.pending["hard_boundaries"]
        self.assertIs(boundaries["runtime_authority_changed"], False)
        self.assertIs(boundaries["workflow_activation_manifest_changed"], False)
        self.assertIs(boundaries["fresh_64_shard_execution_started"], False)
        self.assertIs(boundaries["production_data_changed"], False)
        self.assertIs(boundaries["trained_model_changed"], False)
        self.assertIs(boundaries["main_changed"], False)

    def test_formal_runtime_remains_v17_27_until_separate_activation(self) -> None:
        self.assertEqual(self.runtime["current_production_authority"]["generation"], "V17.27")
        self.assertEqual(self.runtime["formal_runtime"]["runtime_generation"], "V17.27")
        self.assertEqual(self.activation["accepted_production_runtime"]["generation"], "V17.27")
        self.assertEqual(self.runtime["project_status"]["stage3"], "NOT_READY")
        self.assertEqual(self.runtime["project_status"]["stage4"], "LOCKED")

    def test_candidate_evidence_and_implementation_are_exact(self) -> None:
        evidence = self.pending["candidate_evidence"]
        self.assertEqual(evidence["governance_pr"], 93)
        self.assertEqual(evidence["governance_merge_commit"], "9ea0940dcfd1a371af7877143dd173e12fe5a59c")
        self.assertEqual(evidence["candidate_run"], 30827493788)
        self.assertEqual(evidence["candidate_artifact_id"], 8861519922)
        self.assertEqual(
            evidence["candidate_artifact_digest"],
            "sha256:8a87dfed63160374fc04c88c3d02a93eedac6ae239ae559b64aaad93c71d22c1",
        )
        implementation = self.pending["implementation"]
        self.assertEqual(implementation["production_parser"], "scripts/stage3_financial_pdf_parser_v20.py")
        self.assertEqual(implementation["extractor"], "scripts/extract_stage3_financial_pdf_values_v18.py")
        self.assertEqual(implementation["target_announcement_ids"], ["1207621057", "1209825769"])
        self.assertIs(implementation["non_target_delegates_v17_27_exactly"], True)
        self.assertEqual(
            implementation["allowed_concepts"],
            ["TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"],
        )


if __name__ == "__main__":
    unittest.main()
