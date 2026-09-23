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

import extract_stage3_financial_pdf_values as base
import stage3_financial_spatial_alias_v16_7 as v167
import stage3_financial_spatial_alias_v17_15 as v1715
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard

EXPECTED_TOTAL = 82
EXPECTED_SHARDS = (0, 1, 7, 9)
EXPECTED_RECOVERY = {"1225153907"}


def read_versions(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.15-exact-82-safety-replay",
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
    ap.add_argument("--acceptance", required=True)
    ap.add_argument("--shard", required=True, type=int)
    ap.add_argument("--shards", default=64, type=int)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.shards != 64 or args.shard not in EXPECTED_SHARDS:
        raise ValueError("replay frozen to shards 0,1,7,9 of the accepted 64-shard partition")

    accepted = json.loads(Path(args.acceptance).read_text(encoding="utf-8"))
    if not accepted.get("pass") or int(accepted.get("v17_11_remaining_count", -1)) != EXPECTED_TOTAL:
        raise ValueError("not the accepted V17.11 exact-82 state")
    expected_rows = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if len(expected_rows) != EXPECTED_TOTAL:
        raise ValueError(f"expected 82 accepted residual rows, got {len(expected_rows)}")

    rows = [
        row for row in read_versions(Path(args.versions))
        if row["canonical_announcement_id"] in expected_rows
        and base.stable_shard(row["canonical_announcement_id"], args.shards) == args.shard
    ]
    rows.sort(key=lambda row: row["canonical_announcement_id"])

    session = requests.Session()
    results: list[dict] = []
    failures: list[dict] = []
    for index, row in enumerate(rows, 1):
        aid = row["canonical_announcement_id"]
        try:
            raw = download(session, row["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            if digest != expected_rows[aid]["sha256"]:
                raise ValueError(
                    f"source SHA changed expected={expected_rows[aid]['sha256']} actual={digest}"
                )
            with _mupdf_diagnostic_guard():
                with fitz.open(stream=raw, filetype="pdf") as doc:
                    baseline = v167.diagnose_spatial_balance_sheet_v16_7(doc, row["economic_date"])
                    candidate = v1715.diagnose_spatial_balance_sheet_v17_15(doc, row["economic_date"])
            if baseline.get("recovered"):
                raise ValueError("accepted V17.11 residual unexpectedly recovered under baseline")
            recovered = bool(candidate.get("recovered"))
            selected = candidate.get("selected") or {}
            bridge_selected = sorted(
                concept for concept, value in selected.items()
                if value.get("adjacent_row_bridge")
            )
            if recovered:
                if not (candidate.get("column_role_gate") or {}).get("pass"):
                    raise ValueError("candidate recovered without passing column-role gate")
                if candidate.get("identity") is None:
                    raise ValueError("candidate recovered without A=L+E identity evidence")
                if not bridge_selected:
                    raise ValueError("candidate recovered without selecting an adjacent-row bridge")
            results.append({
                "announcement_id": aid,
                "source_code": row["source_code"],
                "report_family": row["report_family"],
                "economic_date": row["economic_date"],
                "canonical_title": row["canonical_title"],
                "canonical_source_url": row["canonical_source_url"],
                "source_sha256": digest,
                "baseline_recovered": False,
                "candidate_recovered": recovered,
                "candidate_identity": candidate.get("identity"),
                "candidate_column_role_gate": candidate.get("column_role_gate"),
                "base_candidate_counts": candidate.get("base_candidate_counts"),
                "bridge_candidate_counts": candidate.get("bridge_candidate_counts"),
                "candidate_counts": candidate.get("candidate_counts"),
                "bridge_funnel": candidate.get("bridge_funnel"),
                "bridge_selected_concepts": bridge_selected,
                "candidate_selected": selected,
            })
        except Exception as exc:
            failures.append({
                "announcement_id": aid,
                "source_code": row.get("source_code"),
                "error": f"{type(exc).__name__}: {exc}",
            })
        print(
            f"S3G1J_V17_15_EXACT82 shard={args.shard} {index}/{len(rows)} aid={aid}",
            flush=True,
        )

    recovered_ids = sorted(row["announcement_id"] for row in results if row["candidate_recovered"])
    report = {
        "gate": "S3G1J_V17_15_EXACT_82_SAFETY_REPLAY_SHARD",
        "experimental_only": True,
        "production_parser_changed": False,
        "accounting_tolerance": "0.005",
        "global_row_tolerance_changed": False,
        "bridge_y_window": "2.8 < delta <= 3.25",
        "source_policy_changed": False,
        "shard": args.shard,
        "shards": args.shards,
        "input_count": len(rows),
        "processed_count": len(results),
        "source_sha_match_count": len(results),
        "recovered_count": len(recovered_ids),
        "recovered_announcement_ids": recovered_ids,
        "results": results,
        "diagnostic_failures": failures,
        "pass": not failures and len(results) == len(rows),
        "stage4_alpha_locked": True,
        "errors": failures,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "shard": args.shard,
        "input_count": len(rows),
        "processed_count": len(results),
        "recovered_announcement_ids": recovered_ids,
        "failures": failures,
        "pass": report["pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
