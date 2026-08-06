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

import extract_stage3_financial_pdf_values as base
import stage3_financial_pdf_parser as parser_base
import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_pdf_parser_v8 as v13
import stage3_financial_spatial_alias_v16 as spatial

TARGET_IDS = {"1212731093", "1217717273", "1225153907", "1219411922"}
CONCEPTS = {
    "TOTAL_ASSETS": parser_base.TIER1_ALIASES.get("TOTAL_ASSETS") or [],
    "TOTAL_LIABILITIES": parser_base.TIER2_ALIASES.get("TOTAL_LIABILITIES") or [],
    "TOTAL_EQUITY": parser_base.TIER2_ALIASES.get("TOTAL_EQUITY") or [],
}
NUMBERISH_RE = re.compile(r"[0-9０-９,，.．()（）\-—–]|")


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V17.13-no-right-amount-diagnostic",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    if not raw.startswith(b"%PDF"):
        raise ValueError(f"source is not PDF bytes={len(raw)}")
    return raw


def word_record(word: dict) -> dict:
    return {
        "text": str(word.get("text") or ""),
        "x0": float(word.get("x0") or 0),
        "x1": float(word.get("x1") or 0),
        "y0": float(word.get("y0") or 0),
        "y1": float(word.get("y1") or 0),
    }


def numberish(text: str) -> bool:
    return any(ch.isdigit() for ch in text) or any(ch in text for ch in ",，.．()（）-—–")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--announcement-id", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    aid = str(args.announcement_id)
    if aid not in TARGET_IDS:
        raise ValueError(f"diagnostic frozen to exact target IDs: {sorted(TARGET_IDS)}")
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    if not summary.get("pass") or summary.get("input_residual_count") != 82:
        raise ValueError("not the accepted V17.12 exact-82 summary")
    upstream = {str(x["announcement_id"]): x for x in summary.get("diagnostics") or []}
    if set(x for x, row in upstream.items() if row.get("category") == "MISSING_CONCEPT_NO_RIGHT_AMOUNT") != TARGET_IDS:
        raise ValueError("accepted no-right-amount target set changed")

    versions = read_versions(Path(args.versions))
    if aid not in versions:
        raise ValueError(f"version row missing {aid}")
    version = versions[aid]
    expected = upstream[aid]
    missing_concepts = sorted(
        concept for concept, stage in (expected.get("concept_stage") or {}).items()
        if stage == "NO_RIGHT_AMOUNT"
    )
    if not missing_concepts:
        raise ValueError(f"target has no NO_RIGHT_AMOUNT concept {aid}")

    session = requests.Session()
    raw = download(session, version["canonical_source_url"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected.get("sha256"):
        raise ValueError(f"source SHA changed expected={expected.get('sha256')} actual={digest}")

    evidence_rows: list[dict] = []
    with fitz.open(stream=raw, filetype="pdf") as doc:
        events = v14._statement_events(doc)
        for pno in range(doc.page_count):
            role_event = v14._nearest_statement_event(events, pno + 1)
            unit = mult = unit_page = None
            if role_event is not None:
                unit, mult, unit_page = spatial._role_unit_context(doc, role_event, pno)
            for row_index, row in enumerate(v14._rows_from_words(doc[pno])):
                for concept in missing_concepts:
                    geometries = []
                    for alias in CONCEPTS[concept]:
                        for geom in spatial._alias_geometries(row, alias, concept):
                            geometries.append((alias, geom))
                    if not geometries:
                        continue
                    geometries.sort(
                        key=lambda item: (
                            -v13._alias_strength(concept, item[0]),
                            -len(v14._norm(item[0])),
                            item[1]["x0"],
                        )
                    )
                    for alias, geom in geometries:
                        numeric = sorted(v14._numeric_word_candidates(row), key=lambda x: x["x0"])
                        numeric_after = [x for x in numeric if x["x0"] >= geom["x1"] - 1]
                        words = row["words"]
                        left = max(0, int(geom["first_word"]) - 6)
                        right = min(len(words), int(geom["last_word"]) + 19)
                        context_words = [word_record(x) for x in words[left:right]]
                        raw_after = [
                            word_record(x) for x in words[int(geom["last_word"]) + 1:right]
                            if numberish(str(x.get("text") or ""))
                        ]
                        evidence_rows.append({
                            "concept": concept,
                            "page": pno + 1,
                            "row_index": row_index,
                            "row_y": float(row["y"]),
                            "row_text": row["text"][:1200],
                            "alias": alias,
                            "alias_strength": v13._alias_strength(concept, alias),
                            "alias_x0": str(geom["x0"]),
                            "alias_x1": str(geom["x1"]),
                            "statement_role_event": role_event,
                            "role_is_group_eligible": bool(role_event and role_event.get("role") in ("GROUP", "DUAL_GROUP_PARENT")),
                            "unit": unit,
                            "unit_multiplier": str(mult) if mult is not None else None,
                            "unit_source_page": unit_page,
                            "numeric_candidates_all": [
                                {"raw": str(x.get("raw")), "value": str(x.get("value")), "x0": str(x.get("x0")), "x1": str(x.get("x1"))}
                                for x in numeric
                            ],
                            "numeric_candidates_after_alias": [
                                {"raw": str(x.get("raw")), "value": str(x.get("value")), "x0": str(x.get("x0")), "x1": str(x.get("x1"))}
                                for x in numeric_after
                            ],
                            "numberish_raw_words_after_alias": raw_after,
                            "context_words": context_words,
                        })

    per_concept_counts = {
        concept: sum(1 for row in evidence_rows if row["concept"] == concept)
        for concept in missing_concepts
    }
    errors = [f"no alias geometry evidence for {concept}" for concept, count in per_concept_counts.items() if count == 0]
    report = {
        "gate": "S3G1J_V17_13_EXACT_FOUR_NO_RIGHT_AMOUNT_GEOMETRY",
        "diagnostic_only": True,
        "no_parser_change": True,
        "no_value_acceptance": True,
        "no_ocr": True,
        "accounting_tolerance_changed": False,
        "source_policy_changed": False,
        "announcement_id": aid,
        "source_code": version["source_code"],
        "report_family": version["report_family"],
        "economic_date": version["economic_date"],
        "canonical_title": version["canonical_title"],
        "canonical_source_url": version["canonical_source_url"],
        "source_sha256": digest,
        "source_bytes": len(raw),
        "page_count": expected.get("page_count"),
        "missing_concepts": missing_concepts,
        "upstream_concept_stage": expected.get("concept_stage"),
        "upstream_funnel": expected.get("funnel"),
        "evidence_row_count": len(evidence_rows),
        "per_concept_evidence_row_count": per_concept_counts,
        "evidence_rows": evidence_rows,
        "pass": not errors,
        "stage4_alpha_locked": True,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "announcement_id": aid,
        "missing_concepts": missing_concepts,
        "evidence_row_count": len(evidence_rows),
        "per_concept_evidence_row_count": per_concept_counts,
        "pass": report["pass"],
        "errors": errors,
    }, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
