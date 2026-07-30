#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import fitz
import requests

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16_3 as v166
import stage3_financial_statement_blocks_v16_5 as blocks
import stage3_financial_spatial_alias_v17_15 as v1715
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard

TARGET_IDS = {"1212731093", "1217717273", "1219411922"}
EQUITY_HINTS = (
    "所有者权益", "股东权益", "权益合计", "少数股东权益", "归属于母公司",
    "负债和所有者权益", "负债及所有者权益", "负债和股东权益", "负债及股东权益",
    "total equity", "shareholders' equity", "owners' equity", "equity attributable",
)
EXACT_TOTAL_HINTS = (
    "所有者权益合计", "股东权益合计", "权益合计",
    "负债和所有者权益总计", "负债及所有者权益总计",
    "负债和股东权益总计", "负债及股东权益总计",
    "total equity", "total shareholders' equity", "total owners' equity",
)


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.16-equity-terminal-diagnostic",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def numeric_records(row: dict) -> list[dict]:
    return [
        {"raw": str(x.get("raw")), "value": str(x.get("value")), "x0": str(x.get("x0"))}
        for x in sorted(v14._numeric_word_candidates(row), key=lambda x: x["x0"])
    ]


def nearest_event(events: list[dict], page_1b: int) -> dict | None:
    eligible = [event for event in events if int(event.get("page") or 0) <= page_1b]
    if not eligible:
        return None
    eligible.sort(key=lambda event: (int(event.get("page") or 0), float(event.get("y") or 0)))
    event = eligible[-1]
    if page_1b - int(event.get("page") or 0) > 4:
        return None
    return event


def classify(page_records: list[dict], equity_rows: list[dict]) -> str:
    exact_rows = [row for row in equity_rows if row.get("exact_total_hint")]
    group_exact = [
        row for row in exact_rows
        if (row.get("statement_role") or {}).get("role") in ("GROUP", "DUAL_GROUP_PARENT")
    ]
    explicit_amount = [
        row for row in group_exact
        if row.get("same_row_numeric_candidates") or row.get("next_row_numeric_candidates")
    ]
    if explicit_amount:
        return "EXPLICIT_GROUP_EQUITY_TERMINAL_WITH_AMOUNT_EVIDENCE"
    if group_exact:
        return "EXPLICIT_GROUP_EQUITY_TERMINAL_WITHOUT_AMOUNT_EVIDENCE"
    if exact_rows:
        return "EXPLICIT_EQUITY_TERMINAL_NOT_GROUP_BOUND"
    if any(row.get("low_text_with_image") for row in page_records) and not equity_rows:
        return "LIKELY_IMAGE_ONLY_OR_BROKEN_TEXT_LAYER"
    if any("归属于母公司" in str(row.get("row_text") or "") for row in equity_rows):
        return "ATTRIBUTABLE_EQUITY_ONLY_NO_TOTAL_EQUITY_TERMINAL"
    if equity_rows:
        return "EQUITY_TEXT_PRESENT_NO_EXACT_TOTAL_TERMINAL"
    return "NO_EQUITY_TEXT_IN_FORMAL_WINDOW"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--accepted-v17-11", required=True)
    ap.add_argument("--v17-15-summary", required=True)
    ap.add_argument("--announcement-id", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    aid = str(args.announcement_id)
    if aid not in TARGET_IDS:
        raise ValueError(f"diagnostic frozen to {sorted(TARGET_IDS)}")

    accepted = json.loads(Path(args.accepted_v17_11).read_text(encoding="utf-8"))
    accepted_rows = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if not accepted.get("pass") or aid not in accepted_rows:
        raise ValueError("not the accepted V17.11 residual source state")

    replay = json.loads(Path(args.v17_15_summary).read_text(encoding="utf-8"))
    remaining = {str(x) for x in replay.get("remaining_announcement_ids") or []}
    if not replay.get("pass") or int(replay.get("remaining_count", -1)) != 81 or not TARGET_IDS.issubset(remaining):
        raise ValueError("not the accepted V17.15 exact-81 state")

    versions = read_versions(Path(args.versions))
    version = versions[aid]
    raw = download(requests.Session(), version["canonical_source_url"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != accepted_rows[aid]["sha256"]:
        raise ValueError(f"source SHA changed for {aid}")

    errors: list[str] = []
    page_records: list[dict] = []
    equity_rows: list[dict] = []
    with _mupdf_diagnostic_guard():
        with fitz.open(stream=raw, filetype="pdf") as doc:
            events = blocks.formal_statement_events(doc)
            existing, _ = v166._collect_candidates_v16_6(doc, version["economic_date"])
            bridge, _ = v1715._collect_adjacent_bridge_candidates(doc, version["economic_date"])
            al_candidates = list(existing.get("TOTAL_ASSETS", [])) + list(existing.get("TOTAL_LIABILITIES", []))
            al_candidates += list(bridge.get("TOTAL_ASSETS", [])) + list(bridge.get("TOTAL_LIABILITIES", []))
            if not al_candidates:
                errors.append("no accepted asset/liability candidate window")
                start_page, end_page = 1, min(doc.page_count, 6)
            else:
                candidate_pages = [int(row["page"]) for row in al_candidates]
                anchor_pages = [int(row["statement_anchor_page"]) for row in al_candidates]
                start_page = max(1, min(candidate_pages + anchor_pages) - 1)
                end_page = min(doc.page_count, max(candidate_pages + anchor_pages) + 4)

            for page_1b in range(start_page, end_page + 1):
                page = doc[page_1b - 1]
                text = page.get_text("text") or ""
                words = page.get_text("words") or []
                images = page.get_images(full=True) or []
                rows = sorted(v14._rows_from_words(page), key=lambda row: float(row["y"]))
                event = nearest_event(events, page_1b)
                page_records.append({
                    "page": page_1b,
                    "text_chars": len(text.strip()),
                    "word_count": len(words),
                    "image_count": len(images),
                    "low_text_with_image": len(text.strip()) < 80 and bool(images),
                    "nearest_statement_role": event,
                })
                for index, row in enumerate(rows):
                    normalized = _norm(row.get("text") or "")
                    matched = [hint for hint in EQUITY_HINTS if _norm(hint) in normalized]
                    if not matched:
                        continue
                    nxt = rows[index + 1] if index + 1 < len(rows) else None
                    same_nums = numeric_records(row)
                    next_nums = numeric_records(nxt) if nxt is not None else []
                    delta = None if nxt is None else float(nxt["y"]) - float(row["y"])
                    exact = [hint for hint in EXACT_TOTAL_HINTS if _norm(hint) in normalized]
                    equity_rows.append({
                        "page": page_1b,
                        "row_index": index,
                        "row_y": float(row["y"]),
                        "row_text": str(row.get("text") or "")[:1600],
                        "matched_equity_hints": matched,
                        "exact_total_hint": exact,
                        "statement_role": event,
                        "same_row_numeric_candidates": same_nums,
                        "next_row_text": None if nxt is None else str(nxt.get("text") or "")[:1600],
                        "next_row_y_delta": delta,
                        "next_row_numeric_candidates": next_nums,
                    })

    category = classify(page_records, equity_rows)
    counters = Counter()
    for row in equity_rows:
        counters["equity_rows"] += 1
        if row.get("exact_total_hint"):
            counters["exact_total_rows"] += 1
        if (row.get("statement_role") or {}).get("role") in ("GROUP", "DUAL_GROUP_PARENT"):
            counters["group_bound_rows"] += 1
        if row.get("same_row_numeric_candidates"):
            counters["same_row_amount_rows"] += 1
        if row.get("next_row_numeric_candidates"):
            counters["next_row_amount_rows"] += 1

    report = {
        "gate": "S3G1J_V17_16_EXACT_THREE_EQUITY_TERMINAL_DIAGNOSTIC",
        "diagnostic_only": True,
        "no_parser_change": True,
        "no_value_acceptance": True,
        "no_e_equals_a_minus_l_inference": True,
        "accounting_tolerance_changed": False,
        "source_policy_changed": False,
        "announcement_id": aid,
        "source_code": version["source_code"],
        "report_family": version["report_family"],
        "economic_date": version["economic_date"],
        "canonical_title": version["canonical_title"],
        "canonical_source_url": version["canonical_source_url"],
        "source_sha256": digest,
        "formal_window": {"start_page": start_page, "end_page": end_page},
        "classification": category,
        "counts": dict(counters),
        "page_records": page_records,
        "equity_rows": equity_rows,
        "pass": not errors,
        "stage4_alpha_locked": True,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "announcement_id": aid,
        "classification": category,
        "formal_window": report["formal_window"],
        "counts": report["counts"],
        "pass": report["pass"],
        "errors": errors,
    }, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
