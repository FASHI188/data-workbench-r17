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

import stage3_financial_pdf_parser as parser_base
import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16 as spatial
import stage3_financial_statement_blocks_v16_5 as blocks
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard

TARGET_CATEGORIES = {
    "NO_FORMAL_GROUP_EVENT",
    "MISSING_CONCEPT_NO_GROUP_ROLE_BINDING",
}
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
TITLE_HINTS = (
    "资产负债表",
    "资产及负债表",
    "财务状况表",
    "balance sheet",
    "statement of financial position",
    "statement of financial condition",
)


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _has_title_hint(value: str) -> bool:
    n = _norm(value)
    return any(_norm(h) in n for h in TITLE_HINTS)


def _read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def _download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.1-title-role-trace",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def _alias_rows(doc: fitz.Document, events: list[dict], candidate_pages: list[int]) -> list[dict]:
    concepts = {
        "TOTAL_ASSETS": parser_base.TIER1_ALIASES.get("TOTAL_ASSETS") or [],
        "TOTAL_LIABILITIES": parser_base.TIER2_ALIASES.get("TOTAL_LIABILITIES") or [],
        "TOTAL_EQUITY": parser_base.TIER2_ALIASES.get("TOTAL_EQUITY") or [],
    }
    out: list[dict] = []
    seen: set[tuple] = set()
    for pno in candidate_pages:
        for row in v14._rows_from_words(doc[pno]):
            for concept, aliases in concepts.items():
                for alias in aliases:
                    for geom in spatial._alias_geometries(row, alias, concept):
                        key = (pno + 1, concept, alias, round(float(geom["x0"]), 2), round(float(row["y"]), 2))
                        if key in seen:
                            continue
                        seen.add(key)
                        bound = blocks.bind_alias_to_preceding_statement_event(
                            events, pno + 1, float(row["y"]), float(geom["x0"])
                        )
                        out.append({
                            "page": pno + 1,
                            "row_y": float(row["y"]),
                            "concept": concept,
                            "alias": alias,
                            "alias_x0": float(geom["x0"]),
                            "row_text": row["text"][:800],
                            "bound_event": None if bound is None else {
                                k: bound.get(k)
                                for k in ("page", "y", "x0", "x1", "x_center", "role", "continuation", "line", "matched_title")
                            },
                        })
    return out


def _trace_class(original_category: str, events: list[dict], title_lines: list[dict], alias_rows: list[dict]) -> str:
    group_events = [e for e in events if e.get("role") in ("GROUP", "DUAL_GROUP_PARENT")]
    if original_category == "NO_FORMAL_GROUP_EVENT":
        if not title_lines:
            return "NO_TITLE_HINT_TEXT"
        if any(x.get("string_role") in ("GROUP", "DUAL_GROUP_PARENT") for x in title_lines):
            return "STRING_TITLE_RECOGNIZED_BUT_ROW_EVENT_MISSED"
        return "UNRECOGNIZED_TITLE_VARIANT"

    non_group = [
        x for x in alias_rows
        if (x.get("bound_event") or {}).get("role") in ("PARENT", "UNKNOWN_STATEMENT")
    ]
    if non_group:
        return "ALIAS_BOUND_NON_GROUP_EVENT"
    unbound = [x for x in alias_rows if x.get("bound_event") is None]
    if unbound and group_events:
        distances = []
        for row in unbound:
            page = int(row["page"])
            before = [e for e in group_events if int(e["page"]) <= page]
            after_same = [e for e in group_events if int(e["page"]) == page and float(e["y"]) > float(row["row_y"]) + 0.5]
            if after_same:
                return "GROUP_EVENT_AFTER_ALIAS_SAME_PAGE"
            if before:
                distances.append(page - max(int(e["page"]) for e in before))
        if distances and min(distances) > int(blocks.MAX_BLOCK_LOOKBACK):
            return "GROUP_EVENT_BEYOND_LOOKBACK"
        return "ALIAS_WITHOUT_ELIGIBLE_GROUP_EVENT"
    if unbound and not group_events:
        if title_lines:
            return "NO_GROUP_EVENT_WITH_TITLE_HINT"
        return "NO_GROUP_EVENT_NO_TITLE_HINT"
    return "ROLE_BINDING_OTHER"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--v17-summary", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    summary = json.loads(Path(args.v17_summary).read_text(encoding="utf-8"))
    if not summary.get("pass") or int(summary.get("input_residual_count", -1)) != 91:
        raise ValueError("V17 residual summary is not the accepted exact-91 diagnostic")
    targets = {
        str(x["announcement_id"]): x
        for x in summary.get("diagnostics") or []
        if x.get("category") in TARGET_CATEGORIES
    }
    if len(targets) != 36:
        raise ValueError(f"expected exact 36 title/role residuals, got {len(targets)}")

    versions = _read_versions(Path(args.versions))
    missing = sorted(set(targets) - set(versions))
    if missing:
        raise ValueError(f"target ids missing from frozen versions: {missing}")

    session = requests.Session()
    rows: list[dict] = []
    errors: list[str] = []
    trace_counts = Counter()
    unrecognized_title_lines = Counter()

    for idx, aid in enumerate(sorted(targets), 1):
        version = versions[aid]
        original = targets[aid]
        record = {
            "announcement_id": aid,
            "source_code": version["source_code"],
            "report_family": version["report_family"],
            "economic_date": version["economic_date"],
            "canonical_title": version["canonical_title"],
            "original_v17_category": original["category"],
            "original_concept_stage": original.get("concept_stage") or {},
        }
        try:
            raw = _download(session, version["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            with fitz.open(stream=raw, filetype="pdf") as doc:
                with _mupdf_diagnostic_guard():
                    events = blocks.formal_statement_events(doc)
                    candidate_pages = v14._candidate_pages(doc)
                    title_lines: list[dict] = []
                    for pno in range(doc.page_count):
                        text = doc[pno].get_text("text") or ""
                        for line in text.splitlines():
                            stripped = line.strip()
                            if not stripped or not _has_title_hint(stripped):
                                continue
                            role, continuation = blocks.classify_formal_statement_title(stripped)
                            title_lines.append({
                                "page": pno + 1,
                                "line": stripped[:800],
                                "normalized_length": len(_norm(stripped)),
                                "string_role": role,
                                "continuation": continuation,
                            })
                            if role is None:
                                unrecognized_title_lines[_norm(stripped)[:300]] += 1
                    word_title_rows: list[dict] = []
                    title_pages = {int(x["page"]) - 1 for x in title_lines}
                    for pno in sorted(title_pages):
                        for row in v14._rows_from_words(doc[pno]):
                            if not _has_title_hint(row["text"]):
                                continue
                            occurrences = blocks._title_occurrences(row)
                            word_title_rows.append({
                                "page": pno + 1,
                                "row_y": float(row["y"]),
                                "row_text": row["text"][:1000],
                                "normalized_length": len(blocks._norm_title(row["text"])),
                                "occurrences": occurrences,
                            })
                    alias_rows = _alias_rows(doc, events, candidate_pages)
                    trace_class = _trace_class(original["category"], events, title_lines, alias_rows)
                    trace_counts[trace_class] += 1
                    record.update({
                        "sha256": digest,
                        "page_count": doc.page_count,
                        "candidate_pages": [p + 1 for p in candidate_pages],
                        "formal_statement_events": events,
                        "formal_group_events": [e for e in events if e.get("role") in ("GROUP", "DUAL_GROUP_PARENT")],
                        "title_hint_lines": title_lines,
                        "word_title_rows": word_title_rows,
                        "alias_rows": alias_rows[:120],
                        "alias_row_count": len(alias_rows),
                        "trace_class": trace_class,
                    })
        except Exception as exc:
            record["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        rows.append(record)
        print(f"V17_1_TITLE_ROLE_TRACE {idx}/{len(targets)} aid={aid}", flush=True)

    report = {
        "gate": "S3G1J_V17_1_TITLE_ROLE_TRACE",
        "diagnostic_pass": not errors and len(rows) == 36,
        "sample_count": len(rows),
        "target_categories": sorted(TARGET_CATEGORIES),
        "trace_class_counts": dict(trace_counts),
        "top_unrecognized_title_lines": [
            {"normalized_line": line, "count": count}
            for line, count in unrecognized_title_lines.most_common(50)
        ],
        "rows": rows,
        "policy": {
            "diagnostic_only": True,
            "parser_policy_changed": False,
            "no_ocr": True,
            "stage4_alpha_locked": True,
        },
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "sample_count": len(rows),
        "trace_class_counts": dict(trace_counts),
        "errors": errors,
        "diagnostic_pass": report["diagnostic_pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["diagnostic_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
