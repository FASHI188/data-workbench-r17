#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
import requests

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_spatial_alias_v16 as spatial
import stage3_financial_statement_blocks_v16_3 as blocks_base
import stage3_financial_statement_blocks_v16_5 as blocks

ALL_MISSING = "MISSING_CANDIDATES_TOTAL_ASSETS_TOTAL_LIABILITIES_TOTAL_EQUITY"
EQUITY_MISSING = "MISSING_CANDIDATES_TOTAL_EQUITY"

ALIASES = {
    "TOTAL_ASSETS": ("资产总计", "资产合计", "总资产"),
    "TOTAL_LIABILITIES": ("负债合计", "负债总计", "负债总额"),
    "TOTAL_EQUITY": (
        "所有者权益（或股东权益）合计",
        "所有者权益合计",
        "股东权益合计",
        "股东权益总计",
        "所有者权益总计",
        "权益合计",
    ),
}
TITLE_TOKENS = (
    "资产负债表",
    "财务状况表",
    "合并及母公司",
    "合并及公司",
    "合并及银行",
    "合并",
    "母公司",
    "本集团",
    "本公司",
    "本行",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def serialize_event(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if event is None:
        return None
    keep = (
        "page",
        "y",
        "x0",
        "x1",
        "x_center",
        "role",
        "continuation",
        "line",
        "matched_title",
        "role_header_evidence",
    )
    return {key: event.get(key) for key in keep if key in event}


def title_like(text: str) -> bool:
    compact = v14._norm(text or "")
    if not compact or len(compact) > 120 or "目录" in compact:
        return False
    if "资产负债表" in compact or "财务状况表" in compact:
        return True
    return any(compact == v14._norm(token) for token in TITLE_TOKENS[5:])


def concept_aliases(text: str) -> dict[str, list[str]]:
    compact = v14._norm(text or "")
    out: dict[str, list[str]] = {}
    for concept, aliases in ALIASES.items():
        matched = [alias for alias in aliases if v14._norm(alias) in compact]
        if matched:
            out[concept] = matched
    return out


def row_span(row: dict[str, Any]) -> tuple[float, float]:
    words = row.get("words") or []
    if not words:
        return 0.0, 0.0
    return min(float(word["x0"]) for word in words), max(
        float(word["x1"]) for word in words
    )


def row_context(rows: list[dict[str, Any]], index: int) -> list[dict[str, Any]]:
    start = max(0, index - 6)
    end = min(len(rows), index + 4)
    return [
        {
            "relative_index": pos - index,
            "y": rows[pos]["y"],
            "text": rows[pos]["text"],
        }
        for pos in range(start, end)
    ]


def collect_layout(raw: bytes, source_row: dict[str, Any]) -> dict[str, Any]:
    with fitz.open(stream=raw, filetype="pdf") as doc:
        events = blocks.formal_statement_events(doc)
        candidate_pages = sorted(set(v14._candidate_pages(doc)))
        inspect_pages = set()
        for page_index in candidate_pages:
            inspect_pages.update(
                page
                for page in range(max(0, page_index - 2), min(doc.page_count, page_index + 3))
            )

        title_rows: list[dict[str, Any]] = []
        alias_rows: list[dict[str, Any]] = []
        for pno in sorted(inspect_pages):
            rows = sorted(v14._rows_from_words(doc[pno]), key=lambda row: float(row["y"]))
            for index, row in enumerate(rows):
                text = str(row.get("text") or "")
                x0, x1 = row_span(row)
                if title_like(text):
                    role, continuation = blocks_base.classify_formal_statement_title(text)
                    occurrences = blocks_base._title_occurrences(row)
                    title_rows.append(
                        {
                            "page": pno + 1,
                            "y": row["y"],
                            "x0": x0,
                            "x1": x1,
                            "text": text,
                            "normalized": v14._norm(text),
                            "string_role": role,
                            "string_continuation": continuation,
                            "occurrences": occurrences,
                            "statement_role_v14": v14._statement_role(text),
                            "context": row_context(rows, index),
                        }
                    )

                matched = concept_aliases(text)
                if not matched:
                    continue
                for concept, aliases in matched.items():
                    for alias in aliases:
                        geometries = spatial._alias_geometries(row, alias, concept)
                        if not geometries:
                            alias_rows.append(
                                {
                                    "concept": concept,
                                    "matched_alias": alias,
                                    "page": pno + 1,
                                    "y": row["y"],
                                    "text": text,
                                    "normalized": v14._norm(text),
                                    "geometry_count": 0,
                                    "geometries": [],
                                    "amounts_after_alias": [],
                                    "bound_event": None,
                                    "context": row_context(rows, index),
                                }
                            )
                            continue
                        for geometry in geometries:
                            amounts = [
                                {
                                    "raw": str(item["raw"]),
                                    "value": str(item["value"]),
                                    "x0": str(item["x0"]),
                                }
                                for item in v14._numeric_word_candidates(row)
                                if item["x0"] > geometry["x1"]
                            ]
                            event = blocks.bind_alias_to_preceding_statement_event(
                                events,
                                pno + 1,
                                float(row["y"]),
                                float(geometry["x0"]),
                            )
                            alias_rows.append(
                                {
                                    "concept": concept,
                                    "matched_alias": alias,
                                    "page": pno + 1,
                                    "y": row["y"],
                                    "text": text,
                                    "normalized": v14._norm(text),
                                    "geometry_count": len(geometries),
                                    "geometries": [
                                        {
                                            key: str(value)
                                            for key, value in geometry.items()
                                        }
                                    ],
                                    "amounts_after_alias": amounts,
                                    "bound_event": serialize_event(event),
                                    "context": row_context(rows, index),
                                }
                            )

        return {
            "page_count": doc.page_count,
            "candidate_pages_1b": [page + 1 for page in candidate_pages],
            "inspected_pages_1b": [page + 1 for page in sorted(inspect_pages)],
            "formal_events": [serialize_event(event) for event in events],
            "formal_event_role_counts": dict(
                sorted(Counter(str(event.get("role")) for event in events).items())
            ),
            "title_rows": title_rows,
            "alias_rows": alias_rows,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-report", required=True)
    parser.add_argument("--source-report-sha256", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    source_path = Path(args.source_report)
    actual_report_sha = sha256_file(source_path)
    if actual_report_sha != args.source_report_sha256:
        raise ValueError(
            f"source report SHA mismatch expected={args.source_report_sha256} "
            f"actual={actual_report_sha}"
        )
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("pass") is not True or source.get("errors"):
        raise ValueError("source P0 diagnostic is not accepted")
    if source.get("target_count") != 22 or source.get("processed_count") != 22:
        raise ValueError("source P0 diagnostic population changed")
    if source.get("v17_24_recovered_count") != 0:
        raise ValueError("source P0 diagnostic recovery set changed")
    expected_signatures = {
        ALL_MISSING: 11,
        EQUITY_MISSING: 11,
    }
    if source.get("signature_counts") != expected_signatures:
        raise ValueError(
            f"source diagnostic signatures changed {source.get('signature_counts')}"
        )

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "data-workbench-r17-stage3-layout-evidence/1.0",
            "Accept": "application/pdf,*/*;q=0.8",
        }
    )
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    source_sha_matches = 0
    for index, row in enumerate(source.get("results") or [], 1):
        aid = str(row["announcement_id"])
        try:
            url = str(row["canonical_source_url"])
            expected_sha = str(row["source_sha256"])
            expected_bytes = int(row["source_bytes"])
            raw = download(session, url)
            actual_sha = hashlib.sha256(raw).hexdigest()
            if actual_sha != expected_sha:
                raise ValueError(
                    f"source SHA changed expected={expected_sha} actual={actual_sha}"
                )
            if len(raw) != expected_bytes:
                raise ValueError(
                    f"source bytes changed expected={expected_bytes} actual={len(raw)}"
                )
            source_sha_matches += 1
            layout = collect_layout(raw, row)
            results.append(
                {
                    "announcement_id": aid,
                    "source_code": row["source_code"],
                    "report_family": row["report_family"],
                    "economic_date": row["economic_date"],
                    "diagnostic_signature": row["diagnostic_signature"],
                    "canonical_source_url": url,
                    "source_sha256": actual_sha,
                    "source_bytes": len(raw),
                    "layout": layout,
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "announcement_id": aid,
                    "source_code": str(row.get("source_code") or ""),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        print(f"S3G1J_P0_LAYOUT_EVIDENCE {index}/22 aid={aid}", flush=True)

    results.sort(key=lambda row: (row["diagnostic_signature"], row["economic_date"], row["announcement_id"]))
    signature_counts = Counter(row["diagnostic_signature"] for row in results)
    title_counts: dict[str, Counter] = {
        ALL_MISSING: Counter(),
        EQUITY_MISSING: Counter(),
    }
    title_role_counts: dict[str, Counter] = {
        ALL_MISSING: Counter(),
        EQUITY_MISSING: Counter(),
    }
    equity_row_counts: dict[str, Counter] = {
        ALL_MISSING: Counter(),
        EQUITY_MISSING: Counter(),
    }
    equity_bound_role_counts: dict[str, Counter] = {
        ALL_MISSING: Counter(),
        EQUITY_MISSING: Counter(),
    }
    for row in results:
        signature = row["diagnostic_signature"]
        layout = row["layout"]
        for title in layout["title_rows"]:
            title_counts[signature][title["normalized"]] += 1
            role = title.get("string_role") or title.get("statement_role_v14") or "UNRECOGNIZED"
            title_role_counts[signature][str(role)] += 1
        for alias in layout["alias_rows"]:
            if alias["concept"] != "TOTAL_EQUITY":
                continue
            equity_row_counts[signature][alias["normalized"]] += 1
            bound = alias.get("bound_event") or {}
            equity_bound_role_counts[signature][str(bound.get("role") or "NONE")] += 1

    report = {
        "gate": "S3G1J_P0_LAYOUT_EVIDENCE_V1",
        "source_diagnostic_run": 30687837626,
        "source_diagnostic_artifact": "stage3-s3g1j-p0-current-v17-24-diagnostic-v1",
        "source_diagnostic_artifact_digest": "sha256:b4e310fbb2b41d33d2c2c545589a6af53487dbfd1492dbb971d860fdcb4a14f0",
        "source_report_sha256": actual_report_sha,
        "target_count": 22,
        "processed_count": len(results),
        "source_sha_match_count": source_sha_matches,
        "signature_counts": dict(sorted(signature_counts.items())),
        "title_normalized_counts_by_signature": {
            key: dict(sorted(value.items()))
            for key, value in title_counts.items()
        },
        "title_role_counts_by_signature": {
            key: dict(sorted(value.items()))
            for key, value in title_role_counts.items()
        },
        "equity_row_normalized_counts_by_signature": {
            key: dict(sorted(value.items()))
            for key, value in equity_row_counts.items()
        },
        "equity_bound_role_counts_by_signature": {
            key: dict(sorted(value.items()))
            for key, value in equity_bound_role_counts.items()
        },
        "results": results,
        "execution_failures": failures,
        "parser_changed": False,
        "source_policy_changed": False,
        "accounting_tolerance_changed": False,
        "production_data_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_locked": True,
        "pass": (
            not failures
            and len(results) == 22
            and source_sha_matches == 22
            and dict(signature_counts) == expected_signatures
        ),
        "errors": failures,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "results"},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
