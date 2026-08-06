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
    "所有者权益", "股东权益", "权益合计", "权益总计", "少数股东权益", "归属于母公司",
    "负债和所有者权益", "负债及所有者权益", "负债和股东权益", "负债及股东权益",
    "total equity", "shareholders' equity", "owners' equity", "equity attributable",
)
EQUITY_TOTAL_LABELS = (
    "所有者权益合计", "股东权益合计", "权益合计",
    "所有者权益总计", "股东权益总计", "权益总计",
    "total equity", "total shareholders' equity", "total owners' equity",
)
EQUITY_TOTAL_BLOCKERS = (
    "归属于", "少数股东", "负债和", "负债及",
    "attributable", "liabilitiesand", "liabilitiesandequity",
)
NEXT_STATEMENT_HINTS = (
    "合并利润表", "合并损益表", "合并综合收益表",
    "合并现金流量表", "合并股东权益变动表", "合并所有者权益变动表",
    "母公司资产负债表", "公司资产负债表",
    "consolidated income statement", "consolidated statement of profit",
    "consolidated statement of cash flows", "consolidated statement of changes in equity",
    "company balance sheet", "parent company balance sheet",
)
TAIL_ROW_LIMIT = 35


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
        {
            "raw": str(x.get("raw")),
            "value": str(x.get("value")),
            "x0": str(x.get("x0")),
            "x1": str(x.get("x1")),
        }
        for x in sorted(v14._numeric_word_candidates(row), key=lambda x: x["x0"])
    ]


def _first_lines(text: str, limit: int = 35) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return _norm("\n".join(lines[:limit]))


def _starts_next_statement(text: str) -> bool:
    head = _first_lines(text)
    return any(_norm(hint) in head for hint in NEXT_STATEMENT_HINTS)


def _is_exact_equity_total(row_text: str) -> list[str]:
    normalized = _norm(row_text)
    if any(_norm(blocker) in normalized for blocker in EQUITY_TOTAL_BLOCKERS):
        return []
    return [label for label in EQUITY_TOTAL_LABELS if _norm(label) in normalized]


def _group_balance_sheet_window(
    doc: fitz.Document,
    events: list[dict],
    al_candidates: list[dict],
) -> tuple[int, int, dict]:
    group_candidates = [
        row for row in al_candidates
        if row.get("statement_role") in ("GROUP", "DUAL_GROUP_PARENT")
    ]
    if not group_candidates:
        raise ValueError("no group asset/liability candidate window")

    anchor_pages = [int(row["statement_anchor_page"]) for row in group_candidates]
    candidate_pages = [int(row["page"]) for row in group_candidates]
    start_page = min(anchor_pages + candidate_pages)
    group_events = [
        event for event in events
        if int(event.get("page") or 0) == start_page
        and event.get("role") in ("GROUP", "DUAL_GROUP_PARENT")
    ]
    if not group_events:
        preceding = [
            event for event in events
            if int(event.get("page") or 0) <= start_page
            and event.get("role") in ("GROUP", "DUAL_GROUP_PARENT")
        ]
        if not preceding:
            raise ValueError("group statement event missing at candidate anchor")
        preceding.sort(key=lambda event: (int(event.get("page") or 0), float(event.get("y") or 0)))
        group_event = preceding[-1]
        start_page = int(group_event["page"])
    else:
        group_events.sort(key=lambda event: float(event.get("y") or 0))
        group_event = group_events[0]

    parent_pages = sorted({
        int(event.get("page") or 0)
        for event in events
        if int(event.get("page") or 0) > start_page and event.get("role") == "PARENT"
    })
    hard_end = (parent_pages[0] - 1) if parent_pages else doc.page_count
    hard_end = min(hard_end, doc.page_count, max(candidate_pages + anchor_pages) + 6)

    end_page = hard_end
    stop_reason = "PARENT_OR_BOUNDED_END"
    for page_1b in range(start_page + 1, hard_end + 1):
        text = doc[page_1b - 1].get_text("text") or ""
        if _starts_next_statement(text):
            end_page = page_1b - 1
            stop_reason = f"NEXT_STATEMENT_AT_PAGE_{page_1b}"
            break
    if end_page < max(candidate_pages):
        raise ValueError(
            f"derived block ends before accepted A/L candidates end={end_page} max_candidate={max(candidate_pages)}"
        )
    return start_page, end_page, {
        "group_event": group_event,
        "stop_reason": stop_reason,
        "accepted_asset_liability_candidate_pages": sorted(set(candidate_pages)),
        "accepted_asset_liability_anchor_pages": sorted(set(anchor_pages)),
    }


def classify(page_records: list[dict], equity_rows: list[dict]) -> str:
    exact_rows = [row for row in equity_rows if row.get("exact_total_labels")]
    explicit_amount = [
        row for row in exact_rows
        if row.get("same_row_numeric_candidates") or row.get("next_row_numeric_candidates")
    ]
    if explicit_amount:
        return "EXPLICIT_GROUP_EQUITY_TERMINAL_WITH_AMOUNT_EVIDENCE"
    if exact_rows:
        return "EXPLICIT_GROUP_EQUITY_TERMINAL_WITHOUT_AMOUNT_EVIDENCE"
    if any(row.get("low_text_with_image") for row in page_records):
        return "GROUP_BLOCK_CONTAINS_IMAGE_ONLY_PAGE_WITHOUT_NATIVE_EQUITY_TERMINAL"
    if any("归属于母公司" in str(row.get("row_text") or "") for row in equity_rows):
        return "ATTRIBUTABLE_EQUITY_ONLY_NO_TOTAL_EQUITY_TERMINAL"
    if equity_rows:
        return "EQUITY_TEXT_PRESENT_NO_EXACT_TOTAL_TERMINAL"
    return "NO_EQUITY_TEXT_IN_GROUP_BALANCE_SHEET_BLOCK"


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
    window_evidence: dict = {}
    with _mupdf_diagnostic_guard():
        with fitz.open(stream=raw, filetype="pdf") as doc:
            events = blocks.formal_statement_events(doc)
            existing, _ = v166._collect_candidates_v16_6(doc, version["economic_date"])
            bridge, _ = v1715._collect_adjacent_bridge_candidates(doc, version["economic_date"])
            al_candidates = list(existing.get("TOTAL_ASSETS", [])) + list(existing.get("TOTAL_LIABILITIES", []))
            al_candidates += list(bridge.get("TOTAL_ASSETS", [])) + list(bridge.get("TOTAL_LIABILITIES", []))
            try:
                start_page, end_page, window_evidence = _group_balance_sheet_window(doc, events, al_candidates)
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                start_page, end_page = 1, min(doc.page_count, 6)
                window_evidence = {"derivation_failed": True}

            group_event = window_evidence.get("group_event")
            for page_1b in range(start_page, end_page + 1):
                page = doc[page_1b - 1]
                text = page.get_text("text") or ""
                words = page.get_text("words") or []
                images = page.get_images(full=True) or []
                rows = sorted(v14._rows_from_words(page), key=lambda row: float(row["y"]))
                tail_rows = [
                    {
                        "row_index": index,
                        "row_y": float(row["y"]),
                        "row_text": str(row.get("text") or "")[:1600],
                        "numeric_candidates": numeric_records(row),
                    }
                    for index, row in list(enumerate(rows))[-TAIL_ROW_LIMIT:]
                ]
                page_records.append({
                    "page": page_1b,
                    "text_chars": len(text.strip()),
                    "word_count": len(words),
                    "image_count": len(images),
                    "low_text_with_image": len(text.strip()) < 80 and bool(images),
                    "group_statement_role": group_event,
                    "row_count": len(rows),
                    "tail_rows": tail_rows,
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
                    exact = _is_exact_equity_total(str(row.get("text") or ""))
                    equity_rows.append({
                        "page": page_1b,
                        "row_index": index,
                        "row_y": float(row["y"]),
                        "row_text": str(row.get("text") or "")[:1600],
                        "matched_equity_hints": matched,
                        "exact_total_labels": exact,
                        "statement_role": group_event,
                        "same_row_numeric_candidates": same_nums,
                        "next_row_text": None if nxt is None else str(nxt.get("text") or "")[:1600],
                        "next_row_y_delta": delta,
                        "next_row_numeric_candidates": next_nums,
                    })

    category = classify(page_records, equity_rows)
    counters = Counter()
    for row in equity_rows:
        counters["equity_rows"] += 1
        if row.get("exact_total_labels"):
            counters["exact_total_rows"] += 1
        if row.get("same_row_numeric_candidates"):
            counters["same_row_amount_rows"] += 1
        if row.get("next_row_numeric_candidates"):
            counters["next_row_amount_rows"] += 1
    counters["image_only_pages"] = sum(bool(row.get("low_text_with_image")) for row in page_records)

    report = {
        "gate": "S3G1J_V17_16_EXACT_THREE_EQUITY_TERMINAL_DIAGNOSTIC",
        "diagnostic_only": True,
        "no_parser_change": True,
        "no_value_acceptance": True,
        "no_e_equals_a_minus_l_inference": True,
        "cross_statement_role_carry_prohibited": True,
        "accounting_tolerance_changed": False,
        "source_policy_changed": False,
        "announcement_id": aid,
        "source_code": version["source_code"],
        "report_family": version["report_family"],
        "economic_date": version["economic_date"],
        "canonical_title": version["canonical_title"],
        "canonical_source_url": version["canonical_source_url"],
        "source_sha256": digest,
        "formal_window": {"start_page": start_page, "end_page": end_page, **window_evidence},
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
        "formal_window": {k: report["formal_window"].get(k) for k in ("start_page", "end_page", "stop_reason")},
        "counts": report["counts"],
        "pass": report["pass"],
        "errors": errors,
    }, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
