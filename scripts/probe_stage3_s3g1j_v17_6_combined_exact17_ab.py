#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from contextlib import ExitStack, contextmanager
from pathlib import Path

import fitz
import requests

import stage3_financial_pdf_parser as parser_base
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard
from stage3_financial_spatial_alias_v16_7 import diagnose_spatial_balance_sheet_v16_7
import probe_stage3_s3g1j_v17_4_generic_dual_role_ab as v174

TARGET_CATEGORY = "NO_FORMAL_GROUP_EVENT"
NEW_LIABILITY_ALIAS = "负债总计"
EXPLICIT_PRESENTATION_UNIT_RE = re.compile(
    r"(?:除特别注明外[,，、:]*)?(?:以|按)\s*(?:人民币)?\s*(百万元|亿元|万元|千元|元)\s*(?:列示|计量|表示)",
    re.I,
)


def _read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def _download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.6-combined-exact17-ab",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


@contextmanager
def _temporary_liability_alias():
    original = list(parser_base.TIER2_ALIASES.get("TOTAL_LIABILITIES") or [])
    updated = list(original)
    if NEW_LIABILITY_ALIAS not in updated:
        updated.append(NEW_LIABILITY_ALIAS)
    parser_base.TIER2_ALIASES["TOTAL_LIABILITIES"] = updated
    try:
        yield
    finally:
        parser_base.TIER2_ALIASES["TOTAL_LIABILITIES"] = original


@contextmanager
def _temporary_explicit_presentation_unit():
    original = parser_base.detect_unit

    def patched(text: str):
        unit, mult = original(text)
        if unit is not None and mult is not None:
            return unit, mult
        compact = re.sub(r"\s+", "", text or "")
        match = EXPLICIT_PRESENTATION_UNIT_RE.search(compact)
        if not match:
            return None, None
        unit = match.group(1)
        return unit, parser_base.UNIT_MULTIPLIERS[unit]

    parser_base.detect_unit = patched
    try:
        yield
    finally:
        parser_base.detect_unit = original


def _hard_evidence_ok(diag: dict) -> bool:
    if not diag.get("recovered"):
        return False
    selected = diag.get("selected") or {}
    if set(selected) != {"TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"}:
        return False
    if not all(bool((item.get("period_evidence") or {}).get("matched")) for item in selected.values()):
        return False
    column = diag.get("column_role_gate") or {}
    if not column.get("pass"):
        return False
    if not all(bool((ev or {}).get("pass")) for ev in (column.get("concepts") or {}).values()):
        return False
    identity = diag.get("identity") or {}
    return identity.get("identity_relative_error") is not None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--v17-summary", required=True)
    ap.add_argument("--v17-4", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    summary = json.loads(Path(args.v17_summary).read_text(encoding="utf-8"))
    if not summary.get("pass") or int(summary.get("input_residual_count", -1)) != 91:
        raise ValueError("V17 summary is not the accepted exact-91 funnel")
    target_ids = sorted(
        str(item["announcement_id"])
        for item in summary.get("diagnostics") or []
        if item.get("category") == TARGET_CATEGORY
    )
    if len(target_ids) != 17:
        raise ValueError(f"expected exact 17 targets, got {len(target_ids)}")

    prior = json.loads(Path(args.v17_4).read_text(encoding="utf-8"))
    if not prior.get("diagnostic_pass") or prior.get("promoted_document_count") != 2 or prior.get("recovered_count") != 0:
        raise ValueError("V17.4 is not the accepted exact-17 zero-recovery A/B")

    versions = _read_versions(Path(args.versions))
    session = requests.Session()
    rows = []
    errors = []
    recovered_ids = []

    for idx, aid in enumerate(target_ids, 1):
        version = versions[aid]
        record = {
            "announcement_id": aid,
            "source_code": version["source_code"],
            "report_family": version["report_family"],
            "economic_date": version["economic_date"],
            "canonical_title": version["canonical_title"],
        }
        try:
            raw = _download(session, version["canonical_source_url"])
            record["sha256"] = hashlib.sha256(raw).hexdigest()
            with fitz.open(stream=raw, filetype="pdf") as doc:
                with _mupdf_diagnostic_guard():
                    baseline = diagnose_spatial_balance_sheet_v16_7(doc, version["economic_date"])
                    if baseline.get("recovered"):
                        raise AssertionError("accepted V17 residual unexpectedly recovered on baseline")
                    with ExitStack() as stack:
                        stack.enter_context(_temporary_liability_alias())
                        stack.enter_context(_temporary_explicit_presentation_unit())
                        promotions_cm = v174._temporary_role_promotion(doc)
                        promotions = stack.enter_context(promotions_cm)
                        combined = diagnose_spatial_balance_sheet_v16_7(doc, version["economic_date"])
            hard_ok = _hard_evidence_ok(combined)
            if hard_ok:
                recovered_ids.append(aid)
            record.update({
                "promotion_count": len(promotions),
                "promotions": promotions,
                "combined_recovered": bool(combined.get("recovered")),
                "hard_evidence_ok": hard_ok,
                "candidate_counts": combined.get("candidate_counts") or {},
                "funnel": combined.get("funnel") or {},
                "identity": combined.get("identity"),
                "selected": v174._selected_summary(combined),
                "column_role_gate": combined.get("column_role_gate"),
            })
        except Exception as exc:
            record["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        rows.append(record)
        print(f"V17_6_COMBINED_EXACT17_AB {idx}/17 aid={aid}", flush=True)

    report = {
        "gate": "S3G1J_V17_6_COMBINED_EXACT17_AB_DIAGNOSTIC",
        "diagnostic_pass": not errors and len(rows) == 17,
        "sample_count": len(rows),
        "recovered_count": len(recovered_ids),
        "recovered_ids": recovered_ids,
        "rows": rows,
        "temporary_changes": {
            "role_promotion": "generic/unaudited balance-sheet heading + same-page explicit V14 dual group/parent header split -> DUAL_GROUP_PARENT",
            "liability_alias": NEW_LIABILITY_ALIAS,
            "explicit_unit_grammar": "以/按人民币<unit>列示|计量|表示",
        },
        "policy": {
            "diagnostic_only": True,
            "parser_policy_changed": False,
            "accounting_tolerance_changed": False,
            "period_gate_changed": False,
            "column_gate_changed": False,
            "source_policy_changed": False,
            "stage4_alpha_locked": True,
        },
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "recovered_count": len(recovered_ids),
        "recovered_ids": recovered_ids,
        "errors": errors,
        "diagnostic_pass": report["diagnostic_pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["diagnostic_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
