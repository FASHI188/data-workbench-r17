from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import extract_stage3_financial_pdf_values_v14 as extractor
import stage3_financial_pdf_parser_v15 as parser


class V1724ProductionTests(unittest.TestCase):
    def test_v17_21_and_earlier_paths_have_absolute_priority(self):
        sentinel_block = {"sentinel": object()}
        sentinel_meta = {"source": "V17_21"}
        with patch.object(
            parser.v13,
            "_validated_balance_sheet_contextual",
            return_value=(sentinel_block, sentinel_meta),
        ), patch.object(
            parser,
            "_v17_24_production_balance_block",
        ) as fallback:
            block, meta = parser._validated_balance_sheet_contextual(
                object(), "2024-09-30"
            )
        self.assertIs(block, sentinel_block)
        self.assertIs(meta, sentinel_meta)
        fallback.assert_not_called()

    def test_promotion_removes_candidate_only_flag(self):
        with patch.object(
            parser.candidate,
            "_v17_24_balance_block",
            return_value=(
                {"TOTAL_ASSETS": object()},
                {"candidate_only": True},
            ),
        ):
            block, meta = parser._v17_24_production_balance_block(
                object(), "2024-09-30"
            )
        self.assertIn("TOTAL_ASSETS", block)
        self.assertFalse(meta["candidate_only"])
        self.assertEqual(meta["production_runtime_generation"], "V17.24")

    def test_formal_extractor_identity(self):
        self.assertEqual(
            extractor.METHOD,
            "CNINFO_ORIGINAL_PDF_PYMUPDF_V14_V17_24_EXACT_CORRUPTED_GROUP_EQUITY_ALIAS_FINAL_FALLBACK",
        )
        self.assertEqual(extractor.METHODOLOGY_VERSION, "V3.3.4-V17.24")
        self.assertEqual(
            extractor.SHARD_GATE,
            "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_24",
        )

    def test_manifest_rewrite_locks_v17_24_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "financial_extract_shard03.manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "gate": "OLD",
                        "parser_method": extractor.METHOD,
                        "methodology_version": extractor.METHODOLOGY_VERSION,
                        "shard": 3,
                    }
                ),
                encoding="utf-8",
            )
            extractor._rewrite_v17_24_shard_manifest(tmp, 3)
            result = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result["gate"], extractor.SHARD_GATE)
        self.assertEqual(result["runtime_generation"], "V17.24")


if __name__ == "__main__":
    unittest.main()
