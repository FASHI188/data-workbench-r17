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

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16 as spatial
from stage3_financial_spatial_alias_v16_3 import diagnose_spatial_balance_sheet_v16_6

REPRESENTATIVE_IDS = {
    "1200948256", "1203240204", "1204557640", "1207547788", "1209728461",
    "1212671853", "1219442543", "1221090309", "1222949445", "1223096939",
}
DATE_RE = re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日")


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["canonical_announcement_id"]: row for row in csv.DictReader(handle)}


def download(session: requests.Session, url: str) -> tuple[bytes, str]:
    response = session.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V16.7-column-role-diagnostic",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    return raw, hashlib.sha256(raw).hexdigest()


def _compact_word_map(row: dict) -> tuple[str, list[int]]:
    chars: list[str] = []
    char_to_word: list[int] = []
    for idx, word in enumerate(row["words"]):
        text = re.sub(r"\s+", "", str(word["text"]))
        for ch in text:
            chars.append(ch)
            char_to_word.append(idx)
    return "".join(chars), char_to_word


def _date_geometries(row: dict) -> list[dict]:
    compact, cmap = _compact_word_map(row)
    out = []
    for m in DATE_RE.finditer(compact):
        first = cmap[m.start()]
        last = cmap[m.end() - 1]
        words = row["words"]
        x0 = float(words[first]["x0"])
        x1 = float(words[last]["x1"])
        date = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        out.append({
            "date": date,
            "x0": x0,
            "x1": x1,
            "x_center": (x0 + x1) / 2,
            "row_y": float(row["y"]),
            "row_text": row["text"][:500],
        })
    return out


def _find_alias_row(doc: fitz.Document, selected: dict) -> dict | None:
    pno = int(selected["page"]) - 1
    alias = str(selected["alias"])
    concept = None
    for candidate_concept in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"):
        if selected.get("concept") == candidate_concept:
            concept = candidate_concept
            break
    # selected dictionaries emitted by the public diagnostic omit concept; infer
    # from alias using spatial matching across all three semantic families.
    for row in v14._rows_from_words(doc[pno]):
        for candidate_concept in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"):
            geoms = spatial._alias_geometries(row, alias, candidate_concept)
            if not geoms:
                continue
            target_x = float(selected["alias_x0"])
            geom = min(geoms, key=lambda g: abs(float(g["x0"]) - target_x))
            if abs(float(geom["x0"]) - target_x) <= 3.0:
                nums = spatial._numeric_word_candidates(row)
                return {
                    "page": pno + 1,
                    "row_y": float(row["y"]),
                    "row_text": row["text"][:800],
                    "alias_x0": float(geom["x0"]),
                    "alias_x1": float(geom["x1"]),
                    "numeric_candidates": [
                        {"raw": str(n["raw"]), "value": str(n["value"]), "x0": float(n["x0"])}
                        for n in nums
                    ],
                }
    return None


def _statement_dates(doc: fitz.Document, selected: dict) -> list[dict]:
    unit = selected.get("unit_evidence") or {}
    root_page = int(unit.get("root_page") or selected["statement_anchor_page"])
    end_page = int(selected["page"])
    out = []
    for page_1b in range(max(1, root_page), min(doc.page_count, end_page) + 1):
        for row in v14._rows_from_words(doc[page_1b - 1]):
            for item in _date_geometries(row):
                item = dict(item)
                item["page"] = page_1b
                out.append(item)
    return out


def _nearest_date_metrics(selected: dict, dates: list[dict], expected: str) -> dict:
    value_x = float(selected["value_x"])
    expected_hits = [d for d in dates if d["date"] == expected]
    other_hits = [d for d in dates if d["date"] != expected]
    nearest_expected = min(expected_hits, key=lambda d: abs(d["x_center"] - value_x)) if expected_hits else None
    nearest_other = min(other_hits, key=lambda d: abs(d["x_center"] - value_x)) if other_hits else None
    expected_distance = abs(nearest_expected["x_center"] - value_x) if nearest_expected else None
    other_distance = abs(nearest_other["x_center"] - value_x) if nearest_other else None
    return {
        "value_x": value_x,
        "nearest_expected": nearest_expected,
        "nearest_other": nearest_other,
        "expected_distance": expected_distance,
        "other_distance": other_distance,
        "expected_is_spatially_nearer": (
            expected_distance is not None
            and (other_distance is None or expected_distance < other_distance)
        ),
        "margin_other_minus_expected": (
            other_distance - expected_distance
            if expected_distance is not None and other_distance is not None
            else None
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    versions = read_versions(Path(args.versions))
    missing = sorted(REPRESENTATIVE_IDS - set(versions))
    if missing:
        raise ValueError(f"missing representative ids: {missing}")

    session = requests.Session()
    rows = []
    errors = []
    for announcement_id in sorted(REPRESENTATIVE_IDS):
        v = versions[announcement_id]
        row = {
            "announcement_id": announcement_id,
            "source_code": v["source_code"],
            "economic_date": v["economic_date"],
            "canonical_title": v["canonical_title"],
        }
        try:
            raw, digest = download(session, v["canonical_source_url"])
            doc = fitz.open(stream=raw, filetype="pdf")
            parsed = diagnose_spatial_balance_sheet_v16_6(doc, v["economic_date"])
            if not parsed.get("recovered"):
                raise ValueError("V16.6 representative unexpectedly not recovered")
            concepts = {}
            for concept, selected in (parsed.get("selected") or {}).items():
                selected = dict(selected)
                selected["concept"] = concept
                dates = _statement_dates(doc, selected)
                concepts[concept] = {
                    "selected": selected,
                    "alias_row": _find_alias_row(doc, selected),
                    "statement_date_geometries": dates,
                    "column_role_metrics": _nearest_date_metrics(selected, dates, v["economic_date"]),
                }
            row.update({
                "download_sha256": digest,
                "concepts": concepts,
            })
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{announcement_id}: {row['error']}")
        rows.append(row)

    all_metrics = [
        c["column_role_metrics"]
        for r in rows for c in (r.get("concepts") or {}).values()
    ]
    report = {
        "gate": "S3G1J_V16_7_COLUMN_ROLE_GEOMETRY_DIAGNOSTIC",
        "diagnostic_pass": not errors and len(all_metrics) == 30,
        "sample_reports": len(rows),
        "sample_concepts": len(all_metrics),
        "expected_date_spatially_nearer_count": sum(bool(m["expected_is_spatially_nearer"]) for m in all_metrics),
        "metrics_with_expected_date_geometry": sum(m["expected_distance"] is not None for m in all_metrics),
        "policy": {
            "diagnostic_only": True,
            "does_not_change_selected_values": True,
            "purpose": "measure date-header x geometry before enforcing current-period column binding",
        },
        "rows": rows,
        "errors": errors,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["diagnostic_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
