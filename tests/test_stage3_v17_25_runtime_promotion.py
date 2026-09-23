from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import extract_stage3_financial_pdf_values_v15 as extractor
import stage3_financial_pdf_parser_v17 as parser


class V1725RuntimePromotionTests(unittest.TestCase):
    def test_runtime_identity_is_generation_locked(self):
        self.assertEqual(extractor.RUNTIME_GENERATION, "V17.25")
        self.assertEqual(
            extractor.SHARD_GATE,
            "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_25",
        )
        self.assertEqual(
            extractor.METHOD,
            "CNINFO_ORIGINAL_PDF_PYMUPDF_V15_V17_25_EXACT_SOURCE_GENERIC_GROUP_WITNESS_PRODUCTION",
        )
        self.assertEqual(extractor.METHODOLOGY_VERSION, "V3.3.5-V17.25")
        self.assertEqual(
            parser.METHOD,
            "V17_25_EXACT_SOURCE_GENERIC_GROUP_WITNESS_PRODUCTION",
        )

    def test_manifest_rewrite_preserves_counts_and_sets_v17_25_identity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "financial_extract_shard03.manifest.json"
            original = {
                "gate": "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_24",
                "runtime_generation": "V17.24",
                "parser_method": extractor.METHOD,
                "methodology_version": extractor.METHODOLOGY_VERSION,
                "shard": 3,
                "shards": 64,
                "selected_versions": 1900,
                "document_rows": 1900,
                "numeric_rows": 16000,
                "pass": True,
                "errors": [],
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            extractor._rewrite_v17_25_shard_manifest(td, 3)
            rewritten = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(rewritten["gate"], extractor.SHARD_GATE)
        self.assertEqual(
            rewritten["runtime_generation"], extractor.RUNTIME_GENERATION
        )
        self.assertEqual(rewritten["selected_versions"], 1900)
        self.assertEqual(rewritten["document_rows"], 1900)
        self.assertEqual(rewritten["numeric_rows"], 16000)
        self.assertIs(rewritten["pass"], True)
        self.assertEqual(rewritten["errors"], [])

    def test_manifest_rewrite_rejects_mixed_parser_generation(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "financial_extract_shard00.manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "parser_method": "OLD_METHOD",
                        "methodology_version": extractor.METHODOLOGY_VERSION,
                        "shard": 0,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "parser method mismatch"):
                extractor._rewrite_v17_25_shard_manifest(td, 0)


if __name__ == "__main__":
    unittest.main()
