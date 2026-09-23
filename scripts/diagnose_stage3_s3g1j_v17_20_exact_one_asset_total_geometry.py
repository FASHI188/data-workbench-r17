#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import fitz
import requests

import diagnose_stage3_s3g1j_v17_11_remaining as legacy
import stage3_financial_coordinate_fallback_v14 as v14
from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard
import stage3_financial_spatial_alias_v17_17 as v17

TARGET_ANNOUNCEMENT_ID = "1219311356"
TARGET_SOURCE_CODE = "600372"
TARGET_ECONOMIC_DATE = "2023-12-31"
EXPECTED_V17_19_CATEGORY = "CANDIDATES_NO_VALID_IDENTITY"
ASSET_LABELS = ("流动资产合计", "非流动资产合计", "资产总计", "资产合计")
NUMBER_RE = re.compile(r"(?<![\d.])-?\(?\d[\d,]*(?:\.\d+)?\)?")


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _word_view(row: dict) -> list[dict]:
    return [
        {
            "text": str(word.get("text") or ""),
            "x0": str(word.get("x0")),
            "x1": str(word.get("x1")),
            "y0": str(word.get("y0")),
            "y1": str(word.get("y1")),
        }
        for word in row.get("words") or []
    ]


def _amounts(row: dict) -> list[dict]:
    out: list[dict] = []
    for match in NUMBER_RE.finditer(str(row.get("text") or "")):
        raw = match.group(0)
        if len(re.sub(r"\D", "", raw)) < 4:
            continue
        out.append({"raw": raw, "start": match.start(), "end": match.end()})
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", required=True)
    parser.add_argument("--v17-11-acceptance", required=True)
    parser.add_argument("--v17-19-diagnostic", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    accepted = json.loads(Path(args.v17_11_acceptance).read_text(encoding="utf-8"))
    source_rows = {str(row["announcement_id"]): row for row in accepted.get("remaining") or []}
    if not accepted.get("pass") or len(source_rows) != 82:
        raise ValueError("not the accepted V17.11 exact-82 source state")
    source = source_rows.get(TARGET_ANNOUNCEMENT_ID)
    if source is None:
        raise ValueError("target missing from accepted source state")

    prior = json.loads(Path(args.v17_19_diagnostic).read_text(encoding="utf-8"))
    if not prior.get("pass") or prior.get("announcement_id") != TARGET_ANNOUNCEMENT_ID:
        raise ValueError("not the accepted V17.19 target diagnostic")
    if prior.get("v17_18_category") != EXPECTED_V17_19_CATEGORY:
        raise ValueError("target V17.18 category changed")
    if prior.get("any_combination_within_0_005") is not False:
        raise ValueError("V17.19 no longer proves existing candidates invalid")

    versions = [
        row
        for row in legacy._read_rows(Path(args.versions))
        if row["canonical_announcement_id"] == TARGET_ANNOUNCEMENT_ID
    ]
    if len(versions) != 1:
        raise ValueError(f"expected one target version row, got {len(versions)}")
    version = versions[0]
    if version["source_code"] != TARGET_SOURCE_CODE or version["economic_date"] != TARGET_ECONOMIC_DATE:
        raise ValueError("target frozen identity changed")

    session = requests.Session()
    raw = legacy._download(session, version["canonical_source_url"])
    digest = hashlib.sha256(raw).hexdigest()
    if digest != source["sha256"] or digest != prior["source_sha256"]:
        raise ValueError("target source SHA changed")

    matches: list[dict] = []
    role_events: list[dict] = []
    with fitz.open(stream=raw, filetype="pdf") as doc:
        with _mupdf_diagnostic_guard():
            role_events = v14._statement_events(doc)
            group_events = [
                event
                for event in role_events
                if event.get("role") == "GROUP" and int(event.get("page") or 0) in {82, 83}
            ]
            if not group_events:
                raise ValueError("no formal GROUP asset-balance-sheet event on pages 82-83")

            for page_1b in (82, 83):
                page = doc[page_1b - 1]
                rows = sorted(v14._rows_from_words(page), key=lambda row: float(row["y"]))
                for index, row in enumerate(rows):
                    compact = _compact(str(row.get("text") or ""))
                    labels = [label for label in ASSET_LABELS if label in compact]
                    if not labels:
                        continue
                    neighborhood: list[dict] = []
                    for neighbor_index in range(max(0, index - 3), min(len(rows), index + 4)):
                        neighbor = rows[neighbor_index]
                        neighborhood.append(
                            {
                                "offset": neighbor_index - index,
                                "y": str(neighbor.get("y")),
                                "y_delta": str(float(neighbor.get("y")) - float(row.get("y"))),
                                "text": str(neighbor.get("text") or "")[:1000],
                                "compact_text": _compact(str(neighbor.get("text") or ""))[:1000],
                                "amount_tokens": _amounts(neighbor),
                                "words": _word_view(neighbor),
                            }
                        )
                    matches.append(
                        {
                            "page": page_1b,
                            "row_index": index,
                            "row_y": str(row.get("y")),
                            "row_text": str(row.get("text") or "")[:1000],
                            "compact_row_text": compact[:1000],
                            "matched_labels": labels,
                            "same_row_amount_tokens": _amounts(row),
                            "same_row_words": _word_view(row),
                            "neighborhood": neighborhood,
                        }
                    )

    exact_total_rows = [
        row
        for row in matches
        if "资产总计" in row["matched_labels"]
        and "流动资产合计" not in row["compact_row_text"]
        and "非流动资产合计" not in row["compact_row_text"]
    ]
    if len(exact_total_rows) != 1:
        raise ValueError(f"expected one exact 资产总计 row, got {len(exact_total_rows)}")

    report = {
        "gate": "S3G1J_V17_20_EXACT_ONE_ASSET_TOTAL_GEOMETRY_DIAGNOSTIC",
        "pass": True,
        "diagnostic_only": True,
        "no_parser_change": True,
        "no_ocr": True,
        "announcement_id": TARGET_ANNOUNCEMENT_ID,
        "source_code": TARGET_SOURCE_CODE,
        "economic_date": TARGET_ECONOMIC_DATE,
        "canonical_title": version["canonical_title"],
        "canonical_source_url": version["canonical_source_url"],
        "source_sha256": digest,
        "source_bytes": len(raw),
        "v17_19_artifact_source_sha256": prior["source_sha256"],
        "formal_group_events_pages_82_83": [
            event for event in role_events if event.get("role") == "GROUP" and int(event.get("page") or 0) in {82, 83}
        ],
        "asset_label_row_count": len(matches),
        "asset_label_rows": matches,
        "exact_asset_total_row_count": len(exact_total_rows),
        "exact_asset_total_row": exact_total_rows[0],
        "same_row_amount_count": len(exact_total_rows[0]["same_row_amount_tokens"]),
        "neighbor_amount_rows": [
            row
            for row in exact_total_rows[0]["neighborhood"]
            if row["offset"] != 0 and row["amount_tokens"]
        ],
        "accounting_tolerance": "0.005",
        "accounting_tolerance_changed": False,
        "global_row_tolerance_changed": False,
        "e_equals_a_minus_l_inference": False,
        "source_policy_changed": False,
        "stage4_alpha_locked": True,
        "errors": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "announcement_id": TARGET_ANNOUNCEMENT_ID,
                "exact_asset_total_row": exact_total_rows[0]["row_text"],
                "same_row_amount_count": report["same_row_amount_count"],
                "neighbor_amount_rows": [
                    {key: row[key] for key in ("offset", "y_delta", "text", "amount_tokens")}
                    for row in report["neighbor_amount_rows"]
                ],
                "pass": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
