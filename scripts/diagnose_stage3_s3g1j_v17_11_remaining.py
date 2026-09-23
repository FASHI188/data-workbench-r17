#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import fitz
import requests

import extract_stage3_financial_pdf_values as base
import stage3_financial_pdf_parser as parser_base
import stage3_financial_coordinate_fallback_v14 as v14
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard, parse_pdf_bytes
from stage3_financial_spatial_alias_v16_7 import diagnose_spatial_balance_sheet_v16_7

CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
EXPECTED_TOTAL_REMAINING = 82
EXPECTED_SHARDS = (0, 1, 7, 9)
TITLE_HINTS = (
    "资产负债表", "财务状况表", "合并及母公司资产负债表",
    "balance sheet", "statement of financial position", "statement of financial condition",
)
TERMINAL_HINTS = (
    "资产总计", "资产合计", "总资产", "负债合计", "总负债",
    "所有者权益合计", "股东权益合计", "权益合计",
    "负债和所有者权益", "负债及所有者权益", "负债和股东权益", "负债及股东权益",
    "total assets", "total liabilities", "total equity",
)
CONTINUATION_HINTS = ("续", "接上表", "continued", "continuation")
GROUP_HINTS = ("合并", "本集团", "集团", "consolidated", "group")
PARENT_HINTS = ("母公司", "本公司", "公司", "parent company", "company")
DATE_LINE_RE = re.compile(r"20\d{2}\s*[年./-]\s*\d{1,2}\s*[月./-]\s*\d{1,2}\s*日?")
UNIT_LINE_RE = re.compile(r"(?:单位|金额单位|货币单位|人民币|RMB|CNY).{0,30}(?:亿元|百万元|万元|千元|元)", re.I)


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _matching_lines(text: str, hints: tuple[str, ...], limit: int = 30) -> list[str]:
    out: list[str] = []
    normalized_hints = tuple(_norm(x) for x in hints)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        n = _norm(line)
        if any(h in n for h in normalized_hints):
            out.append(line[:500])
            if len(out) >= limit:
                break
    return out


def _read_rows(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.11-exact-82-structure-diagnostic",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def _concept_stage(funnel: dict, counts: dict, concept: str) -> str:
    if int(counts.get(concept, 0) or 0) > 0:
        return "CANDIDATE_PRESENT"
    stages = (
        (f"{concept}_group_alias_with_right_amount", "POST_AMOUNT_FILTER"),
        (f"{concept}_group_alias_period_matched", "NO_RIGHT_AMOUNT"),
        (f"{concept}_group_alias_with_unit", "PERIOD_GATE"),
        (f"{concept}_alias_group_role", "NO_UNIT_CONTEXT"),
        (f"{concept}_alias_rows", "NO_GROUP_ROLE_BINDING"),
    )
    for key, label in stages:
        if int(funnel.get(key, 0) or 0) > 0:
            return label
    return "NO_ALIAS_ROWS"


def _funnel_category(diag: dict) -> str:
    funnel = diag.get("funnel") or {}
    counts = diag.get("candidate_counts") or {}
    if diag.get("recovered"):
        return "UNEXPECTED_RECOVERY"
    if diag.get("v16_6_recovered"):
        return "COLUMN_ROLE_GATE"
    if int(funnel.get("candidate_pages", 0) or 0) == 0:
        return "NO_CANDIDATE_PAGES"
    if int(funnel.get("formal_group_events", 0) or 0) == 0:
        return "NO_FORMAL_GROUP_EVENT"
    if all(int(counts.get(c, 0) or 0) > 0 for c in CONCEPTS):
        return "CANDIDATES_NO_VALID_IDENTITY"
    missing = [c for c in CONCEPTS if int(counts.get(c, 0) or 0) == 0]
    stages = [_concept_stage(funnel, counts, c) for c in missing]
    for label in (
        "POST_AMOUNT_FILTER", "NO_RIGHT_AMOUNT", "PERIOD_GATE",
        "NO_UNIT_CONTEXT", "NO_GROUP_ROLE_BINDING", "NO_ALIAS_ROWS",
    ):
        if label in stages:
            return f"MISSING_CONCEPT_{label}"
    return "OTHER_FAIL_CLOSED"


def _page_structure(page: fitz.Page, page_1b: int) -> dict:
    text = page.get_text("text") or ""
    words = page.get_text("words") or []
    blocks = page.get_text("blocks") or []
    images = page.get_images(full=True) or []
    title_lines = _matching_lines(text, TITLE_HINTS)
    terminal_lines = _matching_lines(text, TERMINAL_HINTS)
    continuation_lines = _matching_lines(text, CONTINUATION_HINTS, 10)
    unit_lines = [line.strip()[:500] for line in text.splitlines() if line.strip() and UNIT_LINE_RE.search(line)]
    date_lines = [line.strip()[:500] for line in text.splitlines() if line.strip() and DATE_LINE_RE.search(line)][:30]
    detected_unit, detected_mult = parser_base.detect_unit(text)
    normalized = _norm(text)
    group_hits = sorted({x for x in GROUP_HINTS if _norm(x) in normalized})
    parent_hits = sorted({x for x in PARENT_HINTS if _norm(x) in normalized})
    return {
        "page": page_1b,
        "text_chars": len(text.strip()),
        "word_count": len(words),
        "block_count": len(blocks),
        "image_count": len(images),
        "low_text_with_image": len(text.strip()) < 80 and bool(images),
        "title_lines": title_lines,
        "terminal_lines": terminal_lines,
        "continuation_lines": continuation_lines,
        "unit_lines": unit_lines[:20],
        "detected_unit": detected_unit,
        "detected_unit_multiplier": str(detected_mult) if detected_mult is not None else None,
        "date_lines": date_lines,
        "group_role_hints": group_hits,
        "parent_role_hints": parent_hits,
    }


def _structural_category(pages: list[dict], role_events: list, validation_errors: list[str]) -> list[str]:
    tags: list[str] = []
    if pages and sum(bool(p["low_text_with_image"]) for p in pages) / len(pages) >= 0.8:
        tags.append("LIKELY_SCANNED_OR_IMAGE_ONLY")
    title_pages = [p["page"] for p in pages if p["title_lines"]]
    terminal_pages = [p["page"] for p in pages if p["terminal_lines"]]
    continuation_pages = [p["page"] for p in pages if p["continuation_lines"]]
    unit_pages = [p["page"] for p in pages if p["detected_unit"] or p["unit_lines"]]
    if title_pages and not terminal_pages:
        tags.append("TITLE_WITHOUT_TERMINAL_ROWS")
    if terminal_pages and not title_pages:
        tags.append("TERMINAL_ROWS_WITHOUT_RECOGNIZED_TITLE")
    if title_pages and terminal_pages and set(title_pages).isdisjoint(terminal_pages):
        tags.append("TITLE_AND_TERMINALS_SPLIT_ACROSS_PAGES")
    if continuation_pages:
        tags.append("CONTINUATION_MARKER_PRESENT")
    if title_pages and not unit_pages:
        tags.append("STATEMENT_TITLE_WITHOUT_DETECTED_UNIT")
    if not role_events and (title_pages or terminal_pages):
        tags.append("VISIBLE_STATEMENT_EVIDENCE_WITHOUT_ROLE_EVENT")
    if any("BALANCE_SHEET_IDENTITY_MISMATCH" in str(x) for x in validation_errors):
        tags.append("EXPLICIT_IDENTITY_MISMATCH")
    if any(p["group_role_hints"] and p["parent_role_hints"] for p in pages):
        tags.append("GROUP_AND_PARENT_HINTS_COEXIST")
    return tags or ["NO_ADDITIONAL_STRUCTURE_TAG"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--acceptance", required=True)
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--shards", type=int, default=64)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.shards != 64 or args.shard not in EXPECTED_SHARDS:
        raise ValueError("diagnostic frozen to shards 0,1,7,9 of the 64-shard partition")
    accepted = json.loads(Path(args.acceptance).read_text(encoding="utf-8"))
    if not accepted.get("pass") or int(accepted.get("v17_11_remaining_count", -1)) != EXPECTED_TOTAL_REMAINING:
        raise ValueError("input is not the accepted V17.11 exact-82 residual state")
    target_ids = {str(x["announcement_id"]) for x in accepted.get("remaining") or []}
    if len(target_ids) != EXPECTED_TOTAL_REMAINING:
        raise ValueError(f"expected 82 unique residual ids, got {len(target_ids)}")

    rows = [
        row for row in _read_rows(Path(args.versions))
        if row["canonical_announcement_id"] in target_ids
        and base.stable_shard(row["canonical_announcement_id"], args.shards) == args.shard
    ]
    rows.sort(key=lambda r: r["canonical_announcement_id"])

    session = requests.Session()
    diagnostics: list[dict] = []
    failures: list[dict] = []
    funnel_counts = Counter()
    structure_counts = Counter()
    family_counts = defaultdict(Counter)

    for index, row in enumerate(rows, 1):
        aid = row["canonical_announcement_id"]
        try:
            raw = _download(session, row["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            with fitz.open(stream=raw, filetype="pdf") as doc:
                with _mupdf_diagnostic_guard():
                    parsed = parse_pdf_bytes(raw, row["economic_date"])
                    spatial = diagnose_spatial_balance_sheet_v16_7(doc, row["economic_date"])
                    role_events = v14._statement_events(doc)
                    pages = [_page_structure(doc[pno], pno + 1) for pno in range(doc.page_count)]
            validation_errors = list(parsed.get("validation_errors") or [])
            funnel_category = _funnel_category(spatial)
            structure_tags = _structural_category(pages, role_events, validation_errors)
            funnel_counts[funnel_category] += 1
            for tag in structure_tags:
                structure_counts[tag] += 1
                family_counts[row["report_family"]][tag] += 1
            evidence_pages = [
                p for p in pages
                if p["title_lines"] or p["terminal_lines"] or p["continuation_lines"]
                or p["unit_lines"] or p["date_lines"] or p["low_text_with_image"]
            ]
            diagnostics.append({
                "announcement_id": aid,
                "source_code": row["source_code"],
                "report_family": row["report_family"],
                "economic_date": row["economic_date"],
                "canonical_title": row["canonical_title"],
                "canonical_source_url": row["canonical_source_url"],
                "source_sha256": digest,
                "source_bytes": len(raw),
                "page_count": len(pages),
                "current_validation_errors": validation_errors,
                "current_tier1_found": parsed.get("tier1_found"),
                "current_tier2_found": parsed.get("tier2_found"),
                "current_balance_sheet_block": parsed.get("balance_sheet_block"),
                "funnel_category": funnel_category,
                "structural_tags": structure_tags,
                "statement_role_event_count": len(role_events),
                "statement_role_events": role_events,
                "candidate_counts": spatial.get("candidate_counts"),
                "funnel": spatial.get("funnel"),
                "identity": spatial.get("identity"),
                "column_role_gate": spatial.get("column_role_gate"),
                "evidence_pages": evidence_pages,
                "low_text_image_page_count": sum(bool(p["low_text_with_image"]) for p in pages),
            })
        except Exception as exc:
            failures.append({
                "announcement_id": aid,
                "source_code": row.get("source_code"),
                "error": f"{type(exc).__name__}: {exc}",
            })
        print(f"S3G1J_V17_11_REMAINING shard={args.shard} {index}/{len(rows)} aid={aid}", flush=True)

    report = {
        "gate": "S3G1J_V17_11_EXACT_82_STRUCTURE_DIAGNOSTIC_SHARD",
        "diagnostic_only": True,
        "no_parser_change": True,
        "no_ocr": True,
        "accounting_tolerance_changed": False,
        "source_policy_changed": False,
        "shard": args.shard,
        "shards": args.shards,
        "input_residual_count": len(rows),
        "diagnosed_count": len(diagnostics),
        "diagnostic_failures": failures,
        "funnel_category_counts": dict(funnel_counts),
        "structural_tag_counts": dict(structure_counts),
        "family_structural_tag_counts": {k: dict(v) for k, v in family_counts.items()},
        "diagnostics": diagnostics,
        "pass": not failures and len(diagnostics) == len(rows),
        "stage4_alpha_locked": True,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "shard": args.shard,
        "input": len(rows),
        "diagnosed": len(diagnostics),
        "funnel_categories": dict(funnel_counts),
        "structure_tags": dict(structure_counts),
        "failures": failures,
        "pass": report["pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
