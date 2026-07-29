#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

import requests

import stage3_financial_pdf_parser_v10 as v16_runtime
from stage3_financial_pdf_parser_v9 import parse_pdf_bytes as _v14_parse
from stage3_financial_pdf_parser_v10 import parse_pdf_bytes as v16_parse

V14_REGRESSION_IDS = {
    "1202260810",  # 601166 2016Q1
    "1206660047",  # 601818 2019H1
    "1206728992",  # 601688 2019H1
    "1216700376",  # 600177 2022 annual
    "1217635500",  # 601998 2023H1
}
RESIDUAL_IDS = {
    "1200948256", "1203240204", "1202637566", "1204557640", "1205969212", "1207547788",
    "1209728461", "1212671853", "1219442543", "1221090309", "1222949445", "1223096939",
}
EXPECTED_RECOVERED = RESIDUAL_IDS - {"1202637566", "1205969212"}
EXPECTED_000736 = {
    "TOTAL_ASSETS": "107697681763.55",
    "TOTAL_LIABILITIES": "96659072585.14",
    "TOTAL_EQUITY": "11038609178.41",
}


def v14_parse(raw: bytes) -> dict:
    """Run the frozen V14 parser with only MuPDF diagnostics bounded."""
    with v16_runtime._mupdf_diagnostic_guard():
        return _v14_parse(raw)


def read_versions(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 S3G1J-V16-production-regression", "Referer": "https://www.cninfo.com.cn/"},
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError("source is not PDF")
    return raw


def balance_observations(parsed: dict) -> dict:
    observations = parsed.get("observations") or {}
    return {k: observations.get(k) for k in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--extract-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = read_versions(Path(args.versions))
    by_id = {r["canonical_announcement_id"]: r for r in rows}
    missing = sorted((V14_REGRESSION_IDS | RESIDUAL_IDS) - set(by_id))
    if missing:
        raise ValueError(f"required ids missing from frozen versions: {missing}")

    session = requests.Session()
    v14_regressions = []
    errors = []
    for announcement_id in sorted(V14_REGRESSION_IDS):
        row = by_id[announcement_id]
        raw = download(session, row["canonical_source_url"])
        old = v14_parse(raw)
        new = v16_parse(raw, row["economic_date"])
        old_block = old.get("balance_sheet_block") or {}
        new_block = new.get("balance_sheet_block") or {}
        same_observations = balance_observations(old) == balance_observations(new)
        same_block = old_block == new_block
        arbitration_unchanged = str(new_block.get("arbitration") or "").startswith("V14_")
        passed = same_observations and same_block and arbitration_unchanged and not new.get("validation_errors")
        if not passed:
            errors.append(f"V14 differential regression failed {announcement_id}")
        v14_regressions.append({
            "announcement_id": announcement_id,
            "source_code": row["source_code"],
            "economic_date": row["economic_date"],
            "sha256": hashlib.sha256(raw).hexdigest(),
            "same_balance_observations": same_observations,
            "same_balance_sheet_block": same_block,
            "new_arbitration": new_block.get("arbitration"),
            "passed": passed,
        })

    extract_dir = Path(args.extract_dir)
    docs_path = next(extract_dir.glob("financial_documents_shard*.csv.gz"))
    numeric_path = next(extract_dir.glob("financial_values_shard*.csv.gz"))
    with gzip.open(docs_path, "rt", encoding="utf-8", newline="") as handle:
        docs = list(csv.DictReader(handle))
    with gzip.open(numeric_path, "rt", encoding="utf-8", newline="") as handle:
        numeric = list(csv.DictReader(handle))

    docs_by_id = {r["announcement_id"]: r for r in docs}
    pass_ids = {aid for aid, r in docs_by_id.items() if r["document_status"] == "PASS"}
    error_ids = {aid for aid, r in docs_by_id.items() if r["document_status"] == "ERROR"}
    residual_shape_ok = pass_ids == EXPECTED_RECOVERED and error_ids == (RESIDUAL_IDS - EXPECTED_RECOVERED)
    if not residual_shape_ok:
        errors.append(f"residual shape mismatch pass={sorted(pass_ids)} error={sorted(error_ids)}")

    arbitration_ok = True
    for aid in EXPECTED_RECOVERED:
        evidence = json.loads(docs_by_id[aid]["candidate_evidence_json"])
        arbitrations = [str(x.get("balance_sheet_arbitration") or "") for x in evidence]
        if not any(x == "V16_7_GROUP_PERIOD_FROZEN_DATE_COLUMN_A_EQUALS_L_PLUS_E" for x in arbitrations):
            arbitration_ok = False
            errors.append(f"missing V16.7 arbitration {aid}: {arbitrations}")

    values_000736 = {
        r["concept"]: r["normalized_cny_value"]
        for r in numeric
        if r["announcement_id"] == "1223096939" and r["concept"] in EXPECTED_000736
    }
    guard_000736_ok = values_000736 == EXPECTED_000736
    if not guard_000736_ok:
        errors.append(f"000736 current-period values mismatch: {values_000736}")

    report = {
        "gate": "S3G1J_V16_7_PRODUCTION_FALLBACK_ACCEPTANCE",
        "pass": not errors,
        "v14_differential_regressions": v14_regressions,
        "v14_regressions_all_pass": all(r["passed"] for r in v14_regressions),
        "residual_sample_count": len(docs),
        "expected_recovered_ids": sorted(EXPECTED_RECOVERED),
        "actual_pass_ids": sorted(pass_ids),
        "actual_error_ids": sorted(error_ids),
        "residual_shape_ok": residual_shape_ok,
        "v16_arbitration_ok": arbitration_ok,
        "guard_000736_values": values_000736,
        "guard_000736_ok": guard_000736_ok,
        "stage4_alpha_locked": True,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
