#!/usr/bin/env python3
from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal

import fitz

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v8 as v13

IDENTITY_TOLERANCE = Decimal("0.005")
MAX_PAGE_SPAN = 9
MAX_X_SPREAD = Decimal("120")
Y_TOLERANCE = 2.8
ROLE_LOOKBACK_PAGES = 9

TRIGGER_TERMS = (
    "资产总计", "资产合计", "总资产", "负债合计",
    "所有者权益合计", "股东权益合计", "权益合计",
    "Total assets", "Total of assets", "Total liabilities", "Total of liabilities",
    "Total equity", "Total of owner's equity", "Total shareholders' equity",
)
SPECIAL_SCOPE_PREFIXES = (
    "信托", "受托", "委托", "分部", "分行业", "分产品", "客户资金",
)
GROUP_HEADERS = ("本集团",)
PARENT_HEADERS = ("本公司", "本行", "母公司")


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _statement_role(line: str) -> str | None:
    raw = _norm(line).replace("（续）", "").replace("(续)", "").replace("-续", "")
    if not raw or "目录" in raw:
        return None
    dual = (
        "合并及母公司资产负债表",
        "合并及公司资产负债表",
        "合并及银行资产负债表",
        "合并资产负债表和母公司资产负债表",
        "合并资产负债表及母公司资产负债表",
        "合并资产负债表及资产负债表",
    )
    if any(token in raw for token in dual):
        return "DUAL_GROUP_PARENT"
    if "consolidatedbalancesheet" in raw or "consolidatedstatementoffinancialposition" in raw:
        return "GROUP"
    if "合并资产负债表" in raw:
        return "GROUP"
    if "母公司资产负债表" in raw:
        return "PARENT"
    if "公司资产负债表" in raw and "合并" not in raw:
        return "PARENT"
    if "银行资产负债表" in raw and "合并" not in raw:
        return "PARENT"
    if "balancesheetofparentcompany" in raw:
        return "PARENT"
    return None


def _statement_events(doc: fitz.Document) -> list[dict]:
    events: list[dict] = []
    for pno in range(doc.page_count):
        text = doc[pno].get_text("text") or ""
        for line_index, line in enumerate(text.splitlines()):
            role = _statement_role(line)
            if role:
                events.append({
                    "page": pno + 1,
                    "line_index": line_index,
                    "role": role,
                    "line": line.strip(),
                })
    return events


def _nearest_statement_event(events: list[dict], page_1b: int) -> dict | None:
    eligible = [
        e for e in events
        if e["page"] <= page_1b and e["page"] >= max(1, page_1b - ROLE_LOOKBACK_PAGES)
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda e: (e["page"], e["line_index"]))


def _rows_from_words(page: fitz.Page) -> list[dict]:
    words = page.get_text("words", sort=True) or []
    items = []
    for w in words:
        if len(w) < 5:
            continue
        x0, y0, x1, y1, text = float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])
        if text.strip():
            items.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": text})
    items.sort(key=lambda z: (((z["y0"] + z["y1"]) / 2), z["x0"]))

    rows: list[list[dict]] = []
    centers: list[float] = []
    for item in items:
        cy = (item["y0"] + item["y1"]) / 2
        best = None
        best_dist = None
        for idx in range(max(0, len(rows) - 4), len(rows)):
            dist = abs(cy - centers[idx])
            if dist <= Y_TOLERANCE and (best_dist is None or dist < best_dist):
                best = idx
                best_dist = dist
        if best is None:
            rows.append([item])
            centers.append(cy)
        else:
            rows[best].append(item)
            centers[best] = sum((z["y0"] + z["y1"]) / 2 for z in rows[best]) / len(rows[best])

    out = []
    for idx, row in enumerate(rows):
        row.sort(key=lambda z: z["x0"])
        out.append({
            "row_index": idx,
            "y": centers[idx],
            "text": " ".join(z["text"] for z in row),
            "words": row,
        })
    return out


def _numeric_word_candidates(row: dict) -> list[dict]:
    out = []
    words = row["words"]
    for idx, word in enumerate(words):
        token = word["text"].strip()
        variants = [token]
        if idx > 0 and words[idx - 1]["text"].strip() == "(":
            variants.append("(" + token)
        if idx + 1 < len(words) and words[idx + 1]["text"].strip() == ")":
            variants.append(token + ")")
        if idx > 0 and idx + 1 < len(words) and words[idx - 1]["text"].strip() == "(" and words[idx + 1]["text"].strip() == ")":
            variants.append("(" + token + ")")
        value = None
        raw = None
        for candidate in variants:
            if not base.NUMBER_RE.fullmatch(candidate):
                continue
            parsed = base.parse_num(candidate)
            if parsed is not None:
                value = parsed
                raw = candidate
                break
        if value is None:
            continue
        out.append({
            "raw": raw,
            "value": value,
            "x0": Decimal(str(word["x0"])),
        })
    return out


def _row_contains_alias(row_text: str, alias: str, concept: str) -> bool:
    return base.semantic_row_match(row_text, alias, concept) and _norm(alias) in _norm(row_text)


def _special_scope_reason(row_text: str, alias: str) -> str | None:
    text_n = _norm(row_text)
    alias_n = _norm(alias)
    pos = text_n.find(alias_n)
    prefix = text_n[:pos] if pos >= 0 else ""
    for token in SPECIAL_SCOPE_PREFIXES:
        if _norm(token) in prefix:
            return token
    return None


def _word_center_x(word: tuple) -> Decimal:
    return (Decimal(str(word[0])) + Decimal(str(word[2]))) / Decimal("2")


def _page_role_split(page: fitz.Page) -> dict | None:
    words = page.get_text("words", sort=True) or []
    group_x: list[Decimal] = []
    parent_x: list[Decimal] = []
    group_tokens = {_norm(x) for x in GROUP_HEADERS}
    parent_tokens = {_norm(x) for x in PARENT_HEADERS}
    for word in words:
        if len(word) < 5:
            continue
        token = _norm(str(word[4]).strip())
        if token in group_tokens:
            group_x.append(_word_center_x(word))
        if token in parent_tokens:
            parent_x.append(_word_center_x(word))
    if not group_x or not parent_x:
        return None
    gx = min(group_x)
    right = sorted(x for x in parent_x if x > gx)
    if not right:
        return None
    px = right[0]
    return {"group_header_x": gx, "parent_header_x": px, "split_x": (gx + px) / Decimal("2")}


def _candidate_pages(doc: fitz.Document) -> list[int]:
    pages: set[int] = set()
    for pno in range(doc.page_count):
        compact = _norm(doc[pno].get_text("text") or "")
        if any(_norm(term) in compact for term in TRIGGER_TERMS):
            for q in range(max(0, pno - 1), min(doc.page_count, pno + 2)):
                pages.add(q)
    return sorted(pages)


def _collect_candidates(doc: fitz.Document, pages: list[int], events: list[dict]) -> dict[str, list[dict]]:
    concepts = {
        "TOTAL_ASSETS": base.TIER1_ALIASES.get("TOTAL_ASSETS") or [],
        "TOTAL_LIABILITIES": base.TIER2_ALIASES.get("TOTAL_LIABILITIES") or [],
        "TOTAL_EQUITY": base.TIER2_ALIASES.get("TOTAL_EQUITY") or [],
    }
    out: dict[str, list[dict]] = defaultdict(list)

    for pno in pages:
        unit, mult = base.page_unit_context(doc, pno)
        if unit is None or mult is None:
            continue
        role_event = _nearest_statement_event(events, pno + 1)
        if role_event is None or role_event["role"] not in ("GROUP", "DUAL_GROUP_PARENT"):
            continue
        split = _page_role_split(doc[pno])
        rows = _rows_from_words(doc[pno])
        for row in rows:
            nums = _numeric_word_candidates(row)
            if not nums:
                continue
            for concept, aliases in concepts.items():
                matched = [a for a in aliases if _row_contains_alias(row["text"], a, concept)]
                if not matched:
                    continue
                alias = sorted(matched, key=lambda a: (-len(_norm(a)), -v13._alias_strength(concept, a)))[0]
                if _special_scope_reason(row["text"], alias):
                    continue

                row_xs = sorted({n["x0"] for n in nums})
                if not row_xs:
                    continue
                for num in nums:
                    value_cny = num["value"] * mult
                    if abs(value_cny) < Decimal("10000"):
                        continue
                    x = num["x0"]
                    group_current = False
                    if split:
                        group_side = x < split["split_x"]
                        group_xs = [z for z in row_xs if z < split["split_x"]]
                        group_current = bool(group_side and group_xs and abs(x - min(group_xs)) <= Decimal("3"))
                    else:
                        # On an explicitly GROUP or DUAL statement without a repeated
                        # role header on this continuation page, current group is the
                        # left-most numeric amount in the terminal row.
                        group_current = abs(x - min(row_xs)) <= Decimal("3")
                    if not group_current:
                        continue

                    out[concept].append({
                        "concept": concept,
                        "value": value_cny,
                        "raw_value": str(num["value"]),
                        "unit": unit,
                        "unit_multiplier": mult,
                        "page": pno + 1,
                        "x": x,
                        "alias": alias,
                        "alias_strength": v13._alias_strength(concept, alias),
                        "statement_anchor_page": role_event["page"],
                        "statement_role": role_event["role"],
                        "statement_title": role_event["line"],
                        "row_text": row["text"][:500],
                    })

    for concept in list(out):
        best: dict[tuple, dict] = {}
        for candidate in out[concept]:
            key = (
                str(candidate["value"]), candidate["page"], str(candidate["x"]),
                candidate["statement_anchor_page"],
            )
            current = best.get(key)
            if current is None or candidate["alias_strength"] > current["alias_strength"]:
                best[key] = candidate
        out[concept] = list(best.values())
    return out


def _choose_triplet(candidates: dict[str, list[dict]]) -> tuple[dict | None, dict | None]:
    valid = []
    for assets in candidates.get("TOTAL_ASSETS", []):
        for liabilities in candidates.get("TOTAL_LIABILITIES", []):
            for equity in candidates.get("TOTAL_EQUITY", []):
                anchor_pages = {
                    assets["statement_anchor_page"],
                    liabilities["statement_anchor_page"],
                    equity["statement_anchor_page"],
                }
                if len(anchor_pages) != 1:
                    continue
                page_span = max(assets["page"], liabilities["page"], equity["page"]) - min(
                    assets["page"], liabilities["page"], equity["page"]
                )
                if page_span > MAX_PAGE_SPAN:
                    continue
                x_spread = max(assets["x"], liabilities["x"], equity["x"]) - min(
                    assets["x"], liabilities["x"], equity["x"]
                )
                if x_spread > MAX_X_SPREAD:
                    continue
                rel = abs(assets["value"] - (liabilities["value"] + equity["value"])) / max(
                    abs(assets["value"]), abs(liabilities["value"] + equity["value"]), Decimal("1")
                )
                if rel > IDENTITY_TOLERANCE:
                    continue
                strength = assets["alias_strength"] + liabilities["alias_strength"] + equity["alias_strength"]
                anchor = next(iter(anchor_pages))
                score = (rel, x_spread, page_span, anchor, -strength)
                valid.append((score, {
                    "TOTAL_ASSETS": assets,
                    "TOTAL_LIABILITIES": liabilities,
                    "TOTAL_EQUITY": equity,
                }, {
                    "identity_relative_error": str(rel),
                    "identity_residual_cny": str(abs(assets["value"] - (liabilities["value"] + equity["value"]))),
                    "x_spread": str(x_spread),
                    "page_span": page_span,
                    "statement_anchor_page": anchor,
                    "statement_role": assets["statement_role"],
                    "statement_title": assets["statement_title"],
                }))
    if not valid:
        return None, None
    valid.sort(key=lambda x: x[0])
    _, chosen, meta = valid[0]
    return chosen, meta


def validated_coordinate_balance_sheet(doc: fitz.Document) -> tuple[dict[str, base.Observation] | None, dict | None]:
    events = _statement_events(doc)
    if not events:
        return None, None
    pages = _candidate_pages(doc)
    if not pages:
        return None, None
    candidates = _collect_candidates(doc, pages, events)
    chosen, identity = _choose_triplet(candidates)
    if chosen is None or identity is None:
        return None, None

    block: dict[str, base.Observation] = {}
    for concept in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"):
        c = chosen[concept]
        block[concept] = base.Observation(
            concept=concept,
            status="FOUND",
            raw_value=c["raw_value"],
            normalized_cny_value=str(c["value"]),
            unit=c["unit"],
            unit_multiplier=str(c["unit_multiplier"]),
            page=c["page"],
            matched_alias=c["alias"],
            extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V14_COORDINATE_ROLE_GATE",
            confidence="HIGH",
        )

    # Parent-attributable equity is not needed to establish A=L+E. Keep it
    # fail-closed here rather than borrowing a value from another role/table.
    block["EQUITY_ATTRIBUTABLE_TO_PARENT"] = base.Observation(
        concept="EQUITY_ATTRIBUTABLE_TO_PARENT",
        status="NOT_FOUND",
        extraction_scope="VALIDATED_BALANCE_SHEET_BLOCK_V14_COORDINATE_ROLE_GATE",
        confidence="NONE",
    )

    meta = {
        "start_page": identity["statement_anchor_page"],
        "unit": chosen["TOTAL_ASSETS"]["unit"],
        "arbitration": "V14_COORDINATE_GROUP_CURRENT_A_EQUALS_L_PLUS_E",
        "identity_tolerance": str(IDENTITY_TOLERANCE),
        "identity_relative_error": identity["identity_relative_error"],
        "identity_residual_cny": identity["identity_residual_cny"],
        "page_span": identity["page_span"],
        "x_spread": identity["x_spread"],
        "statement_role": identity["statement_role"],
        "statement_title": identity["statement_title"],
        "selected_pages": {k: chosen[k]["page"] for k in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")},
        "selected_aliases": {k: chosen[k]["alias"] for k in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")},
    }
    return block, meta
