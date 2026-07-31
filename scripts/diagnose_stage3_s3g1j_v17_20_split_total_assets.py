#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import fitz
import requests

import diagnose_stage3_s3g1j_v17_11_remaining as legacy
import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16_7 as v167
import stage3_financial_spatial_alias_v17_15 as v1715
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard

TARGET_ID = "1219311356"
TARGET_CODE = "600372"
TARGET_DATE = "2023-12-31"
EXACT_ALIAS = "资产总计"


def read_versions(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--v17-11-acceptance", required=True)
    ap.add_argument("--v17-19-report", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    accepted = json.loads(Path(args.v17_11_acceptance).read_text(encoding="utf-8"))
    source_map = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if not accepted.get("pass") or len(source_map) != 82 or TARGET_ID not in source_map:
        raise ValueError("accepted V17.11 exact-82 source state mismatch")

    prior = json.loads(Path(args.v17_19_report).read_text(encoding="utf-8"))
    if not prior.get("pass") or prior.get("announcement_id") != TARGET_ID:
        raise ValueError("V17.19 exact-one evidence mismatch")
    if prior.get("any_combination_within_0_005") is not False:
        raise ValueError("V17.19 no longer proves candidate identity failure")

    rows = [r for r in read_versions(Path(args.versions)) if r["canonical_announcement_id"] == TARGET_ID]
    if len(rows) != 1:
        raise ValueError(f"expected one frozen version row, got {len(rows)}")
    row = rows[0]
    if row["source_code"] != TARGET_CODE or row["economic_date"] != TARGET_DATE:
        raise ValueError("target frozen identity changed")

    raw = legacy._download(requests.Session(), row["canonical_source_url"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != source_map[TARGET_ID]["sha256"] or digest != prior["source_sha256"]:
        raise ValueError("target source SHA changed")

    matches: list[dict] = []
    with fitz.open(stream=raw, filetype="pdf") as doc:
        with _mupdf_diagnostic_guard():
            for pno in v14._candidate_pages(doc):
                page = doc[pno]
                rows_on_page = sorted(v14._rows_from_words(page), key=lambda item: float(item["y"]))
                for idx, text_row in enumerate(rows_on_page):
                    if v14._norm(str(text_row.get("text") or "")) != v14._norm(EXACT_ALIAS):
                        continue
                    alias_geoms = v1715.spatial._alias_geometries(text_row, EXACT_ALIAS, "TOTAL_ASSETS")
                    if len(alias_geoms) != 1:
                        raise ValueError(f"expected one exact alias geometry, got {len(alias_geoms)}")
                    geom = alias_geoms[0]
                    next_row = rows_on_page[idx + 1] if idx + 1 < len(rows_on_page) else None
                    next_amounts = []
                    next_numeric_only = False
                    delta = None
                    if next_row is not None:
                        delta = Decimal(str(float(next_row["y"]) - float(text_row["y"])))
                        next_numeric_only = v1715._strict_numeric_only_row(next_row)
                        next_amounts = v167._amounts_after_alias(next_row, float(geom["x1"]))
                    header = v167._find_header_column_evidence(
                        doc,
                        {
                            "page": pno + 1,
                            "statement_anchor_page": pno + 1,
                            "alias_x1": geom["x1"],
                            "value_x": next_amounts[0]["x0"] if next_amounts else 0,
                        },
                        TARGET_DATE,
                    )
                    matches.append({
                        "page": pno + 1,
                        "row_index": idx,
                        "alias_row_text": text_row["text"],
                        "alias_y": str(text_row["y"]),
                        "alias_x0": str(geom["x0"]),
                        "alias_x1": str(geom["x1"]),
                        "next_row_text": None if next_row is None else next_row["text"],
                        "next_row_y": None if next_row is None else str(next_row["y"]),
                        "y_delta": None if delta is None else str(delta),
                        "next_row_numeric_only": next_numeric_only,
                        "next_amounts": [
                            {"raw": str(a["raw"]), "value": str(a["value"]), "x0": str(a["x0"])}
                            for a in next_amounts
                        ],
                        "header": header,
                        "within_existing_v17_15_window": (
                            delta is not None and v1715.BRIDGE_MIN_Y_DELTA < delta <= v1715.BRIDGE_MAX_Y_DELTA
                        ),
                    })

    group_matches = [m for m in matches if m["page"] == 83]
    if len(group_matches) != 1:
        raise ValueError(f"expected one group exact asset-total row on page 83, got {len(group_matches)}")
    target = group_matches[0]
    if not target["next_row_numeric_only"] or len(target["next_amounts"]) != 2:
        raise ValueError("exact asset-total label is not followed by two strict numeric columns")
    if target["next_amounts"][0]["value"] != "73523417381.93":
        raise ValueError("unexpected frozen-date total-assets amount")
    header = target.get("header") or {}
    if header.get("expected_date") != TARGET_DATE or int(header.get("expected_column_index", -1)) != 0:
        raise ValueError("expected-date header evidence missing")

    report = {
        "gate": "S3G1J_V17_20_EXACT_ONE_SPLIT_TOTAL_ASSETS_GEOMETRY",
        "pass": True,
        "diagnostic_only": True,
        "no_parser_change": True,
        "no_ocr": True,
        "announcement_id": TARGET_ID,
        "source_code": TARGET_CODE,
        "economic_date": TARGET_DATE,
        "source_sha256": digest,
        "source_bytes": len(raw),
        "exact_alias": EXACT_ALIAS,
        "matches": matches,
        "target_group_match": target,
        "existing_v17_15_window": f"{v1715.BRIDGE_MIN_Y_DELTA} < delta <= {v1715.BRIDGE_MAX_Y_DELTA}",
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "global_row_tolerance_changed": False,
        "source_policy_changed": False,
        "stage4_alpha_locked": True,
        "errors": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "announcement_id": TARGET_ID,
        "page": target["page"],
        "y_delta": target["y_delta"],
        "within_existing_v17_15_window": target["within_existing_v17_15_window"],
        "amounts": target["next_amounts"],
        "pass": True,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
