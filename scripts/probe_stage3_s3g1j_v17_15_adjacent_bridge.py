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

import stage3_financial_spatial_alias_v16_7 as v167
import stage3_financial_spatial_alias_v17_15 as v1715
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard

TARGET_IDS = {"1212731093", "1217717273", "1225153907", "1219411922"}


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def download(url: str) -> bytes:
    response = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.15-adjacent-bridge-experiment",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--announcement-id", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    aid = str(args.announcement_id)
    if aid not in TARGET_IDS:
        raise ValueError(f"experiment frozen to {sorted(TARGET_IDS)}")
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    diagnostics = {str(x["announcement_id"]): x for x in summary.get("diagnostics") or []}
    target_set = {x for x, row in diagnostics.items() if row.get("category") == "MISSING_CONCEPT_NO_RIGHT_AMOUNT"}
    if not summary.get("pass") or target_set != TARGET_IDS:
        raise ValueError("not the accepted V17.12 exact-four no-right-amount state")
    expected = diagnostics[aid]
    versions = read_versions(Path(args.versions))
    version = versions[aid]

    raw = download(version["canonical_source_url"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected["sha256"]:
        raise ValueError(f"source SHA changed expected={expected['sha256']} actual={digest}")

    with _mupdf_diagnostic_guard():
        with fitz.open(stream=raw, filetype="pdf") as doc:
            baseline = v167.diagnose_spatial_balance_sheet_v16_7(doc, version["economic_date"])
            candidate = v1715.diagnose_spatial_balance_sheet_v17_15(doc, version["economic_date"])

    if baseline.get("recovered"):
        raise ValueError(f"V17.11 baseline unexpectedly recovered {aid}")
    selected = candidate.get("selected") or {}
    bridge_selected = sorted(
        concept for concept, row in selected.items() if row.get("adjacent_row_bridge")
    )
    report = {
        "gate": "S3G1J_V17_15_EXACT_FOUR_ADJACENT_BRIDGE_EXPERIMENT",
        "experimental_only": True,
        "production_parser_changed": False,
        "accounting_tolerance_changed": False,
        "global_row_tolerance_changed": False,
        "source_policy_changed": False,
        "announcement_id": aid,
        "source_code": version["source_code"],
        "report_family": version["report_family"],
        "economic_date": version["economic_date"],
        "canonical_title": version["canonical_title"],
        "canonical_source_url": version["canonical_source_url"],
        "source_sha256": digest,
        "baseline_recovered": False,
        "candidate_recovered": bool(candidate.get("recovered")),
        "candidate_identity": candidate.get("identity"),
        "candidate_column_role_gate": candidate.get("column_role_gate"),
        "base_candidate_counts": candidate.get("base_candidate_counts"),
        "bridge_candidate_counts": candidate.get("bridge_candidate_counts"),
        "candidate_counts": candidate.get("candidate_counts"),
        "bridge_funnel": candidate.get("bridge_funnel"),
        "bridge_selected_concepts": bridge_selected,
        "candidate_selected": selected,
        "stage4_alpha_locked": True,
        "pass": True,
        "errors": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "announcement_id": aid,
        "source_code": version["source_code"],
        "candidate_recovered": report["candidate_recovered"],
        "bridge_candidate_counts": report["bridge_candidate_counts"],
        "bridge_selected_concepts": bridge_selected,
        "candidate_identity": report["candidate_identity"],
        "column_gate_pass": bool((report["candidate_column_role_gate"] or {}).get("pass")),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
