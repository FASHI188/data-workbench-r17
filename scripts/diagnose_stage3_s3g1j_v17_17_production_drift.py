#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

import fitz
import requests

import extract_stage3_financial_pdf_values_v11 as production_v11
import extract_stage3_financial_pdf_values_v12 as production_v12
import stage3_financial_spatial_alias_v17_17 as spatial_v17_17
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard

TARGET_IDS = {"1207399857", "1223364547"}
BALANCE_CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def download(url: str) -> bytes:
    response = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.17-production-drift-diagnostic",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def balance_found(parsed: dict) -> bool:
    observations = parsed.get("observations") or {}
    return all((observations.get(concept) or {}).get("status") == "FOUND" for concept in BALANCE_CONCEPTS)


def compact_parsed(parsed: dict) -> dict:
    observations = parsed.get("observations") or {}
    return {
        "balance_found": balance_found(parsed),
        "parser_version": parsed.get("parser_version"),
        "balance_sheet_block": parsed.get("balance_sheet_block"),
        "validation_errors": parsed.get("validation_errors"),
        "balance_observations": {concept: observations.get(concept) for concept in BALANCE_CONCEPTS},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--acceptance", required=True)
    ap.add_argument("--announcement-id", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    aid = str(args.announcement_id)
    if aid not in TARGET_IDS:
        raise ValueError(f"diagnostic frozen to {sorted(TARGET_IDS)}")
    accepted = json.loads(Path(args.acceptance).read_text(encoding="utf-8"))
    accepted_rows = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if not accepted.get("pass") or aid not in accepted_rows:
        raise ValueError("not the accepted V17.11 residual source state")

    version = read_versions(Path(args.versions))[aid]
    raw = download(version["canonical_source_url"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != accepted_rows[aid]["sha256"]:
        raise ValueError("source SHA changed")

    v11 = compact_parsed(production_v11.parse_pdf_bytes(raw, version["economic_date"]))
    v12 = compact_parsed(production_v12.parse_pdf_bytes(raw, version["economic_date"]))
    with _mupdf_diagnostic_guard():
        with fitz.open(stream=raw, filetype="pdf") as doc:
            direct = spatial_v17_17.diagnose_spatial_balance_sheet_v17_17(doc, version["economic_date"])

    report = {
        "gate": "S3G1J_V17_17_EXACT_TWO_PRODUCTION_DRIFT_DIAGNOSTIC",
        "pass": True,
        "diagnostic_only": True,
        "no_parser_change": True,
        "announcement_id": aid,
        "source_code": version["source_code"],
        "report_family": version["report_family"],
        "economic_date": version["economic_date"],
        "canonical_title": version["canonical_title"],
        "canonical_source_url": version["canonical_source_url"],
        "source_sha256": digest,
        "v17_15_production": v11,
        "v17_17_production": v12,
        "v17_17_direct": direct,
        "production_found_changed": v11["balance_found"] != v12["balance_found"],
        "production_block_changed": v11["balance_sheet_block"] != v12["balance_sheet_block"],
        "accounting_tolerance_changed": False,
        "source_policy_changed": False,
        "stage4_alpha_locked": True,
        "errors": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "announcement_id": aid,
        "v17_15_found": v11["balance_found"],
        "v17_17_found": v12["balance_found"],
        "direct_recovered": direct.get("recovered"),
        "v17_15_arbitration": (v11.get("balance_sheet_block") or {}).get("arbitration"),
        "v17_17_arbitration": (v12.get("balance_sheet_block") or {}).get("arbitration"),
        "pass": True,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
