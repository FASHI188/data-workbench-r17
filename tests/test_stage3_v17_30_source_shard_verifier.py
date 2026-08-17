from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/verify_stage3_s3g1j_v17_30_source_shards.py"


def load_module():
    spec=importlib.util.spec_from_file_location("verify_v1730_shards",SCRIPT)
    assert spec and spec.loader
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_single_shard(root: Path, mod, *, include_numeric_rows: bool=True, legacy_numeric_observations: bool=False) -> None:
    shard=root/"artifact-0"
    shard.mkdir()
    data=shard/"payload.txt"
    data.write_text("abc\n",encoding="utf-8")
    digest=mod.sha256(data)
    (shard/"output_sha256.txt").write_text(f"{digest}  payload.txt\n",encoding="utf-8")
    manifest={
        "shard":0,"shards":1,"gate":mod.EXPECTED_GATE,
        "runtime_generation":mod.EXPECTED_RUNTIME,
        "parser_method":mod.EXPECTED_METHOD,
        "methodology_version":mod.EXPECTED_METHODOLOGY,
        "source_format":"PDF","original_pdf_authority":True,
        "current_f10_historical_backfill_used":False,
        "stage4_alpha_locked":True,"document_rows":2,"selected_versions":2,
        "error_count":1,"errors":["x"],
    }
    if include_numeric_rows:
        manifest["numeric_rows"]=3
    if legacy_numeric_observations:
        manifest["numeric_observations"]=3
    (shard/"financial_extract_shard00.manifest.json").write_text(json.dumps(manifest),encoding="utf-8")


class V1730SourceShardVerifierTest(unittest.TestCase):
    def test_constants_lock_v17_30_identity(self)->None:
        mod=load_module()
        self.assertEqual(mod.EXPECTED_SHARDS,64)
        self.assertEqual(mod.EXPECTED_DOCUMENTS,121354)
        self.assertEqual(mod.EXPECTED_NUMERIC,1051826)
        self.assertEqual(mod.EXPECTED_ERRORS,1362)
        self.assertEqual(mod.EXPECTED_RUNTIME,"V17.30")
        self.assertEqual(mod.EXPECTED_GATE,"S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_30")
        self.assertIn("PYMUPDF_V20_V17_30",mod.EXPECTED_METHOD)

    def test_hash_ledger_rejects_duplicate_path(self)->None:
        mod=load_module()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"output_sha256.txt"
            digest="0"*64
            p.write_text(f"{digest}  a.txt\n{digest}  a.txt\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"duplicate hash-ledger path"):
                mod.parse_hash_ledger(p)

    def test_synthetic_single_shard_verifies_real_numeric_rows_schema(self)->None:
        mod=load_module()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            write_single_shard(root,mod)
            mod.EXPECTED_SHARDS=1
            mod.EXPECTED_DOCUMENTS=2
            mod.EXPECTED_NUMERIC=3
            mod.EXPECTED_ERRORS=1
            report=mod.verify(root)
            self.assertTrue(report["pass"])
            self.assertTrue(report["all_output_sha256_ledgers_recomputed"])
            self.assertEqual(report["shard_count"],1)
            self.assertEqual(report["numeric_rows"],3)

    def test_legacy_numeric_observations_cannot_substitute_for_numeric_rows(self)->None:
        mod=load_module()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            write_single_shard(root,mod,include_numeric_rows=False,legacy_numeric_observations=True)
            mod.EXPECTED_SHARDS=1
            mod.EXPECTED_DOCUMENTS=2
            mod.EXPECTED_NUMERIC=3
            mod.EXPECTED_ERRORS=1
            with self.assertRaisesRegex(ValueError,"missing numeric_rows"):
                mod.verify(root)


if __name__=="__main__":
    unittest.main()
