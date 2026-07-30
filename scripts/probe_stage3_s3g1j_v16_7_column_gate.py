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

from stage3_financial_spatial_alias_v16_7 import diagnose_spatial_balance_sheet_v16_7

REPRESENTATIVE_IDS = {
    "1200948256", "1203240204", "1202637566", "1204557640", "1205969212", "1207547788",
    "1209728461", "1212671853", "1219442543", "1221090309", "1222949445", "1223096939",
}
EXPECTED_RECOVERED_IDS = {
    "1200948256", "1203240204", "1204557640", "1207547788", "1209728461",
    "1212671853", "1219442543", "1221090309", "1222949445", "1223096939",
}
EXPECTED_000736_CURRENT = {
    "TOTAL_ASSETS": "107697681763.55",
    "TOTAL_LIABILITIES": "96659072585.14",
    "TOTAL_EQUITY": "11038609178.41",
}


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def download(session: requests.Session, url: str) -> tuple[bytes, str]:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V16.7-column-gate",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    return raw, hashlib.sha256(raw).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    versions = read_versions(Path(args.versions))
    missing = sorted(REPRESENTATIVE_IDS - set(versions))
    if missing:
        raise ValueError(f"missing representative ids: {missing}")

    session = requests.Session()
    rows = []
    errors = []
    for announcement_id in sorted(REPRESENTATIVE_IDS):
        v = versions[announcement_id]
        row = {
            "announcement_id": announcement_id,
            "source_code": v["source_code"],
            "economic_date": v["economic_date"],
            "canonical_title": v["canonical_title"],
        }
        try:
            raw, digest = download(session, v["canonical_source_url"])
            doc = fitz.open(stream=raw, filetype="pdf")
            parsed = diagnose_spatial_balance_sheet_v16_7(doc, v["economic_date"])
            row.update({"download_sha256": digest, "v16_7": parsed})
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{announcement_id}: {row['error']}")
        rows.append(row)

    recovered = [r for r in rows if (r.get("v16_7") or {}).get("recovered")]
    recovered_ids = {r["announcement_id"] for r in recovered}
    shape_ok = recovered_ids == EXPECTED_RECOVERED_IDS
    column_pass_count = sum(
        sum(bool(ev.get("pass")) for ev in (((r.get("v16_7") or {}).get("column_role_gate") or {}).get("concepts") or {}).values())
        for r in recovered
    )

    guard = next(r for r in rows if r["announcement_id"] == "1223096939")
    selected = (guard.get("v16_7") or {}).get("selected") or {}
    guard_values = {concept: str((selected.get(concept) or {}).get("value") or "") for concept in EXPECTED_000736_CURRENT}
    guard_ok = guard_values == EXPECTED_000736_CURRENT

    diagnostic_pass = not errors and shape_ok and column_pass_count == 30 and guard_ok
    report = {
        "gate": "S3G1J_V16_7_FROZEN_DATE_COLUMN_ROLE_GATE",
        "diagnostic_pass": diagnostic_pass,
        "sample_reports": len(rows),
        "expected_recovered_count": 10,
        "recovered_count": len(recovered),
        "expected_recovered_ids": sorted(EXPECTED_RECOVERED_IDS),
        "recovered_ids": sorted(recovered_ids),
        "recovered_shape_ok": shape_ok,
        "column_role_pass_concepts": column_pass_count,
        "expected_column_role_pass_concepts": 30,
        "guard_000736": {
            "expected_values": EXPECTED_000736_CURRENT,
            "actual_values": guard_values,
            "exact_values": guard_ok,
        },
        "policy": {
            "diagnostic_only": True,
            "v16_6_period_gate_retained": True,
            "frozen_economic_date_ordinal_must_match_selected_amount_column": True,
            "group_parent_and_statement_role_gates_retained": True,
            "accounting_identity_retained": True,
            "no_ocr": True,
        },
        "rows": rows,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if diagnostic_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
