#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import fitz
import requests

import diagnose_stage3_s3g1j_p0_v17_24 as source_tools
import stage3_financial_coordinate_fallback_v14 as rows_v14
import stage3_financial_pdf_parser_v19 as runtime
import stage3_financial_spatial_alias_v17_24 as spatial
import stage3_financial_statement_blocks_v16_5 as blocks


DOCUMENTS_GZIP_SHA256 = (
    "c2abe07baaa76efb80a30cfdd4e762ad07814f6aa795a92b9c0504f7944ab99a"
)
IDENTITY_TOLERANCE = Decimal("0.005")
MAX_SEQUENCE_ROWS = 3
MAX_ROW_GAP = Decimal("24")
MAX_EQUITY_ASSET_COLUMN_X0_DRIFT = Decimal("18")
CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
PARTIAL_EQUITY_LABEL = "所有者权益（或股东权益）合"
FULL_EQUITY_LABEL = "所有者权益（或股东权益）合计"

TARGETS: dict[str, dict[str, Any]] = {
    "1207621057": {
        "source_code": "603995",
        "economic_date": "2020-03-31",
        "economic_date_cn": "2020年3月31日",
        "source_url": "https://static.cninfo.com.cn/finalpage/2020-04-27/1207621057.PDF",
        "source_sha256": "b2aa4afa67e2b02010d5ba708d4e5fe02138623ff4bc48718c03029111a64568",
        "source_bytes": 477621,
        "group_anchor_page": 7,
        "asset_page": 8,
        "liability_page": 9,
        "equity_page": 10,
        "values": {
            "TOTAL_ASSETS": ["5470381065.66", "5189894320.88"],
            "TOTAL_LIABILITIES": ["2220814468.73", "2026096822.42"],
            "TOTAL_EQUITY": ["3249566596.93", "3163797498.46"],
        },
        "split_pattern": "LABEL_AND_AMOUNTS_THEN_CONTINUATION",
    },
    "1209825769": {
        "source_code": "603757",
        "economic_date": "2021-03-31",
        "economic_date_cn": "2021年3月31日",
        "source_url": "https://static.cninfo.com.cn/finalpage/2021-04-28/1209825769.PDF",
        "source_sha256": "0bd1da8bdac0aff2a3e99b83adc29e7b60e959c99dd29b8ab88cbda1344b441c",
        "source_bytes": 633887,
        "group_anchor_page": 8,
        "asset_page": 10,
        "liability_page": 10,
        "equity_page": 11,
        "values": {
            "TOTAL_ASSETS": ["1615699540.62", "1595907051.24"],
            "TOTAL_LIABILITIES": ["312375993.81", "334336378.51"],
            "TOTAL_EQUITY": ["1303323546.81", "1261570672.73"],
        },
        "split_pattern": "LABEL_THEN_AMOUNTS_THEN_CONTINUATION",
    },
}

ALIASES = {
    "TOTAL_ASSETS": "资产总计",
    "TOTAL_LIABILITIES": "负债合计",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: str) -> str:
    return (
        rows_v14._norm(value or "")
        .replace(":", "：")
        .replace("（", "(")
        .replace("）", ")")
    )


def row_x0(row: dict[str, Any]) -> float:
    words = list(row.get("words") or [])
    if not words:
        return 0.0
    return min(float(word["x0"]) for word in words)


def row_amounts(row: dict[str, Any]) -> list[dict[str, Any]]:
    return list(rows_v14._numeric_word_candidates(row))


def amount_pair(row: dict[str, Any], expected: list[str]) -> list[dict[str, Any]] | None:
    wanted = [Decimal(value) for value in expected]
    candidates = row_amounts(row)
    for start in range(0, max(0, len(candidates) - 1)):
        pair = candidates[start : start + 2]
        if [Decimal(str(item["value"])) for item in pair] == wanted:
            return pair
    return None


def amount_only_row(row: dict[str, Any], pair: list[dict[str, Any]]) -> bool:
    allowed = {normalize_text(str(item["raw"])) for item in pair}
    tokens = [normalize_text(str(word.get("text") or "")) for word in row.get("words") or []]
    tokens = [token for token in tokens if token not in {"", "(", ")"}]
    return bool(tokens) and all(token in allowed for token in tokens)


def find_exact_concept_row(
    rows: list[dict[str, Any]], concept: str, expected: list[str]
) -> dict[str, Any]:
    alias = ALIASES[concept]
    matches: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if normalize_text(alias) not in normalize_text(str(row.get("text") or "")):
            continue
        pair = amount_pair(row, expected)
        if pair is not None:
            matches.append({"index": index, "row": row, "pair": pair})
    if len(matches) != 1:
        raise ValueError(
            f"{concept} exact row count expected=1 actual={len(matches)}"
        )
    return matches[0]


def find_split_equity_sequence(
    rows: list[dict[str, Any]], expected: list[str]
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    partial = normalize_text(PARTIAL_EQUITY_LABEL)
    full = normalize_text(FULL_EQUITY_LABEL)
    for index, label_row in enumerate(rows):
        text = normalize_text(str(label_row.get("text") or ""))
        if partial not in text or full in text:
            continue
        end = min(len(rows), index + MAX_SEQUENCE_ROWS)
        window = rows[index:end]
        continuation_positions = [
            offset
            for offset, row in enumerate(window)
            if normalize_text(str(row.get("text") or "")) == "计"
        ]
        if len(continuation_positions) != 1:
            continue
        continuation_offset = continuation_positions[0]
        if continuation_offset == 0:
            continue
        amount_matches: list[tuple[int, list[dict[str, Any]]]] = []
        for offset, row in enumerate(window[: continuation_offset + 1]):
            pair = amount_pair(row, expected)
            if pair is not None:
                amount_matches.append((offset, pair))
        if len(amount_matches) != 1:
            continue
        amount_offset, pair = amount_matches[0]
        amount_row = window[amount_offset]
        if amount_offset > 0 and not amount_only_row(amount_row, pair):
            continue
        if amount_offset > continuation_offset:
            continue
        gaps = [
            Decimal(str(window[pos + 1]["y"])) - Decimal(str(window[pos]["y"]))
            for pos in range(continuation_offset)
        ]
        if not gaps or any(gap <= 0 or gap > MAX_ROW_GAP for gap in gaps):
            continue
        matches.append(
            {
                "label_index": index,
                "amount_index": index + amount_offset,
                "continuation_index": index + continuation_offset,
                "label_row": label_row,
                "amount_row": amount_row,
                "continuation_row": window[continuation_offset],
                "pair": pair,
                "row_gaps": [str(gap) for gap in gaps],
                "pattern": (
                    "LABEL_AND_AMOUNTS_THEN_CONTINUATION"
                    if amount_offset == 0
                    else "LABEL_THEN_AMOUNTS_THEN_CONTINUATION"
                ),
            }
        )
    if len(matches) != 1:
        raise ValueError(
            f"split equity sequence count expected=1 actual={len(matches)}"
        )
    return matches[0]


def validate_group_event(
    events: list[dict[str, Any]], page: int, row: dict[str, Any], anchor_page: int
) -> dict[str, Any]:
    event = blocks.bind_alias_to_preceding_statement_event(
        events, page, float(row["y"]), row_x0(row)
    )
    if not isinstance(event, dict):
        raise ValueError("split equity label has no preceding formal statement event")
    if event.get("role") != "GROUP":
        raise ValueError(f"split equity role must be GROUP actual={event.get('role')}")
    if int(event.get("page") or 0) != anchor_page:
        raise ValueError(
            f"GROUP anchor page expected={anchor_page} actual={event.get('page')}"
        )
    if "合并资产负债表" not in str(event.get("line") or ""):
        raise ValueError("GROUP anchor is not an explicit consolidated balance sheet title")
    return event


def validate_header_context(
    doc: fitz.Document, event: dict[str, Any], economic_date_cn: str
) -> dict[str, Any]:
    page = int(event["page"])
    rows = rows_v14._rows_from_words(doc[page - 1])
    event_y = Decimal(str(event.get("y") or 0))
    after = [
        row
        for row in rows
        if Decimal(str(row["y"])) >= event_y
        and Decimal(str(row["y"])) <= event_y + Decimal("110")
    ]
    date_rows = [
        row
        for row in after
        if normalize_text(economic_date_cn)
        in normalize_text(str(row.get("text") or ""))
    ]
    unit_rows = [
        row
        for row in after
        if "单位：元" in normalize_text(str(row.get("text") or ""))
        and "人民币" in normalize_text(str(row.get("text") or ""))
    ]
    if len(date_rows) != 1:
        raise ValueError(f"GROUP expected-date row count={len(date_rows)}")
    if len(unit_rows) != 1:
        raise ValueError(f"GROUP CNY unit row count={len(unit_rows)}")
    return {
        "date_row": str(date_rows[0]["text"]),
        "unit_row": str(unit_rows[0]["text"]),
    }


def validate_identity(
    assets: list[str], liabilities: list[str], equity: list[str]
) -> dict[str, Any]:
    if not (len(assets) == len(liabilities) == len(equity) == 2):
        raise ValueError("current and prior columns are both required")
    columns: list[dict[str, str]] = []
    for label, a_raw, l_raw, e_raw in zip(
        ("CURRENT", "PRIOR"), assets, liabilities, equity
    ):
        a = Decimal(a_raw)
        l = Decimal(l_raw)
        e = Decimal(e_raw)
        residual = a - l - e
        relative = abs(residual) / max(abs(a), Decimal("1"))
        if relative > IDENTITY_TOLERANCE:
            raise ValueError(
                f"{label} identity failed residual={residual} relative={relative}"
            )
        columns.append(
            {
                "column": label,
                "total_assets": str(a),
                "total_liabilities": str(l),
                "total_equity_explicit_pdf": str(e),
                "identity_residual_cny": str(residual),
                "identity_relative_error": str(relative),
            }
        )
    return {"tolerance": str(IDENTITY_TOLERANCE), "columns": columns}


def validate_equity_asset_alignment(
    asset_pair: list[dict[str, Any]], equity_pair: list[dict[str, Any]]
) -> dict[str, Any]:
    asset_x = [Decimal(str(item["x0"])) for item in asset_pair]
    equity_x = [Decimal(str(item["x0"])) for item in equity_pair]
    drift = [abs(a - e) for a, e in zip(asset_x, equity_x)]
    if any(value > MAX_EQUITY_ASSET_COLUMN_X0_DRIFT for value in drift):
        raise ValueError(f"equity/asset amount-column x0 drift={drift}")
    if not (asset_x[0] < asset_x[1] and equity_x[0] < equity_x[1]):
        raise ValueError("current/prior amount columns are not left-to-right ordered")
    return {
        "asset_x0": [str(value) for value in asset_x],
        "equity_x0": [str(value) for value in equity_x],
        "absolute_x0_drift": [str(value) for value in drift],
        "max_allowed_drift": str(MAX_EQUITY_ASSET_COLUMN_X0_DRIFT),
    }


def load_documents(path: Path) -> dict[str, dict[str, str]]:
    actual = sha256_file(path)
    if actual != DOCUMENTS_GZIP_SHA256:
        raise ValueError(
            f"V17.27 documents gzip SHA mismatch expected={DOCUMENTS_GZIP_SHA256} actual={actual}"
        )
    matched: dict[str, dict[str, str]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            aid = str(row.get("announcement_id") or "")
            if aid in TARGETS:
                if aid in matched:
                    raise ValueError(f"duplicate target document {aid}")
                matched[aid] = row
    if set(matched) != set(TARGETS):
        raise ValueError(f"missing target rows {sorted(set(TARGETS)-set(matched))}")
    return matched


def download(session: requests.Session, url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(1, 7):
        try:
            response = session.get(url, timeout=(30, 180))
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise ValueError(f"download is not PDF {url}")
            return response.content
        except Exception as exc:
            last = exc
            if attempt < 6:
                time.sleep(attempt * 5)
    assert last is not None
    raise last


def diagnose_target(
    document: dict[str, str], spec: dict[str, Any], session: requests.Session
) -> dict[str, Any]:
    aid = str(document.get("announcement_id") or "")
    if aid not in TARGETS:
        raise ValueError(f"non-target announcement {aid}")
    if document.get("document_status") != "ERROR":
        raise ValueError(f"target {aid} is no longer fail-closed")
    if document.get("numeric_observations") not in {"0", 0}:
        raise ValueError(f"target {aid} unexpectedly contains numeric observations")
    source = source_tools.source_evidence(document)
    for key, expected in (
        ("url", spec["source_url"]),
        ("sha256", spec["source_sha256"]),
        ("bytes", spec["source_bytes"]),
    ):
        if source[key] != expected:
            raise ValueError(
                f"target {aid} source {key} expected={expected!r} actual={source[key]!r}"
            )
    raw = download(session, source["url"])
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != spec["source_sha256"]:
        raise ValueError(
            f"target {aid} downloaded SHA expected={spec['source_sha256']} actual={actual_sha}"
        )
    if len(raw) != spec["source_bytes"]:
        raise ValueError(
            f"target {aid} downloaded bytes expected={spec['source_bytes']} actual={len(raw)}"
        )

    parsed = runtime.parse_pdf_bytes(raw, spec["economic_date"])
    if source_tools.is_recovered(parsed):
        raise ValueError(f"target {aid} is already recovered by formal V17.27 runtime")

    with fitz.open(stream=raw, filetype="pdf") as doc:
        events = blocks.formal_statement_events(doc)
        spatial_diagnostic = spatial.diagnose_spatial_balance_sheet_v17_24(
            doc, spec["economic_date"]
        )
        expected_counts = {
            "TOTAL_ASSETS": 3,
            "TOTAL_LIABILITIES": 1,
            "TOTAL_EQUITY": 0,
        }
        if spatial_diagnostic.get("candidate_counts") != expected_counts:
            raise ValueError(
                f"target {aid} existing candidate funnel changed "
                f"{spatial_diagnostic.get('candidate_counts')}"
            )
        if spatial_diagnostic.get("recovered") is not False:
            raise ValueError(f"target {aid} existing spatial parser unexpectedly recovered")

        asset_rows = rows_v14._rows_from_words(doc[spec["asset_page"] - 1])
        liability_rows = rows_v14._rows_from_words(doc[spec["liability_page"] - 1])
        equity_rows = rows_v14._rows_from_words(doc[spec["equity_page"] - 1])
        asset = find_exact_concept_row(
            asset_rows, "TOTAL_ASSETS", spec["values"]["TOTAL_ASSETS"]
        )
        liability = find_exact_concept_row(
            liability_rows, "TOTAL_LIABILITIES", spec["values"]["TOTAL_LIABILITIES"]
        )
        equity = find_split_equity_sequence(
            equity_rows, spec["values"]["TOTAL_EQUITY"]
        )
        if equity["pattern"] != spec["split_pattern"]:
            raise ValueError(
                f"target {aid} split pattern expected={spec['split_pattern']} "
                f"actual={equity['pattern']}"
            )
        event = validate_group_event(
            events,
            spec["equity_page"],
            equity["label_row"],
            spec["group_anchor_page"],
        )
        header = validate_header_context(doc, event, spec["economic_date_cn"])
        alignment = validate_equity_asset_alignment(asset["pair"], equity["pair"])
        identity = validate_identity(
            spec["values"]["TOTAL_ASSETS"],
            spec["values"]["TOTAL_LIABILITIES"],
            spec["values"]["TOTAL_EQUITY"],
        )

    return {
        "announcement_id": aid,
        "source_code": spec["source_code"],
        "economic_date": spec["economic_date"],
        "source_url": spec["source_url"],
        "source_sha256": actual_sha,
        "source_bytes": len(raw),
        "formal_runtime_generation": "V17.27",
        "formal_runtime_recovered": False,
        "existing_spatial_candidate_counts": spatial_diagnostic["candidate_counts"],
        "existing_spatial_recovered": False,
        "group_event": {
            key: event.get(key)
            for key in (
                "page",
                "y",
                "x0",
                "x1",
                "role",
                "continuation",
                "line",
                "matched_title",
            )
        },
        "header_context": header,
        "explicit_rows": {
            "TOTAL_ASSETS": {
                "page": spec["asset_page"],
                "text": asset["row"]["text"],
                "values": spec["values"]["TOTAL_ASSETS"],
            },
            "TOTAL_LIABILITIES": {
                "page": spec["liability_page"],
                "text": liability["row"]["text"],
                "values": spec["values"]["TOTAL_LIABILITIES"],
            },
            "TOTAL_EQUITY": {
                "page": spec["equity_page"],
                "label_text": equity["label_row"]["text"],
                "amount_text": equity["amount_row"]["text"],
                "continuation_text": equity["continuation_row"]["text"],
                "pattern": equity["pattern"],
                "values": spec["values"]["TOTAL_EQUITY"],
                "row_gaps": equity["row_gaps"],
            },
        },
        "column_alignment": alignment,
        "identity": identity,
        "equity_value_is_explicit_pdf_text": True,
        "equity_value_inferred_as_assets_minus_liabilities": False,
        "diagnostic_candidate_pass": True,
        "automatic_recovery_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    documents = load_documents(Path(args.documents))
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "data-workbench-r17-stage3-v17-28-split-equity-diagnostic/1.0",
            "Accept": "application/pdf,*/*;q=0.8",
        }
    )
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for aid in sorted(TARGETS):
        try:
            results.append(diagnose_target(documents[aid], TARGETS[aid], session))
        except Exception as exc:
            failures.append({"announcement_id": aid, "error": f"{type(exc).__name__}: {exc}"})
        print(f"S3G1J_V17_28_SPLIT_EQUITY_DIAGNOSTIC aid={aid}", flush=True)

    results.sort(key=lambda row: row["announcement_id"])
    passed = (
        not failures
        and [row["announcement_id"] for row in results] == sorted(TARGETS)
        and all(row["diagnostic_candidate_pass"] for row in results)
        and all(not row["automatic_recovery_authorized"] for row in results)
        and all(row["equity_value_is_explicit_pdf_text"] for row in results)
        and all(
            not row["equity_value_inferred_as_assets_minus_liabilities"]
            for row in results
        )
    )
    report = {
        "gate": "S3G1J_V17_28_SPLIT_EQUITY_DIAGNOSTIC_V1",
        "source_full_basis_run": 30806818977,
        "source_full_basis_head_sha": "fa77d30a2ccdd3664beab01fd7ff7b5d16761726",
        "source_full_basis_artifact_id": 8854139999,
        "source_full_basis_artifact": "stage3-s3g1j-v17-27-full-final",
        "source_full_basis_artifact_digest": "sha256:410e257d7a3ada353926970f806abc3e970e5638f55c1dec7b47c71c57777721",
        "source_documents_gzip_sha256": DOCUMENTS_GZIP_SHA256,
        "runtime_generation": "V17.27",
        "candidate_generation": "V17.28_DIAGNOSTIC_ONLY",
        "target_count": len(TARGETS),
        "processed_count": len(results),
        "source_sha_match_count": len(results),
        "target_announcement_ids": sorted(TARGETS),
        "results": results,
        "execution_failures": failures,
        "parser_changed": False,
        "runtime_authority_changed": False,
        "production_data_changed": False,
        "trained_model_changed": False,
        "source_policy_changed": False,
        "point_in_time_policy_changed": False,
        "issuer_gate_changed": False,
        "accounting_tolerance_changed": False,
        "ocr_enabled": False,
        "fuzzy_alias_matching_enabled": False,
        "equity_inference_enabled": False,
        "automatic_recovery_authorized": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_live_locked": True,
        "main_changed": False,
        "pass": passed,
        "errors": failures,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=2, default=str))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
