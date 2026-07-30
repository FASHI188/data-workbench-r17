#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from pathlib import Path

import fitz
import requests

import stage3_financial_spatial_alias_v16_3 as v166
import stage3_financial_spatial_alias_v16_7 as v167
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard

TARGET_CATEGORY = "COLUMN_ROLE_GATE"
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
UNIT_SUFFIX_RE = re.compile(r"(?:人民币)?(?:百万元|亿元|万元|千元|元)$")


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.10-column-evidence-ab",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def expected_cn(expected: str) -> str:
    y, m, d = v166._canonical_economic_date(expected).split("-")
    return f"{int(y)}年{int(m)}月{int(d)}日"


def strict_statement_header_row(row: dict, expected: str, alias_x1: float):
    """Diagnostic-only extension for two exact observed statement-header forms.

    Keep the existing right-of-alias rule. Only expand the structural syntax from
    a pure date to either `于<date>` or `<date><explicit currency unit>`. No
    narrative prefixes/suffixes are accepted.
    """
    compact = re.sub(r"\s+", "", row.get("text") or "").strip("：:、，,。.;；()（）")
    exp_cn = expected_cn(expected)
    structural = compact == f"于{exp_cn}" or bool(
        compact.startswith(exp_cn) and UNIT_SUFFIX_RE.fullmatch(compact[len(exp_cn):] or "")
    )
    if not structural:
        return None
    if any(token in compact for token in v167.HEADER_BLOCKERS):
        return None
    dates = [d for d in v167._date_geometries(row) if float(d["x_center"]) >= float(alias_x1) - 5.0]
    expected_date = v166._canonical_economic_date(expected)
    if not dates or not any(d["date"] == expected_date for d in dates):
        return None
    dates.sort(key=lambda item: item["x_center"])
    index = next(i for i, item in enumerate(dates) if item["date"] == expected_date)
    return {
        "page": None,
        "row_y": float(row["y"]),
        "row_text": row["text"][:500],
        "dates": dates,
        "expected_date": expected_date,
        "expected_column_index": index,
        "source": "V17_10_STRICT_STATEMENT_HEADER_SYNTAX_AB",
    }


def strict_header_evidence(doc: fitz.Document, candidate: dict, expected: str):
    current_page = int(candidate["page"])
    root_page = int((candidate.get("unit_evidence") or {}).get("root_page") or candidate["statement_anchor_page"])
    alias_x1 = float(candidate["alias_x1"])
    for page_1b in range(current_page, max(1, root_page) - 1, -1):
        for row in v167.v14._rows_from_words(doc[page_1b - 1]):
            evidence = strict_statement_header_row(row, expected, alias_x1)
            if evidence is not None:
                evidence = dict(evidence)
                evidence["page"] = page_1b
                return evidence
    return None


def amount_mapping(doc: fitz.Document, candidate: dict, header: dict) -> dict:
    found = v167._find_candidate_row(doc, candidate)
    if found is None:
        return {"pass": False, "reason": "candidate alias row not reconstructed"}
    amounts = found.get("amounts") or v167._amounts_after_alias(found["row"], float(found["geom"]["x1"]))
    idx = int(header["expected_column_index"])
    if idx >= len(amounts):
        return {
            "pass": False,
            "reason": "expected date column index exceeds amount columns",
            "amounts": [{"raw": str(a["raw"]), "value": str(a["value"]), "x0": float(a["x0"])} for a in amounts],
        }
    expected_amount = amounts[idx]
    selected_raw = v167._selected_raw_decimal(candidate)
    passed = selected_raw is not None and expected_amount["value"] == selected_raw
    return {
        "pass": passed,
        "reason": None if passed else "selected value does not match trusted header ordinal",
        "expected_amount": {"raw": str(expected_amount["raw"]), "value": str(expected_amount["value"]), "x0": float(expected_amount["x0"])},
        "selected_raw_value": str(candidate.get("raw_value")),
        "selected_value_x": float(candidate["value_x"]),
        "amounts": [{"raw": str(a["raw"]), "value": str(a["value"]), "x0": float(a["x0"])} for a in amounts],
    }


def candidate_current_or_strict(doc: fitz.Document, concept: str, candidate: dict, expected: str) -> dict:
    current = v167.column_role_evidence(doc, candidate, expected)
    if current.get("pass"):
        return {"pass": True, "source": "CURRENT_V16_7", "header": current.get("header"), "mapping": current}
    strict = strict_header_evidence(doc, candidate, expected)
    if strict is not None:
        mapping = amount_mapping(doc, candidate, strict)
        if mapping.get("pass"):
            return {"pass": True, "source": "STRICT_HEADER_SYNTAX_AB", "header": strict, "mapping": mapping}
    return {"pass": False, "source": None, "current": current, "strict_header": strict}


def shared_page_header(
    doc: fitz.Document,
    concept: str,
    candidate: dict,
    direct: dict[str, dict],
    selected: dict[str, dict],
) -> dict | None:
    page = int(candidate["page"])
    role = candidate.get("statement_role")
    for sibling in CONCEPTS:
        if sibling == concept or not direct[sibling].get("pass"):
            continue
        other = selected[sibling]
        header = direct[sibling].get("header") or {}
        if int(header.get("page") or -1) != page:
            continue
        if int(other.get("page") or -1) != page:
            continue
        if other.get("statement_role") != role:
            continue
        mapping = amount_mapping(doc, candidate, header)
        if not mapping.get("pass"):
            continue
        return {
            "pass": True,
            "source": "SAME_PAGE_TRUSTED_SIBLING_HEADER_AB",
            "sibling_concept": sibling,
            "sibling_header_source": direct[sibling].get("source"),
            "header": header,
            "mapping": mapping,
        }
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--v17-8-summary", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    summary = json.loads(Path(args.v17_8_summary).read_text(encoding="utf-8"))
    if not summary.get("pass") or summary.get("input_residual_count") != 88:
        raise ValueError("V17.8 summary is not accepted exact-88")
    targets = {
        str(item["announcement_id"]): item
        for item in summary.get("diagnostics") or []
        if item.get("category") == TARGET_CATEGORY
    }
    if len(targets) != 6:
        raise ValueError(f"expected exact six COLUMN_ROLE_GATE targets, got {len(targets)}")

    versions = read_versions(Path(args.versions))
    session = requests.Session()
    rows = []
    errors = []
    recovered_ids = []

    for idx, aid in enumerate(sorted(targets), 1):
        version = versions[aid]
        record = {
            "announcement_id": aid,
            "source_code": version["source_code"],
            "report_family": version["report_family"],
            "economic_date": version["economic_date"],
            "canonical_title": version["canonical_title"],
        }
        try:
            raw = download(session, version["canonical_source_url"])
            record["sha256"] = hashlib.sha256(raw).hexdigest()
            with fitz.open(stream=raw, filetype="pdf") as doc:
                with _mupdf_diagnostic_guard():
                    parsed = v166.diagnose_spatial_balance_sheet_v16_6(doc, version["economic_date"])
                    if not parsed.get("recovered"):
                        raise AssertionError("COLUMN_ROLE_GATE target no longer reaches V16.6 recovery")
                    selected = parsed.get("selected") or {}
                    if set(selected) != set(CONCEPTS):
                        raise AssertionError(f"selected concepts mismatch: {sorted(selected)}")
                    direct = {
                        concept: candidate_current_or_strict(doc, concept, selected[concept], version["economic_date"])
                        for concept in CONCEPTS
                    }
                    final = {}
                    for concept in CONCEPTS:
                        if direct[concept].get("pass"):
                            final[concept] = direct[concept]
                            continue
                        shared = shared_page_header(doc, concept, selected[concept], direct, selected)
                        final[concept] = shared or direct[concept]
                    recovered = all(bool(final[c].get("pass")) for c in CONCEPTS)
                    if recovered:
                        recovered_ids.append(aid)
                    record.update({
                        "v16_6_identity": parsed.get("identity"),
                        "direct_current_or_strict": direct,
                        "final_ab_evidence": final,
                        "ab_recovered": recovered,
                    })
        except Exception as exc:
            record["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        rows.append(record)
        print(f"V17_10_COLUMN_EVIDENCE_AB {idx}/6 aid={aid}", flush=True)

    report = {
        "gate": "S3G1J_V17_10_EXACT6_COLUMN_EVIDENCE_AB",
        "diagnostic_pass": not errors and len(rows) == 6,
        "sample_count": len(rows),
        "recovered_count": len(recovered_ids),
        "recovered_ids": recovered_ids,
        "rows": rows,
        "policy": {
            "diagnostic_only": True,
            "parser_policy_changed": False,
            "strict_header_syntax_ab": ["于<expected-date>", "<expected-date><explicit-currency-unit>"],
            "same_page_sibling_header_ab": True,
            "column_gate_changed_in_production": False,
            "accounting_tolerance_changed": False,
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
