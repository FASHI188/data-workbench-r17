#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

CURRENT_P0_GZIP_SHA256 = "dc6cc9b10482406121e66772c38bf13e745e00ab0a80f4e324ccf9bb897bd922"
CURRENT_P0_PLAINTEXT_SHA256 = "94c768d34844a7c47bdfaf6bfd4067b6533c572b4e30c2b0e00b554a09bb9ea1"
BASE_DIAGNOSTIC_SHA256 = "665161dc49a77559af43e055b8cb5a4a6bced857af540a96ca8f5a8747203049"
DETAIL_SHA256 = "b3ab013938ad41c673e1125336b2abda1fde8edff68e21f8ef3ba8cbdee00b54"
RAW_SHA256 = "8a958ad58a89d6b911358aff472018dc39a62b2d3d3547ae7808db1b8fdbbfbe"
IDENTITY_TOLERANCE = Decimal("0.005")

EXPECTED_P0_IDS = (
    "1202799494", "1204077386", "1205543437", "1209806910",
    "1215186538", "1219426855", "1219792633", "1219834247",
    "1219840508", "1219879687", "1220087244", "1221006100",
    "1223347318", "1223407043",
)
EXPECTED_SAFE = (
    "1215186538", "1219426855", "1219792633", "1219840508",
    "1219879687", "1220087244", "1221006100",
)
EXPECTED_DIAGNOSTIC = (
    "1202799494", "1204077386", "1205543437", "1209806910",
    "1223347318", "1223407043",
)
EXPECTED_DO_NOT_PROMOTE = ("1219834247",)

LEDGER_FIELDS = [
    "announcement_id", "source_code", "report_family", "economic_date",
    "canonical_title", "canonical_source_url", "source_sha256", "source_bytes",
    "page_count", "source_identity_locked", "formal_group_title_count",
    "formal_parent_title_count", "group_asset_row", "group_liability_row",
    "group_equity_label_line", "group_equity_amount_line", "group_asset_current",
    "group_asset_prior", "group_liability_current", "group_liability_prior",
    "group_equity_current", "group_equity_prior", "current_identity_residual",
    "prior_identity_residual", "current_identity_pass", "prior_identity_pass",
    "classification", "root_cause", "evidence_basis", "candidate_authorized",
]

NUM_RE = re.compile(r"-?\d[\d,]*\.\d{2}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_gzip_plaintext(path: Path) -> str:
    h = hashlib.sha256()
    with gzip.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def numbers(text: str) -> list[Decimal]:
    return [Decimal(x.replace(",", "")) for x in NUM_RE.findall(text or "")]


def load_json(path: Path, expected_sha: str) -> dict[str, Any]:
    if sha256_file(path) != expected_sha:
        raise ValueError(f"input SHA mismatch: {path.name}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def read_current_p0(path: Path) -> dict[str, dict[str, str]]:
    if sha256_file(path) != CURRENT_P0_GZIP_SHA256:
        raise ValueError("current P0 gzip SHA mismatch")
    if sha256_gzip_plaintext(path) != CURRENT_P0_PLAINTEXT_SHA256:
        raise ValueError("current P0 plaintext SHA mismatch")
    out: dict[str, dict[str, str]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            aid = str(row["announcement_id"])
            if aid in out:
                raise ValueError(f"duplicate current P0 ID {aid}")
            out[aid] = row
    if tuple(sorted(out)) != EXPECTED_P0_IDS:
        raise ValueError(f"unexpected current P0 population {sorted(out)}")
    return out


def index_results(obj: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["announcement_id"]): row for row in obj["results"]}


def group_total_candidate(raw_row: dict[str, Any], concept: str) -> dict[str, Any] | None:
    candidates = raw_row.get("candidates", {}).get(concept, [])
    if concept == "TOTAL_ASSETS":
        candidates = [c for c in candidates if c.get("alias") == "资产总计"]
    else:
        candidates = [c for c in candidates if c.get("alias") == "负债合计"]
    candidates = [
        c for c in candidates
        if c.get("statement_role") == "GROUP"
        and c.get("period_evidence", {}).get("matched") is True
        and c.get("unit_evidence", {}).get("source") == "EXPLICIT_UNIT_LABEL"
        and len(numbers(str(c.get("row_text") or ""))) >= 2
    ]
    return candidates[-1] if candidates else None


def explicit_split_equity_proof(base_row: dict[str, Any]) -> dict[str, Any] | None:
    """Return explicit GROUP equity values only when the PDF extraction captured them.

    The accepted layout artifact records the end of a multi-page GROUP balance sheet in
    the context immediately preceding the formal PARENT title. A valid proof requires:
    - a formal GROUP title and a later formal PARENT title;
    - an explicit two-amount line immediately followed by the split label ending in 合计;
    - a nearby explicit 负债和所有者权益 total line and its two amounts;
    - no use of A-L to construct equity.
    """
    titles = base_row.get("layout", {}).get("title_rows", [])
    groups = [t for t in titles if t.get("statement_role_v14") == "GROUP"]
    parents = [t for t in titles if t.get("statement_role_v14") == "PARENT"]
    if not groups or not parents:
        return None
    parent = parents[0]
    context = sorted(parent.get("context", []), key=lambda x: int(x.get("relative_index", 0)))
    by_rel = {int(x["relative_index"]): x for x in context}
    for rel in sorted(k for k in by_rel if k < 0):
        vals = numbers(str(by_rel[rel].get("text") or ""))
        if len(vals) != 2:
            continue
        label = str(by_rel.get(rel + 1, {}).get("text") or "").replace(" ", "")
        next_label = str(by_rel.get(rel + 2, {}).get("text") or "").replace(" ", "")
        total_vals = numbers(str(by_rel.get(rel + 3, {}).get("text") or ""))
        if "合计" not in label and label != "计":
            continue
        if "负债和所有者权益" not in next_label:
            continue
        if len(total_vals) != 2:
            continue
        return {
            "values": vals,
            "amount_line": str(by_rel[rel].get("text") or ""),
            "label_line": str(by_rel[rel + 1].get("text") or ""),
            "total_label_line": str(by_rel[rel + 2].get("text") or ""),
            "total_amount_line": str(by_rel[rel + 3].get("text") or ""),
            "parent_title_page": int(parent.get("page") or 0),
            "group_title_page": int(groups[-1].get("page") or 0),
        }
    return None


def classify_target(
    aid: str,
    p0_row: dict[str, str],
    base_row: dict[str, Any],
    raw_row: dict[str, Any],
) -> dict[str, Any]:
    source_locked = (
        str(p0_row.get("canonical_source_url") or "") == str(base_row.get("canonical_source_url") or "")
        and bool(str(base_row.get("source_sha256") or ""))
        and int(base_row.get("source_bytes") or 0) > 0
    )
    if not source_locked:
        raise ValueError(f"source identity drift for {aid}")

    funnel = raw_row.get("candidate_diagnostic", {}).get("base_funnel", {})
    formal_group = int(funnel.get("formal_group_events") or 0)
    formal_parent = int(funnel.get("formal_parent_events") or 0)
    asset = group_total_candidate(raw_row, "TOTAL_ASSETS")
    liability = group_total_candidate(raw_row, "TOTAL_LIABILITIES")
    equity = explicit_split_equity_proof(base_row)

    a_vals = numbers(str(asset.get("row_text") if asset else ""))[-2:] if asset else []
    l_vals = numbers(str(liability.get("row_text") if liability else ""))[-2:] if liability else []
    e_vals = equity["values"] if equity else []
    residuals: list[Decimal] = []
    if len(a_vals) == len(l_vals) == len(e_vals) == 2:
        residuals = [a_vals[i] - l_vals[i] - e_vals[i] for i in range(2)]

    if aid == "1219834247":
        classification = "DO_NOT_PROMOTE"
        root_cause = "BANK_SPECIFIC_STATEMENT_WITHOUT_FORMAL_GROUP_ALE_ROLE_BINDING"
    elif (
        source_locked and formal_group > 0 and formal_parent > 0
        and asset is not None and liability is not None and equity is not None
        and len(residuals) == 2
        and all(abs(x) <= IDENTITY_TOLERANCE for x in residuals)
    ):
        classification = "SAFE_EXACT_SOURCE_CANDIDATE"
        root_cause = "SPLIT_GROUP_EQUITY_LABEL_AND_AMOUNT_LINES_NOT_JOINED_BY_V17_28"
    else:
        classification = "DIAGNOSTIC_ONLY"
        failure = str(raw_row.get("candidate_failure_stage") or "")
        if failure == "PERIOD_OR_ROLE_GATE_REMOVED_ALE_CANDIDATES":
            root_cause = "GENERIC_GROUP_WITNESS_PRESENT_BUT_ROLE_LOCAL_PERIOD_MISSING"
        elif formal_group == 0:
            root_cause = "NO_FORMAL_GROUP_STATEMENT_ROLE_BINDING"
        elif asset is not None and liability is not None and equity is None:
            root_cause = "FORMAL_GROUP_A_L_PRESENT_BUT_EXPLICIT_GROUP_EQUITY_PAIR_NOT_PROVEN"
        else:
            root_cause = "INSUFFICIENT_EXPLICIT_GROUP_ALE_EVIDENCE"

    def s(x: Any) -> str:
        return "" if x is None else str(x)

    return {
        "announcement_id": aid,
        "source_code": str(base_row.get("source_code") or ""),
        "report_family": str(base_row.get("report_family") or ""),
        "economic_date": str(base_row.get("economic_date") or ""),
        "canonical_title": str(base_row.get("canonical_title") or ""),
        "canonical_source_url": str(base_row.get("canonical_source_url") or ""),
        "source_sha256": str(base_row.get("source_sha256") or ""),
        "source_bytes": int(base_row.get("source_bytes") or 0),
        "page_count": int(base_row.get("layout", {}).get("page_count") or 0),
        "source_identity_locked": source_locked,
        "formal_group_title_count": formal_group,
        "formal_parent_title_count": formal_parent,
        "group_asset_row": s(asset.get("row_text") if asset else None),
        "group_liability_row": s(liability.get("row_text") if liability else None),
        "group_equity_label_line": s(equity.get("label_line") if equity else None),
        "group_equity_amount_line": s(equity.get("amount_line") if equity else None),
        "group_asset_current": s(a_vals[0] if len(a_vals) == 2 else None),
        "group_asset_prior": s(a_vals[1] if len(a_vals) == 2 else None),
        "group_liability_current": s(l_vals[0] if len(l_vals) == 2 else None),
        "group_liability_prior": s(l_vals[1] if len(l_vals) == 2 else None),
        "group_equity_current": s(e_vals[0] if len(e_vals) == 2 else None),
        "group_equity_prior": s(e_vals[1] if len(e_vals) == 2 else None),
        "current_identity_residual": s(residuals[0] if len(residuals) == 2 else None),
        "prior_identity_residual": s(residuals[1] if len(residuals) == 2 else None),
        "current_identity_pass": len(residuals) == 2 and abs(residuals[0]) <= IDENTITY_TOLERANCE,
        "prior_identity_pass": len(residuals) == 2 and abs(residuals[1]) <= IDENTITY_TOLERANCE,
        "classification": classification,
        "root_cause": root_cause,
        "evidence_basis": "FROZEN_EXACT_PDF_LAYOUT_ARTIFACTS_NO_OCR_NO_ARITHMETIC_EQUITY_INFERENCE",
        "candidate_authorized": classification == "SAFE_EXACT_SOURCE_CANDIDATE",
    }


def deterministic_csv_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=LEDGER_FIELDS, lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: row.get(k, "") for k in LEDGER_FIELDS})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current-p0", required=True)
    ap.add_argument("--base-diagnostic", required=True)
    ap.add_argument("--candidate-detail", required=True)
    ap.add_argument("--candidate-raw", required=True)
    ap.add_argument("--out-root", required=True)
    args = ap.parse_args()

    p0 = read_current_p0(Path(args.current_p0))
    base = load_json(Path(args.base_diagnostic), BASE_DIAGNOSTIC_SHA256)
    detail = load_json(Path(args.candidate_detail), DETAIL_SHA256)
    raw = load_json(Path(args.candidate_raw), RAW_SHA256)
    if raw.get("identity_tolerance") != "0.005":
        raise ValueError("identity tolerance drift")
    if detail.get("period_or_role_gate_removed_candidates_announcement_ids") != ["1204077386", "1205543437"]:
        raise ValueError("accepted period-or-role evidence drift")

    base_idx = index_results(base)
    raw_idx = index_results(raw)
    rows = [classify_target(aid, p0[aid], base_idx[aid], raw_idx[aid]) for aid in EXPECTED_P0_IDS]
    rows.sort(key=lambda x: x["announcement_id"])

    safe = tuple(r["announcement_id"] for r in rows if r["classification"] == "SAFE_EXACT_SOURCE_CANDIDATE")
    diagnostic = tuple(r["announcement_id"] for r in rows if r["classification"] == "DIAGNOSTIC_ONLY")
    blocked = tuple(r["announcement_id"] for r in rows if r["classification"] == "DO_NOT_PROMOTE")
    if safe != EXPECTED_SAFE or diagnostic != EXPECTED_DIAGNOSTIC or blocked != EXPECTED_DO_NOT_PROMOTE:
        raise ValueError(f"classification drift safe={safe} diagnostic={diagnostic} blocked={blocked}")

    out = Path(args.out_root)
    out.mkdir(parents=True, exist_ok=True)
    ledger = out / "stage3_s3g1j_v17_28_p0_pdf_root_cause.csv.gz"
    deterministic_csv_gz(ledger, rows)
    safe_manifest = out / "stage3_s3g1j_v17_28_safe_exact_source_targets.json"
    safe_manifest.write_text(json.dumps({
        "gate": "S3G1J_V17_28_P0_PDF_ROOT_CAUSE_SAFE_EXACT_SOURCE_TARGETS",
        "target_count": len(safe),
        "announcement_ids": list(safe),
        "source_sha256_by_announcement_id": {r["announcement_id"]: r["source_sha256"] for r in rows if r["announcement_id"] in safe},
        "candidate_parser_authorized": False,
        "next_gate": "SEPARATE_EXACT_SOURCE_DIAGNOSTIC_BEFORE_CANDIDATE_PARSER",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "gate": "S3G1J_V17_28_P0_PDF_ROOT_CAUSE_DIAGNOSTIC",
        "source_current_p0_artifact_id": 8937238672,
        "source_base_diagnostic_artifact_id": 8829316913,
        "source_candidate_detail_artifact_id": 8832931244,
        "target_count": len(rows),
        "classification_counts": {
            "SAFE_EXACT_SOURCE_CANDIDATE": len(safe),
            "DIAGNOSTIC_ONLY": len(diagnostic),
            "DO_NOT_PROMOTE": len(blocked),
        },
        "safe_exact_source_announcement_ids": list(safe),
        "diagnostic_only_announcement_ids": list(diagnostic),
        "do_not_promote_announcement_ids": list(blocked),
        "safe_current_identity_zero_residual_count": sum(r["current_identity_residual"] == "0.00" for r in rows if r["classification"] == "SAFE_EXACT_SOURCE_CANDIDATE"),
        "safe_prior_identity_zero_residual_count": sum(r["prior_identity_residual"] == "0.00" for r in rows if r["classification"] == "SAFE_EXACT_SOURCE_CANDIDATE"),
        "ledger_gzip_sha256": sha256_file(ledger),
        "ledger_plaintext_sha256": sha256_gzip_plaintext(ledger),
        "safe_manifest_sha256": sha256_file(safe_manifest),
        "gzip_mtime": 0,
        "gzip_embedded_filename": "",
        "pdf_binaries_redownloaded": False,
        "evidence_source": "ACCEPTED_FROZEN_EXACT_PDF_LAYOUT_ARTIFACTS",
        "ocr_used": False,
        "equity_inferred_from_assets_minus_liabilities": False,
        "parser_changed": False,
        "runtime_authority_changed": False,
        "production_data_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_live_locked": True,
        "candidate_parser_authorized": False,
        "pass": True,
        "errors": [],
    }
    summary_path = out / "stage3_s3g1j_v17_28_p0_pdf_root_cause_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
