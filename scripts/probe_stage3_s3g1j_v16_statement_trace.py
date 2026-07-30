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

import stage3_financial_pdf_parser as base
import stage3_financial_coordinate_fallback_v14 as v14
from probe_stage3_s3g1j_v16_spatial_alias import REPRESENTATIVE_IDS

TITLE_HINTS = (
    "资产负债表",
    "财务状况表",
    "balance sheet",
    "statement of financial position",
    "statement of financial condition",
)
TERMINAL_HINTS = (
    "资产总计", "资产合计", "总资产",
    "负债合计", "总负债",
    "所有者权益合计", "股东权益合计", "权益合计",
    "负债和所有者权益", "负债及所有者权益", "负债和股东权益", "负债及股东权益",
    "total assets", "total liabilities", "total equity",
)
UNIT_HINT_RE = re.compile(r"(?:单位|金额单位|货币单位|人民币|RMB|CNY).*(?:百万元|亿元|万元|千元|元)", re.I)


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def _download(session: requests.Session, url: str) -> tuple[bytes, str]:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V16.2-statement-trace",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    return raw, hashlib.sha256(raw).hexdigest()


def _lines_with_hints(text: str, hints: tuple[str, ...]) -> list[str]:
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        n = _norm(stripped)
        if any(_norm(h) in n for h in hints):
            out.append(stripped[:500])
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    versions = _read_versions(Path(args.versions))
    missing = sorted(REPRESENTATIVE_IDS - set(versions))
    if missing:
        raise ValueError(f"representative ids missing: {missing}")

    session = requests.Session()
    rows = []
    errors = []
    for announcement_id in sorted(REPRESENTATIVE_IDS):
        version = versions[announcement_id]
        record = {
            "announcement_id": announcement_id,
            "source_code": version["source_code"],
            "report_family": version["report_family"],
            "economic_date": version["economic_date"],
            "canonical_title": version["canonical_title"],
            "canonical_source_url": version["canonical_source_url"],
        }
        try:
            raw, digest = _download(session, version["canonical_source_url"])
            doc = fitz.open(stream=raw, filetype="pdf")
            recognized_events = v14._statement_events(doc)
            pages = []
            for pno in range(doc.page_count):
                text = doc[pno].get_text("text") or ""
                title_lines = _lines_with_hints(text, TITLE_HINTS)
                terminal_lines = _lines_with_hints(text, TERMINAL_HINTS)
                detected_unit, detected_mult = base.detect_unit(text)
                unit_like_lines = [
                    line.strip()[:500]
                    for line in text.splitlines()
                    if line.strip() and UNIT_HINT_RE.search(line.strip())
                ]
                if title_lines or terminal_lines or detected_unit or unit_like_lines:
                    pages.append({
                        "page": pno + 1,
                        "title_lines": title_lines[:20],
                        "terminal_lines": terminal_lines[:30],
                        "detected_unit": detected_unit,
                        "detected_unit_multiplier": str(detected_mult) if detected_mult is not None else None,
                        "unit_like_lines": unit_like_lines[:20],
                    })
            record.update({
                "sha256": digest,
                "page_count": doc.page_count,
                "recognized_role_events": recognized_events,
                "recognized_role_event_count": len(recognized_events),
                "evidence_pages": pages,
                "title_hint_pages": [p["page"] for p in pages if p["title_lines"]],
                "terminal_hint_pages": [p["page"] for p in pages if p["terminal_lines"]],
                "detected_unit_pages": [p["page"] for p in pages if p["detected_unit"]],
                "unit_like_but_regex_missed_pages": [
                    p["page"] for p in pages if p["unit_like_lines"] and not p["detected_unit"]
                ],
            })
        except Exception as exc:
            record["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{announcement_id}: {type(exc).__name__}: {exc}")
        rows.append(record)

    report = {
        "gate": "S3G1J_V16_2_STATEMENT_TITLE_UNIT_TRACE",
        "diagnostic_pass": not errors,
        "sample_count": len(rows),
        "policy": {
            "diagnostic_only": True,
            "no_parser_change": True,
            "no_ocr": True,
            "records_unrecognized_title_variants_and_unit_regex_misses": True,
        },
        "rows": rows,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
