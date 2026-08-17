#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

import extract_stage3_financial_pdf_values_v14 as prior
from stage3_financial_pdf_parser_v17 import parse_pdf_bytes as v17_25_parse_pdf_bytes

base = prior.base
METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V15_V17_25_EXACT_SOURCE_GENERIC_GROUP_WITNESS_PRODUCTION"
METHODOLOGY_VERSION = "V3.3.5-V17.25"
SHARD_GATE = "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_25"
RUNTIME_GENERATION = "V17.25"

sha_file = prior.sha_file
write_deterministic_csv_gz = prior.write_deterministic_csv_gz
slim_evidence = prior.slim_evidence


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    parsed = dict(v17_25_parse_pdf_bytes(raw, economic_date))
    parsed["declared_a_share_codes"] = prior.prior.prior.v15.v14.v9.declared_a_share_codes(raw)
    return parsed


def _required_cli_value(flag: str) -> str:
    try:
        index = sys.argv.index(flag)
        value = sys.argv[index + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError(f"missing required CLI value {flag}") from exc
    if not value:
        raise ValueError(f"empty required CLI value {flag}")
    return value


def _rewrite_v17_25_shard_manifest(out_root: str, shard: int) -> None:
    manifest_path = Path(out_root) / f"financial_extract_shard{shard:02d}.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("parser_method") != METHOD:
        raise ValueError(
            f"V17.25 shard parser method mismatch: {manifest.get('parser_method')}"
        )
    if manifest.get("methodology_version") != METHODOLOGY_VERSION:
        raise ValueError(
            f"V17.25 shard methodology mismatch: {manifest.get('methodology_version')}"
        )
    if int(manifest.get("shard", -1)) != shard:
        raise ValueError(
            f"V17.25 shard identity mismatch expected={shard} "
            f"actual={manifest.get('shard')}"
        )
    manifest["gate"] = SHARD_GATE
    manifest["runtime_generation"] = RUNTIME_GENERATION
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    out_root = _required_cli_value("--out")
    shard = int(_required_cli_value("--shard"))

    original_parse = prior.parse_pdf_bytes
    original_method = prior.METHOD
    original_methodology = prior.METHODOLOGY_VERSION
    prior.parse_pdf_bytes = parse_pdf_bytes
    prior.METHOD = METHOD
    prior.METHODOLOGY_VERSION = METHODOLOGY_VERSION
    try:
        result = prior.main()
    finally:
        prior.parse_pdf_bytes = original_parse
        prior.METHOD = original_method
        prior.METHODOLOGY_VERSION = original_methodology

    _rewrite_v17_25_shard_manifest(out_root, shard)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
