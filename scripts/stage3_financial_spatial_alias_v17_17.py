#!/usr/bin/env python3
from __future__ import annotations

import re
from collections import Counter, defaultdict
from decimal import Decimal

import fitz

import stage3_financial_coordinate_fallback_v14 as v14
import stage3_financial_pdf_parser_v8 as v13
import stage3_financial_spatial_alias_v16 as spatial
import stage3_financial_spatial_alias_v16_3 as v166
import stage3_financial_spatial_alias_v16_7 as v167
import stage3_financial_spatial_alias_v17_15 as v1715
import stage3_financial_statement_blocks_v16_5 as blocks

CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
STRICT_EQUITY_LABEL = "股东权益总计"
YEAR_TOKEN_RE = re.compile(r"20\d{2}")
MONTH_DAY_TOKEN_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")
MAX_SPLIT_HEADER_X_DELTA = 35.0


def _norm(value: str) -> str:
    return v14._norm(value or "")


def _is_exact_strict_equity_row(row_text: str) -> bool:
    normalized = _norm(row_text)
    label = _norm(STRICT_EQUITY_LABEL)
    if not normalized.startswith(label):
        return False
    if any(token in normalized for token in (_norm("归属于"), _norm("少数股东"), _norm("负债和"), _norm("负债及"))):
        return False
    return True


def _token_geometries(row: dict, pattern: re.Pattern[str]) -> list[dict]:
    compact, char_map = v167._compact_word_map(row)
    out: list[dict] = []
    for match in pattern.finditer(compact):
        first_word = char_map[match.start()]
        last_word = char_map[match.end() - 1]
        words = row["words"]
        x0 = float(words[first_word]["x0"])
        x1 = float(words[last_word]["x1"])
        out.append({
            "text": match.group(0),
            "groups": list(match.groups()),
            "x0": x0,
            "x1": x1,
            "x_center": (x0 + x1) / 2,
        })
    return out


def _strict_two_row_header_on_page(
    page: fitz.Page,
    expected_economic_date: str,
    alias_x1: float,
) -> dict | None:
    expected = v166._canonical_economic_date(expected_economic_date)
    rows = sorted(v14._rows_from_words(page), key=lambda row: float(row["y"]))
    for index in range(len(rows) - 1):
        year_row = rows[index]
        md_row = rows[index + 1]
        year_compact = re.sub(r"\s+", "", str(year_row.get("text") or ""))
        md_compact = re.sub(r"\s+", "", str(md_row.get("text") or ""))
        if re.fullmatch(r"(?:20\d{2}年){3}", year_compact) is None:
            continue
        cleaned_md = (
            md_compact.replace("附注", "")
            .replace("(已重述)", "")
            .replace("（已重述）", "")
        )
        if re.fullmatch(r"(?:\d{1,2}月\d{1,2}日){3}", cleaned_md) is None:
            continue
        years = _token_geometries(year_row, YEAR_TOKEN_RE)
        month_days = _token_geometries(md_row, MONTH_DAY_TOKEN_RE)
        years = [row for row in years if row["x_center"] >= alias_x1 - 5.0]
        month_days = [row for row in month_days if row["x_center"] >= alias_x1 - 5.0]
        years.sort(key=lambda row: row["x_center"])
        month_days.sort(key=lambda row: row["x_center"])
        if len(years) != 3 or len(month_days) != 3:
            continue
        if any(
            abs(year["x_center"] - md["x_center"]) > MAX_SPLIT_HEADER_X_DELTA
            for year, md in zip(years, month_days)
        ):
            continue
        dates = []
        for year, md in zip(years, month_days):
            month, day = md["groups"]
            dates.append({
                "date": f"{int(year['text']):04d}-{int(month):02d}-{int(day):02d}",
                "x0": min(year["x0"], md["x0"]),
                "x1": max(year["x1"], md["x1"]),
                "x_center": (year["x_center"] + md["x_center"]) / 2,
                "year_row_y": float(year_row["y"]),
                "month_day_row_y": float(md_row["y"]),
            })
        expected_indexes = [idx for idx, row in enumerate(dates) if row["date"] == expected]
        if len(expected_indexes) != 1:
            continue
        return {
            "page": page.number + 1,
            "row_y": float(year_row["y"]),
            "row_text": f"{year_row['text']} || {md_row['text']}",
            "dates": dates,
            "expected_date": expected,
            "expected_column_index": expected_indexes[0],
            "structural_source": "V17_17_STRICT_THREE_COLUMN_TWO_ROW_YEAR_MONTH_DAY_HEADER",
            "year_row_text": str(year_row["text"])[:500],
            "month_day_row_text": str(md_row["text"])[:500],
            "x_alignment_tolerance": MAX_SPLIT_HEADER_X_DELTA,
        }
    return None


def _strict_two_row_column_evidence(
    doc: fitz.Document,
    candidate: dict,
    expected_economic_date: str,
) -> dict:
    current_page = int(candidate["page"])
    root_page = int((candidate.get("unit_evidence") or {}).get("root_page") or candidate["statement_anchor_page"])
    alias_x1 = float(candidate["alias_x1"])
    for page_1b in range(current_page, max(1, root_page) - 1, -1):
        header = _strict_two_row_header_on_page(
            doc[page_1b - 1], expected_economic_date, alias_x1
        )
        if header is None:
            continue
        return v1715._column_evidence_with_header(
            doc,
            candidate,
            header,
            "V17_17_STRICT_THREE_COLUMN_TWO_ROW_YEAR_MONTH_DAY_HEADER",
        )
    return {"pass": False, "reason": "no strict paired year/month-day header row"}


def _direct_column_evidence(
    doc: fitz.Document,
    candidate: dict,
    expected_economic_date: str,
) -> dict:
    direct = v1715._direct_column_evidence(doc, candidate, expected_economic_date)
    if direct.get("pass"):
        return direct
    split = _strict_two_row_column_evidence(doc, candidate, expected_economic_date)
    if split.get("pass"):
        split["prior_direct_failure"] = direct
        return split
    return {
        "pass": False,
        "reason": "direct and strict two-row header evidence both failed",
        "direct_failure": direct,
        "two_row_failure": split,
    }


def _collect_strict_same_row_equity_candidates(
    doc: fitz.Document,
    expected_economic_date: str,
) -> tuple[list[dict], dict]:
    events = blocks.formal_statement_events(doc)
    pages = v14._candidate_pages(doc)
    candidates: list[dict] = []
    funnel = Counter()

    for pno in pages:
        rows = sorted(v14._rows_from_words(doc[pno]), key=lambda row: float(row["y"]))
        for row in rows:
            if not _is_exact_strict_equity_row(str(row.get("text") or "")):
                continue
            funnel["exact_equity_total_rows"] += 1
            geometries = spatial._alias_geometries(row, STRICT_EQUITY_LABEL, "TOTAL_EQUITY")
            if not geometries:
                funnel["rows_without_alias_geometry"] += 1
                continue
            for geom in geometries:
                role_event = blocks.bind_alias_to_preceding_statement_event(
                    events, pno + 1, float(row["y"]), float(geom["x0"])
                )
                if role_event is None:
                    funnel["rows_without_formal_role"] += 1
                    continue
                if role_event.get("role") not in ("GROUP", "DUAL_GROUP_PARENT"):
                    funnel["rows_bound_parent"] += 1
                    continue
                unit, mult, unit_evidence = blocks.role_local_unit_context(
                    doc, events, role_event, pno + 1, float(row["y"])
                )
                if unit is None or mult is None:
                    funnel["rows_without_unit"] += 1
                    continue
                period_evidence = v166._statement_period_evidence(
                    doc, role_event, unit_evidence, pno + 1, expected_economic_date
                )
                if not period_evidence.get("matched"):
                    funnel["rows_without_frozen_period"] += 1
                    continue
                amounts = v167._amounts_after_alias(row, float(geom["x1"]))
                if len(amounts) < 2:
                    funnel["rows_without_two_amount_columns"] += 1
                    continue
                amount = amounts[0]
                value_cny = amount["value"] * mult
                if abs(value_cny) < Decimal("10000"):
                    funnel["economically_tiny_amount"] += 1
                    continue
                candidates.append({
                    "concept": "TOTAL_EQUITY",
                    "value": value_cny,
                    "raw_value": str(amount["value"]),
                    "unit": unit,
                    "unit_multiplier": mult,
                    "unit_evidence": unit_evidence,
                    "period_evidence": period_evidence,
                    "page": pno + 1,
                    "alias": STRICT_EQUITY_LABEL,
                    "alias_strength": v13._alias_strength("TOTAL_EQUITY", "股东权益合计") + 1,
                    "alias_x0": geom["x0"],
                    "alias_x1": geom["x1"],
                    "value_x": amount["x0"],
                    "statement_anchor_page": role_event["page"],
                    "statement_anchor_y": role_event["y"],
                    "statement_anchor_x": role_event["x_center"],
                    "statement_role": role_event["role"],
                    "statement_title": role_event["matched_title"],
                    "statement_title_line": role_event["line"],
                    "row_text": str(row.get("text") or "")[:800],
                    "strict_same_row_equity_total": True,
                    "strict_amount_columns": [
                        {"raw": str(item["raw"]), "value": item["value"], "x0": item["x0"]}
                        for item in amounts
                    ],
                })
                funnel["strict_same_row_candidates"] += 1
    return candidates, dict(sorted(funnel.items()))


def _serialize(candidate: dict) -> dict:
    out = v1715._serialize_candidate(candidate)
    out["strict_same_row_equity_total"] = bool(candidate.get("strict_same_row_equity_total"))
    if candidate.get("strict_same_row_equity_total"):
        out["strict_amount_columns"] = [
            {"raw": str(item["raw"]), "value": str(item["value"]), "x0": str(item["x0"])}
            for item in candidate.get("strict_amount_columns") or []
        ]
    return out


def diagnose_spatial_balance_sheet_v17_17(
    doc: fitz.Document,
    expected_economic_date: str,
) -> dict:
    existing, base_funnel = v166._collect_candidates_v16_6(doc, expected_economic_date)
    bridge, bridge_funnel = v1715._collect_adjacent_bridge_candidates(doc, expected_economic_date)
    strict_equity, strict_funnel = _collect_strict_same_row_equity_candidates(doc, expected_economic_date)

    merged: dict[str, list[dict]] = defaultdict(list)
    for concept in CONCEPTS:
        merged[concept].extend(existing.get(concept, []))
        merged[concept].extend(bridge.get(concept, []))
    merged["TOTAL_EQUITY"].extend(strict_equity)
    candidates = v1715._dedupe_candidates(merged)
    chosen, identity = spatial._choose_spatial_identity(candidates)

    counts = {concept: len(candidates.get(concept, [])) for concept in CONCEPTS}
    strict_counts = {
        concept: sum(bool(row.get("strict_same_row_equity_total")) for row in candidates.get(concept, []))
        for concept in CONCEPTS
    }
    if chosen is None:
        return {
            "expected_economic_date": v166._canonical_economic_date(expected_economic_date),
            "base_funnel": base_funnel,
            "bridge_funnel": bridge_funnel,
            "strict_equity_funnel": strict_funnel,
            "candidate_counts": counts,
            "strict_candidate_counts": strict_counts,
            "identity_recovered_before_column_gate": False,
            "recovered": False,
            "identity": None,
            "column_role_gate": {"pass": False, "reason": "no A=L+E identity after strict total-equity extension"},
            "selected": {},
        }

    direct = {
        concept: _direct_column_evidence(doc, candidate, expected_economic_date)
        for concept, candidate in chosen.items()
    }
    evidence = dict(direct)
    for concept, candidate in chosen.items():
        if direct[concept].get("pass"):
            continue
        sibling = v1715._trusted_sibling_evidence(doc, concept, candidate, chosen, direct)
        if sibling is not None:
            evidence[concept] = sibling
    all_pass = all(bool((evidence.get(concept) or {}).get("pass")) for concept in CONCEPTS)
    return {
        "expected_economic_date": v166._canonical_economic_date(expected_economic_date),
        "base_funnel": base_funnel,
        "bridge_funnel": bridge_funnel,
        "strict_equity_funnel": strict_funnel,
        "candidate_counts": counts,
        "strict_candidate_counts": strict_counts,
        "identity_recovered_before_column_gate": True,
        "recovered": bool(all_pass),
        "identity": identity if all_pass else None,
        "column_role_gate": {
            "pass": all_pass,
            "concepts": evidence,
            "policy": (
                "V17.15 preserved; exact GROUP row label 股东权益总计 only; same-row amount; "
                "direct or strict three-column paired year/month-day frozen-date header; "
                "A=L+E tolerance 0.005"
            ),
        },
        "selected": {
            concept: _serialize(candidate)
            for concept, candidate in (chosen.items() if all_pass else [])
        },
    }
