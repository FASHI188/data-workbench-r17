#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import fitz
import requests

import diagnose_stage3_s3g1j_v17_11_remaining as legacy
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard
from stage3_financial_spatial_alias_v17_21 import diagnose_spatial_balance_sheet_v17_21

EXPECTED_TOTAL = 80
EXPECTED_RECOVERY = {"1219311356"}
EXPECTED_SHARDS = (0, 1, 7, 9)
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")


def _load_exact80(root: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for path in sorted(glob.glob(str(root / "shard*.json"))):
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        if not report.get("pass"):
            raise ValueError(f"V17.18 shard not pass: {path}")
        for row in report.get("diagnostics") or []:
            aid = str(row["announcement_id"])
            if aid in rows:
                raise ValueError(f"duplicate V17.18 residual {aid}")
            rows[aid] = row
    if len(rows) != EXPECTED_TOTAL:
        raise ValueError(f"expected exact 80 V17.18 residuals, got {len(rows)}")
    return rows


def _validate_recovery(aid: str, diagnostic: dict) -> None:
    selected = diagnostic.get("selected") or {}
    if set(selected) != set(CONCEPTS):
        raise ValueError(f"{aid} incomplete selected concepts")
    assets = selected["TOTAL_ASSETS"]
    if assets.get("alias") != "资产总计":
        raise ValueError(f"{aid} unexpected asset alias {assets.get('alias')}")
    if assets.get("reverse_adjacent_asset_total") is not True:
        raise ValueError(f"{aid} recovery did not use reverse asset-total candidate")
    delta = Decimal(str(assets.get("reverse_bridge_y_delta")))
    if not (Decimal("5.50") <= delta <= Decimal("6.25")):
        raise ValueError(f"{aid} reverse delta outside frozen window {delta}")
    amounts = assets.get("bridge_amount_columns") or []
    if len(amounts) != 2:
        raise ValueError(f"{aid} reverse bridge did not have exactly two amount columns")
    identity = diagnostic.get("identity") or {}
    relative = Decimal(str(identity.get("identity_relative_error")))
    if relative > Decimal("0.005"):
        raise ValueError(f"{aid} identity outside tolerance {relative}")
    gate = diagnostic.get("column_role_gate") or {}
    if not gate.get("pass"):
        raise ValueError(f"{aid} column gate failed")
    evidence = gate.get("concepts") or {}
    if not all(bool((evidence.get(concept) or {}).get("pass")) for concept in CONCEPTS):
        raise ValueError(f"{aid} incomplete frozen-date column evidence")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", required=True)
    parser.add_argument("--v17-18-candidate-root", required=True)
    parser.add_argument("--shard", required=True, type=int)
    parser.add_argument("--shards", default=64, type=int)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.shards != 64 or args.shard not in EXPECTED_SHARDS:
        raise ValueError("V17.21 replay is frozen to shards 0,1,7,9 of the 64-shard partition")

    residuals = _load_exact80(Path(args.v17_18_candidate_root))
    versions = [
        row
        for row in legacy._read_rows(Path(args.versions))
        if row["canonical_announcement_id"] in residuals
        and legacy.base.stable_shard(row["canonical_announcement_id"], args.shards) == args.shard
    ]
    versions.sort(key=lambda row: row["canonical_announcement_id"])

    session = requests.Session()
    results: list[dict] = []
    failures: list[dict] = []
    for index, row in enumerate(versions, 1):
        aid = row["canonical_announcement_id"]
        try:
            raw = legacy._download(session, row["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            if digest != residuals[aid]["source_sha256"]:
                raise ValueError(
                    f"source SHA changed expected={residuals[aid]['source_sha256']} actual={digest}"
                )
            with fitz.open(stream=raw, filetype="pdf") as doc:
                with _mupdf_diagnostic_guard():
                    diagnostic = diagnose_spatial_balance_sheet_v17_21(doc, row["economic_date"])
            recovered = bool(diagnostic.get("recovered"))
            expected = aid in EXPECTED_RECOVERY
            if expected:
                if not recovered:
                    raise ValueError("intended V17.21 candidate recovery did not recover")
                _validate_recovery(aid, diagnostic)
            elif recovered:
                raise ValueError("unexpected V17.21 recovery outside accepted exact-one set")
            results.append(
                {
                    "announcement_id": aid,
                    "source_code": row["source_code"],
                    "report_family": row["report_family"],
                    "economic_date": row["economic_date"],
                    "canonical_title": row["canonical_title"],
                    "canonical_source_url": row["canonical_source_url"],
                    "source_sha256": digest,
                    "v17_18_funnel_category": residuals[aid]["funnel_category"],
                    "candidate_recovered": recovered,
                    "diagnostic": diagnostic,
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "announcement_id": aid,
                    "source_code": row.get("source_code"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(f"S3G1J_V17_21_EXACT80 shard={args.shard} {index}/{len(versions)} aid={aid}", flush=True)

    recovered_ids = sorted(
        row["announcement_id"] for row in results if row["candidate_recovered"]
    )
    report = {
        "gate": "S3G1J_V17_21_EXACT_80_CANDIDATE_SAFETY_SHARD",
        "candidate_only": True,
        "production_parser_changed": False,
        "expected_recovery_announcement_ids": sorted(EXPECTED_RECOVERY),
        "shard": args.shard,
        "shards": args.shards,
        "input_count": len(versions),
        "processed_count": len(results),
        "source_sha_match_count": len(results),
        "candidate_recovered_count": len(recovered_ids),
        "candidate_recovered_announcement_ids": recovered_ids,
        "results": results,
        "execution_failures": failures,
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "global_row_tolerance_changed": False,
        "reverse_asset_y_window": "5.50 <= delta <= 6.25",
        "reverse_asset_amount_column_count": 2,
        "e_equals_a_minus_l_inference": False,
        "source_policy_changed": False,
        "stage4_alpha_locked": True,
        "pass": not failures and len(results) == len(versions),
        "errors": failures,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "shard": args.shard,
                "input_count": len(versions),
                "processed_count": len(results),
                "candidate_recovered_announcement_ids": recovered_ids,
                "failures": failures,
                "pass": report["pass"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
