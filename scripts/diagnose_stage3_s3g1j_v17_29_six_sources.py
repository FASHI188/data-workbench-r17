#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import fitz
import requests

import stage3_financial_pdf_parser_v21 as parser

EVIDENCE_PATH = Path("governance/stage3_s3g1j_v17_29_residual_classification.json")
EXPECTED_IDS = {
    "1202799494", "1204077386", "1205543437",
    "1209806910", "1223347318", "1223407043",
}
BANK_EXCLUDED_ID = "1219834247"

TITLE_HINTS = ("资产负债表", "财务状况表")
GROUP_ROLE_HINTS = ("合并", "本集团", "集团")
PARENT_ROLE_HINTS = ("母公司", "本公司", "公司")
UNIT_HINT_RE = re.compile(r"(?:单位\s*[:：]?\s*)?(?:人民币\s*)?(?:元|千元|万元|百万元)")
NUMBER_RE = re.compile(r"[-−]?\(?\d[\d,，.]*\)?")

ALIASES = {
    "TOTAL_ASSETS": ("资产总计", "资产合计"),
    "TOTAL_LIABILITIES": ("负债合计", "负债总计"),
    "TOTAL_EQUITY": (
        "所有者权益合计", "股东权益合计", "所有者权益（或股东权益）合计",
        "归属于母公司所有者权益合计", "归属于母公司股东权益合计",
        "归属于母公司所有者的权益", "归属于母公司股东的权益",
    ),
}


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").replace("，", ",")


def expected_date_forms(date: str) -> tuple[str, ...]:
    y, m, d = date.split("-")
    return (
        f"{y}年{int(m)}月{int(d)}日",
        f"{y}年{m}月{d}日",
        date,
        date.replace("-", "/"),
        f"{y}.{m}.{d}",
    )


def line_rows(page: fitz.Page) -> list[dict[str, Any]]:
    raw = page.get_text("dict")
    rows: list[dict[str, Any]] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(str(span.get("text") or "") for span in spans).strip()
            if not text:
                continue
            bbox = line.get("bbox") or [0, 0, 0, 0]
            rows.append({
                "text": text,
                "compact": compact(text),
                "bbox": [round(float(v), 2) for v in bbox],
                "y0": round(float(bbox[1]), 2),
                "y1": round(float(bbox[3]), 2),
            })
    rows.sort(key=lambda r: (r["y0"], r["bbox"][0], r["compact"]))
    return rows


def contains_any(text: str, hints: tuple[str, ...]) -> bool:
    c = compact(text)
    return any(compact(h) in c for h in hints)


def concept_hits(rows: list[dict[str, Any]], concept: str) -> list[dict[str, Any]]:
    aliases = ALIASES[concept]
    out = []
    for i, row in enumerate(rows):
        if contains_any(row["compact"], aliases):
            numbers = NUMBER_RE.findall(row["text"])
            adjacent = []
            for j in range(max(0, i - 2), min(len(rows), i + 3)):
                if j == i:
                    continue
                if abs(rows[j]["y0"] - row["y0"]) <= 36 or abs(rows[j]["y0"] - row["y1"]) <= 36:
                    adjacent.append(rows[j]["text"])
            out.append({
                "line_index": i,
                "text": row["text"],
                "bbox": row["bbox"],
                "number_tokens": numbers[:8],
                "number_token_count": len(numbers),
                "adjacent_lines": adjacent[:8],
            })
    return out


def title_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, row in enumerate(rows):
        if contains_any(row["compact"], TITLE_HINTS):
            c = row["compact"]
            role = "GROUP" if any(h in c for h in GROUP_ROLE_HINTS) else (
                "PARENT" if any(h in c for h in PARENT_ROLE_HINTS) else "GENERIC"
            )
            out.append({"line_index": i, "text": row["text"], "bbox": row["bbox"], "role": role})
    return out


def period_hits(rows: list[dict[str, Any]], date: str) -> list[dict[str, Any]]:
    forms = tuple(compact(x) for x in expected_date_forms(date))
    out = []
    for i, row in enumerate(rows):
        c = row["compact"]
        if any(form in c for form in forms):
            out.append({"line_index": i, "text": row["text"], "bbox": row["bbox"]})
    return out


def unit_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, row in enumerate(rows):
        if UNIT_HINT_RE.search(compact(row["text"])):
            out.append({"line_index": i, "text": row["text"], "bbox": row["bbox"]})
    return out


def role_header_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, row in enumerate(rows):
        c = row["compact"]
        group = [h for h in GROUP_ROLE_HINTS if h in c]
        parent = [h for h in PARENT_ROLE_HINTS if h in c]
        if group or parent:
            out.append({
                "line_index": i,
                "text": row["text"],
                "bbox": row["bbox"],
                "group_hints": group,
                "parent_hints": parent,
            })
    return out


def local_windows(rows: list[dict[str, Any]], anchors: list[int], radius: int = 3) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for idx in anchors:
        lo, hi = max(0, idx - radius), min(len(rows), idx + radius + 1)
        key = (lo, hi)
        if key in seen:
            continue
        seen.add(key)
        out.append({"from": lo, "to": hi - 1, "lines": [rows[i]["text"] for i in range(lo, hi)]})
    return out


def fetch_pdf(url: str, expected_sha: str, expected_bytes: int | None) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Stage3Evidence/1.0)",
        "Referer": "https://www.cninfo.com.cn/",
        "Accept": "application/pdf,*/*;q=0.8",
    }
    last: Exception | None = None
    for attempt in range(1, 5):
        try:
            response = requests.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.content
            digest = hashlib.sha256(data).hexdigest()
            if digest != expected_sha:
                raise ValueError(f"source sha mismatch expected={expected_sha} actual={digest}")
            if expected_bytes and len(data) != expected_bytes:
                raise ValueError(f"source byte mismatch expected={expected_bytes} actual={len(data)}")
            if not data.startswith(b"%PDF"):
                raise ValueError("source bytes are not PDF")
            return data
        except Exception as exc:
            last = exc
            if attempt < 4:
                time.sleep(attempt * 5)
    raise RuntimeError(f"exact source download failed: {last}")


def parser_snapshot(pdf_bytes: bytes, date: str) -> dict[str, Any]:
    try:
        parsed = parser.parse_pdf_bytes(pdf_bytes, date)
    except Exception as exc:
        return {"exception": f"{type(exc).__name__}:{exc}"}
    observations = parsed.get("observations") or {}
    return {
        "parser_version": parsed.get("parser_version"),
        "tier1_found": parsed.get("tier1_found"),
        "tier2_found": parsed.get("tier2_found"),
        "validation_errors": parsed.get("validation_errors") or [],
        "found_concepts": sorted(k for k, v in observations.items() if isinstance(v, dict) and v.get("status") == "FOUND"),
        "balance_sheet_block": parsed.get("balance_sheet_block"),
    }


def load_targets(evidence_path: Path) -> dict[str, dict[str, Any]]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    boundary = evidence["surviving_p0_root_cause_boundary"]
    targets = {row["announcement_id"]: row for row in boundary["diagnostic_only"]}
    if set(targets) != EXPECTED_IDS:
        raise ValueError(f"diagnostic target set drift {sorted(targets)}")
    if {row["announcement_id"] for row in boundary["do_not_promote"]} != {BANK_EXCLUDED_ID}:
        raise ValueError("bank isolation boundary drift")
    if boundary["safe_exact_source_candidate_count"] != 0:
        raise ValueError("surviving P0 unexpectedly already has safe candidate")
    return targets


def load_document_rows(path: Path, targets: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            aid = row.get("announcement_id", "")
            if aid in targets:
                if aid in found:
                    raise ValueError(f"duplicate document row {aid}")
                found[aid] = row
    if set(found) != set(targets):
        raise ValueError(f"missing document rows {sorted(set(targets)-set(found))}")
    return found


def analyze_pdf(pdf_bytes: bytes, target: dict[str, Any]) -> dict[str, Any]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: list[dict[str, Any]] = []
    for pageno in range(doc.page_count):
        page = doc[pageno]
        rows = line_rows(page)
        titles = title_hits(rows)
        periods = period_hits(rows, target["economic_date"])
        units = unit_hits(rows)
        roles = role_header_hits(rows)
        concepts = {concept: concept_hits(rows, concept) for concept in ALIASES}
        has_concept = {concept: bool(hits) for concept, hits in concepts.items()}
        relevant = bool(titles or periods or units or roles or any(has_concept.values()))
        if not relevant:
            continue
        anchor_indexes = [x["line_index"] for x in titles + periods + units + roles]
        for hits in concepts.values():
            anchor_indexes.extend(x["line_index"] for x in hits)
        pages.append({
            "page": pageno + 1,
            "title_hits": titles,
            "period_hits": periods,
            "unit_hits": units,
            "role_header_hits": roles,
            "concept_hits": concepts,
            "all_three_concepts_on_page": all(has_concept.values()),
            "group_title_present": any(x["role"] == "GROUP" for x in titles),
            "generic_title_present": any(x["role"] == "GENERIC" for x in titles),
            "expected_period_on_page": bool(periods),
            "unit_on_page": bool(units),
            "context_windows": local_windows(rows, sorted(set(anchor_indexes)), radius=2)[:24],
        })
    return {"page_count": doc.page_count, "pages": pages}


def family_evidence(target: dict[str, Any], spatial: dict[str, Any]) -> dict[str, Any]:
    pages = spatial["pages"]
    all3 = [p for p in pages if p["all_three_concepts_on_page"]]
    group_title = [p["page"] for p in pages if p["group_title_present"]]
    all3_group = [p["page"] for p in all3 if p["group_title_present"]]
    all3_period = [p["page"] for p in all3 if p["expected_period_on_page"]]
    all3_unit = [p["page"] for p in all3 if p["unit_on_page"]]
    all3_group_period_unit = [
        p["page"] for p in all3
        if p["group_title_present"] and p["expected_period_on_page"] and p["unit_on_page"]
    ]
    equity_pair_pages = []
    for p in pages:
        eq = p["concept_hits"]["TOTAL_EQUITY"]
        if any(hit["number_token_count"] >= 2 for hit in eq):
            equity_pair_pages.append(p["page"])
    return {
        "prior_root_cause": target["root_cause"],
        "pages_with_all_three_concepts": [p["page"] for p in all3],
        "pages_with_explicit_group_title": group_title,
        "all_three_plus_group_title_pages": all3_group,
        "all_three_plus_expected_period_pages": all3_period,
        "all_three_plus_unit_pages": all3_unit,
        "all_three_plus_group_period_unit_pages": all3_group_period_unit,
        "equity_line_with_two_or_more_number_tokens_pages": sorted(set(equity_pair_pages)),
        "explicit_group_role_visible_somewhere": bool(group_title),
        "role_local_period_visible_on_all_three_page": bool(all3_period),
        "role_local_unit_visible_on_all_three_page": bool(all3_unit),
        "explicit_equity_pair_visible_on_single_line": bool(equity_pair_pages),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--documents", required=True)
    ap.add_argument("--evidence", default=str(EVIDENCE_PATH))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    targets = load_targets(Path(args.evidence))
    docs = load_document_rows(Path(args.documents), targets)
    results = []
    for aid in sorted(targets):
        target = targets[aid]
        row = docs[aid]
        expected_sha = target["source_sha256"]
        if row.get("selected_source_sha256") != expected_sha:
            raise ValueError(f"{aid}: selected source SHA drift")
        if row.get("document_status") != "ERROR":
            raise ValueError(f"{aid}: expected residual ERROR row")
        if row.get("tie_candidate_count") != "1" or row.get("tie_resolution") != "TIE_SOURCE_INCOMPLETE":
            raise ValueError(f"{aid}: expected single-canonical incomplete residual")
        url = row.get("selected_source_url") or row.get("canonical_source_url")
        if not url:
            raise ValueError(f"{aid}: missing exact source URL")
        expected_bytes = int(row["selected_source_bytes"]) if row.get("selected_source_bytes") else None
        pdf = fetch_pdf(url, expected_sha, expected_bytes)
        spatial = analyze_pdf(pdf, target)
        result = {
            "announcement_id": aid,
            "source_code": target["source_code"],
            "report_family": target["report_family"],
            "economic_date": target["economic_date"],
            "source_url": url,
            "source_sha256": expected_sha,
            "source_bytes": len(pdf),
            "prior_root_cause": target["root_cause"],
            "parser_snapshot": parser_snapshot(pdf, target["economic_date"]),
            "spatial_evidence": spatial,
        }
        result["family_evidence"] = family_evidence(target, spatial)
        results.append(result)

    family_counts: dict[str, int] = {}
    for row in results:
        family_counts[row["prior_root_cause"]] = family_counts.get(row["prior_root_cause"], 0) + 1
    report = {
        "gate": "S3G1J_V17_29_SIX_SOURCE_LOCKED_DIAGNOSTIC_V1",
        "diagnostic_only": True,
        "target_count": len(results),
        "target_announcement_ids": [r["announcement_id"] for r in results],
        "bank_specific_excluded_announcement_id": BANK_EXCLUDED_ID,
        "prior_root_cause_counts": dict(sorted(family_counts.items())),
        "all_exact_source_sha_verified": True,
        "formal_parser_changed": False,
        "runtime_authority_changed": False,
        "production_data_changed": False,
        "candidate_parser_authorized": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_locked": True,
        "targets": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "gate": report["gate"],
        "target_count": report["target_count"],
        "prior_root_cause_counts": report["prior_root_cause_counts"],
        "target_summary": [
            {"announcement_id": r["announcement_id"], **r["family_evidence"]}
            for r in results
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
