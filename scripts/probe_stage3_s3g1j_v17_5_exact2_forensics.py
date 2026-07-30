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

import stage3_financial_pdf_parser as parser_base
import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16 as spatial
import stage3_financial_statement_blocks_v16_5 as blocks
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard

TARGETS = {
    "1201745924": {"source_code": "601818", "pages": [10, 11, 12, 13, 14]},
    "1205526156": {"source_code": "601939", "pages": [9, 10, 11, 12, 13]},
}
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
UNIT_HINT_RE = re.compile(r"(?:单位|人民币|百万元|千元|万元|亿元|\bRMB\b|million|thousand)", re.I)
LIABILITY_HINT_RE = re.compile(r"(?:负债|合计|总计|权益|资产)")


def _read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def _download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.5-exact2-forensics",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def _alias_matches(row: dict) -> dict:
    concepts = {
        "TOTAL_ASSETS": parser_base.TIER1_ALIASES.get("TOTAL_ASSETS") or [],
        "TOTAL_LIABILITIES": parser_base.TIER2_ALIASES.get("TOTAL_LIABILITIES") or [],
        "TOTAL_EQUITY": parser_base.TIER2_ALIASES.get("TOTAL_EQUITY") or [],
    }
    out = {}
    for concept, aliases in concepts.items():
        hits = []
        for alias in aliases:
            geoms = spatial._alias_geometries(row, alias, concept)
            if geoms:
                hits.append({
                    "alias": alias,
                    "geometries": [
                        {k: float(g[k]) for k in ("x0", "x1")}
                        for g in geoms
                    ],
                })
        out[concept] = hits
    return out


def _row_record(row: dict) -> dict:
    return {
        "y": float(row["y"]),
        "text": row["text"][:1600],
        "words": [
            {
                "text": str(w["text"]),
                "x0": float(w["x0"]),
                "x1": float(w["x1"]),
                "y0": float(w["y0"]),
                "y1": float(w["y1"]),
            }
            for w in row["words"]
        ],
        "numeric_candidates": [
            {"raw": str(n.get("raw")), "value": str(n.get("value")), "x0": float(n.get("x0"))}
            for n in v14._numeric_word_candidates(row)
        ],
        "alias_matches": _alias_matches(row),
        "detect_unit": tuple(str(x) if x is not None else None for x in parser_base.detect_unit(row["text"])),
        "standalone_unit": tuple(str(x) if x is not None else None for x in blocks.detect_standalone_statement_unit(row["text"])),
    }


def _page_record(page: fitz.Page, page_1b: int) -> dict:
    text = page.get_text("text") or ""
    text_lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows = v14._rows_from_words(page)
    unit_rows = []
    liability_rows = []
    header_rows = []
    for row in rows:
        if UNIT_HINT_RE.search(row["text"]):
            unit_rows.append(_row_record(row))
        if LIABILITY_HINT_RE.search(row["text"]):
            liability_rows.append(_row_record(row))
        if float(row["y"]) <= 230:
            header_rows.append(_row_record(row))
    try:
        page_units = blocks._page_units_with_y_v16_5(page)
    except Exception as exc:
        page_units = [{"error": f"{type(exc).__name__}: {exc}"}]
    split = v14._page_role_split(page)
    return {
        "page": page_1b,
        "page_text_unit_lines": [line for line in text_lines if UNIT_HINT_RE.search(line)][:100],
        "page_text_liability_lines": [line for line in text_lines if LIABILITY_HINT_RE.search(line)][:200],
        "unit_rows": unit_rows[:100],
        "liability_rows": liability_rows[:200],
        "header_rows": header_rows[:100],
        "page_units_v16_5": [
            {
                k: (str(v) if k == "multiplier" else v)
                for k, v in item.items()
            }
            for item in page_units
        ],
        "v14_page_role_split": None if split is None else {k: str(v) for k, v in split.items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--v17-4", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ab = json.loads(Path(args.v17_4).read_text(encoding="utf-8"))
    if not ab.get("diagnostic_pass") or int(ab.get("promoted_document_count", -1)) != 2 or int(ab.get("recovered_count", -1)) != 0:
        raise ValueError("V17.4 evidence is not the accepted exact-2 zero-recovery state")
    promoted_ids = sorted(
        str(row["announcement_id"])
        for row in ab.get("rows") or []
        if int(row.get("promotion_count", 0) or 0) > 0
    )
    if promoted_ids != sorted(TARGETS):
        raise ValueError(f"unexpected promoted ids: {promoted_ids}")

    versions = _read_versions(Path(args.versions))
    session = requests.Session()
    rows = []
    errors = []

    for aid in sorted(TARGETS):
        version = versions[aid]
        expected = TARGETS[aid]
        record = {
            "announcement_id": aid,
            "source_code": version["source_code"],
            "economic_date": version["economic_date"],
            "report_family": version["report_family"],
            "canonical_title": version["canonical_title"],
        }
        if version["source_code"] != expected["source_code"]:
            errors.append(f"source-code mismatch {aid}")
            rows.append(record)
            continue
        try:
            raw = _download(session, version["canonical_source_url"])
            record["sha256"] = hashlib.sha256(raw).hexdigest()
            with fitz.open(stream=raw, filetype="pdf") as doc:
                with _mupdf_diagnostic_guard():
                    record["page_count"] = doc.page_count
                    record["pages"] = [
                        _page_record(doc[p - 1], p)
                        for p in expected["pages"]
                        if 1 <= p <= doc.page_count
                    ]
        except Exception as exc:
            record["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        rows.append(record)

    report = {
        "gate": "S3G1J_V17_5_EXACT2_LIABILITY_UNIT_FORENSICS",
        "diagnostic_pass": not errors and len(rows) == 2,
        "sample_count": len(rows),
        "rows": rows,
        "policy": {
            "diagnostic_only": True,
            "parser_policy_changed": False,
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
        "sample_count": len(rows),
        "errors": errors,
        "diagnostic_pass": report["diagnostic_pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["diagnostic_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
