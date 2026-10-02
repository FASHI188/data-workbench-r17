from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import extract_stage3_financial_pdf_values_v13 as extractor
import finalize_stage3_financial_pdf_values as finalizer


class V1721ShardManifestTests(unittest.TestCase):
    def test_rewrite_replaces_historical_v17_17_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "financial_extract_shard07.manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "gate": "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_17",
                        "parser_method": extractor.METHOD,
                        "methodology_version": extractor.METHODOLOGY_VERSION,
                        "shard": 7,
                    }
                ),
                encoding="utf-8",
            )

            extractor._rewrite_v17_21_shard_manifest(str(root), 7)
            actual = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(actual["gate"], extractor.SHARD_GATE)
        self.assertEqual(actual["runtime_generation"], "V17.21")
        self.assertEqual(actual["parser_method"], extractor.METHOD)
        self.assertEqual(actual["methodology_version"], extractor.METHODOLOGY_VERSION)

    def test_rewrite_rejects_wrong_parser_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "financial_extract_shard01.manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "gate": "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_17",
                        "parser_method": "WRONG",
                        "methodology_version": extractor.METHODOLOGY_VERSION,
                        "shard": 1,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "parser method mismatch"):
                extractor._rewrite_v17_21_shard_manifest(str(root), 1)


class S3G1JFinalizerIdentityTests(unittest.TestCase):
    def _manifests(self, root: Path) -> list[Path]:
        paths = []
        for shard in range(64):
            path = root / f"financial_extract_shard{shard:02d}.manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "gate": extractor.SHARD_GATE,
                        "parser_method": extractor.METHOD,
                        "methodology_version": extractor.METHODOLOGY_VERSION,
                        "runtime_generation": "V17.21",
                        "shard": shard,
                        "shards": 64,
                        "selected_versions": 10,
                        "document_rows": 10,
                        "numeric_rows": 30,
                        "error_count": 0,
                        "errors": [],
                        "source_format": "PDF",
                        "original_pdf_authority": True,
                        "current_f10_historical_backfill_used": False,
                        "pass": True,
                        "stage4_alpha_locked": True,
                    }
                ),
                encoding="utf-8",
            )
            paths.append(path)
        return paths

    def test_uniform_v17_21_manifests_pass_identity_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._manifests(Path(tmp))
            errors: list[str] = []
            manifest_map, identity = finalizer._validate_shard_manifests(
                paths,
                640,
                extractor.SHARD_GATE,
                extractor.METHOD,
                extractor.METHODOLOGY_VERSION,
                errors,
            )

        self.assertEqual(errors, [])
        self.assertEqual(set(manifest_map), set(range(64)))
        self.assertEqual(identity["gate"], extractor.SHARD_GATE)
        self.assertEqual(identity["runtime_generation"], "V17.21")
        self.assertEqual(identity["document_rows_total"], 640)
        self.assertEqual(identity["numeric_rows_total"], 1920)

    def test_mixed_v17_17_v17_21_shards_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._manifests(root)
            mixed = json.loads(paths[17].read_text(encoding="utf-8"))
            mixed["gate"] = "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_17"
            mixed["runtime_generation"] = "V17.17"
            paths[17].write_text(json.dumps(mixed), encoding="utf-8")
            errors: list[str] = []
            finalizer._validate_shard_manifests(
                paths,
                640,
                extractor.SHARD_GATE,
                extractor.METHOD,
                extractor.METHODOLOGY_VERSION,
                errors,
            )

        self.assertTrue(any("mixed or missing shard gate" in item for item in errors))
        self.assertTrue(any("mixed or missing runtime generation" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
