#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import fitz
import requests

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v8 as v13

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "config/stage3_s3g1j_v10_diagnostic_samples.json"
OUT = ROOT / "data/stage3_source_probe_v14/s3g1j_coordinate_rows_v14.json"

# These are the exact V13 acceptance residuals with an unchanged, complete
# same-moment source. NO_FULL_AUTHORITY_SAME_MOMENT cases are intentionally
# excluded: a later full report must not be backfilled into an earlier body-only
# point-in-time event.
RESIDUAL_IDS = {
    "1203373899", "1202637566", "1201392942", "1202600091", "1202260810",
    "1201734718", "1202805050", "1201726564", "1209868800", "1212651259",
    "1206728992", "1206660047", "1216700376", "1219442543", "1225037867",
    "1221090309", "1217635500", "1223385260", "1223364547", "1214924252",
}

TRIGGER_TERMS = (
    "资产总计", "资产合计", "总资产",
    "负债合计",
    "所有者权益合计", "股东权益合计", "权益合计",
    "Total assets", "Total of assets",
    "Total liabilities", "Total of liabilities",
    "Total equity", "Total of owner's equity", "Total shareholders' equity",
)
MAX_PAGE_SPAN = 9
MAX_X_SPREAD = Decimal("120")
IDENTITY_TOLERANCE = Decimal("0.005")
Y_TOLERANCE = 2.8


def _download(session: requests.Session, sample: dict) -> bytes:
    response = session.get(
        sample["url"],
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V14-coordinate-diagnostic",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=90,
    )
    response.raise_for_status()
    raw = response.content
    actual = hashlib.sha256(raw).hexdigest()
    if actual != sample["sha256"]:
        raise AssertionError(
            f"SHA mismatch {sample['announcement_id']} expected={sample['sha256']} actual={actual}"
        )
    return raw


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _rows_from_words(page: fitz.Page) -> list[dict]:
    words = page.get_text("words", sort=True) or []
    items = []
    for w in words:
        if len(w) < 5:
            continue
        x0, y0, x1, y1, text = float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])
        if not text.strip():
            continue
        items.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": text})
    items.sort(key=lambda z: (((z["y0"] + z["y1"]) / 2), z["x0"]))

    rows: list[list[dict]] = []
    centers: list[float] = []
    for item in items:
        cy = (item["y0"] + item["y1"]) / 2
        best = None
        best_dist = None
        # only the last few rows can overlap in y after sorting
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
        text = " ".join(z["text"] for z in row)
        out.append({"row_index": idx, "y": centers[idx], "text": text, "words": row})
    return out


def _numeric_word_candidates(row: dict) -> list[dict]:
    out = []
    words = row["words"]
    for idx, w in enumerate(words):
        token = w["text"].strip()
        # PDF extraction occasionally separates a leading '(' or trailing ')'.
        variants = [token]
        if idx > 0 and words[idx - 1]["text"].strip() == "(":
            variants.append("(" + token)
        if idx + 1 < len(words) and words[idx + 1]["text"].strip() == ")":
            variants.append(token + ")")
        if idx > 0 and idx + 1 < len(words) and words[idx - 1]["text"].strip() == "(" and words[idx + 1]["text"].strip() == ")":
            variants.append("(" + token + ")")
        value = None
        used = None
        for candidate in variants:
            if not base.NUMBER_RE.fullmatch(candidate):
                continue
            value = base.parse_num(candidate)
            if value is not None:
                used = candidate
                break
        if value is None:
            continue
        out.append(
            {
                "raw": used,
                "value": value,
                "x0": Decimal(str(w["x0"])),
                "x1": Decimal(str(w["x1"])),
            }
        )
    return out


def _row_contains_alias(row_text: str, alias: str, concept: str) -> bool:
    if not base.semantic_row_match(row_text, alias, concept):
        return False
    return _norm(alias) in _norm(row_text)


def _collect_coordinate_candidates(doc: fitz.Document, candidate_pages: list[int]) -> dict[str, list[dict]]:
    concepts = {
        "TOTAL_ASSETS": base.TIER1_ALIASES.get("TOTAL_ASSETS") or [],
        "TOTAL_LIABILITIES": base.TIER2_ALIASES.get("TOTAL_LIABILITIES") or [],
        "TOTAL_EQUITY": base.TIER2_ALIASES.get("TOTAL_EQUITY") or [],
    }
    out: dict[str, list[dict]] = defaultdict(list)

    for pno in candidate_pages:
        rows = _rows_from_words(doc[pno])
        unit, mult = base.page_unit_context(doc, pno)
        if unit is None or mult is None:
            continue
        for ri, row in enumerate(rows):
            nums = _numeric_word_candidates(row)
            if not nums:
                continue
            for concept, aliases in concepts.items():
                matched_aliases = [a for a in aliases if _row_contains_alias(row["text"], a, concept)]
                if not matched_aliases:
                    continue
                # Prefer the most specific textual alias on this row, but keep
                # every numeric column. A/L/E column alignment is decided later.
                alias = sorted(matched_aliases, key=lambda a: (-len(_norm(a)), -v13._alias_strength(concept, a)))[0]
                for num in nums:
                    # note numbers / row indices are normally tiny and far left;
                    # retain them only if they are economically plausible. The
                    # identity/column gate remains the actual arbiter.
                    value_cny = num["value"] * mult
                    if abs(value_cny) < Decimal("10000"):
                        continue
                    out[concept].append(
                        {
                            "concept": concept,
                            "value": value_cny,
                            "raw_value": str(num["value"]),
                            "unit": unit,
                            "page": pno + 1,
                            "row_index": ri,
                            "y": Decimal(str(row["y"])),
                            "x": num["x0"],
                            "alias": alias,
                            "alias_strength": v13._alias_strength(concept, alias),
                            "row_text": row["text"][:500],
                        }
                    )

    # Deduplicate identical value/page/x observations from overlapping aliases.
    for concept in list(out):
        best = {}
        for c in out[concept]:
            key = (str(c["value"]), c["page"], str(c["x"]))
            old = best.get(key)
            if old is None or c["alias_strength"] > old["alias_strength"]:
                best[key] = c
        out[concept] = list(best.values())
    return out


def _choose_coordinate_identity(candidates: dict[str, list[dict]]) -> tuple[dict | None, dict | None]:
    valid = []
    for a in candidates.get("TOTAL_ASSETS", []):
        for l in candidates.get("TOTAL_LIABILITIES", []):
            for e in candidates.get("TOTAL_EQUITY", []):
                page_span = max(a["page"], l["page"], e["page"]) - min(a["page"], l["page"], e["page"])
                if page_span > MAX_PAGE_SPAN:
                    continue
                x_spread = max(a["x"], l["x"], e["x"]) - min(a["x"], l["x"], e["x"])
                if x_spread > MAX_X_SPREAD:
                    continue
                rel = abs(a["value"] - (l["value"] + e["value"])) / max(
                    abs(a["value"]), abs(l["value"] + e["value"]), Decimal("1")
                )
                if rel > IDENTITY_TOLERANCE:
                    continue
                strength = a["alias_strength"] + l["alias_strength"] + e["alias_strength"]
                mean_x = (a["x"] + l["x"] + e["x"]) / Decimal("3")
                score = (rel, x_spread, page_span, -strength, mean_x)
                valid.append(
                    (
                        score,
                        {"TOTAL_ASSETS": a, "TOTAL_LIABILITIES": l, "TOTAL_EQUITY": e},
                        {
                            "identity_relative_error": str(rel),
                            "identity_residual_cny": str(abs(a["value"] - (l["value"] + e["value"]))),
                            "x_spread": str(x_spread),
                            "page_span": page_span,
                        },
                    )
                )
    if not valid:
        return None, None
    valid.sort(key=lambda x: x[0])
    _, chosen, meta = valid[0]
    return chosen, meta


def _candidate_pages(doc: fitz.Document) -> list[int]:
    pages: set[int] = set()
    for pno in range(doc.page_count):
        text = doc[pno].get_text("text") or ""
        compact = _norm(text)
        if any(_norm(term) in compact for term in TRIGGER_TERMS):
            for q in range(max(0, pno - 1), min(doc.page_count, pno + 2)):
                pages.add(q)
    return sorted(pages)


def main() -> int:
    spec = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    all_samples = {str(x["announcement_id"]): x for x in (spec.get("samples") or [])}
    missing = sorted(RESIDUAL_IDS - set(all_samples))
    if missing:
        raise ValueError(f"residual ids missing from frozen V10 sample: {missing}")
    samples = [all_samples[x] for x in sorted(RESIDUAL_IDS)]

    session = requests.Session()
    rows = []
    errors: list[str] = []
    recovery_counts = Counter()

    for sample in samples:
        row = {
            k: sample[k]
            for k in ("shard", "source_code", "report_family", "economic_date", "announcement_id", "url", "sha256", "era")
        }
        try:
            raw = _download(session, sample)
            current = v13.parse_pdf_bytes(raw)
            current_ok = bool(current.get("balance_sheet_block")) and not (current.get("validation_errors") or [])
            doc = fitz.open(stream=raw, filetype="pdf")
            pages = _candidate_pages(doc)
            candidates = _collect_coordinate_candidates(doc, pages)
            chosen, identity = _choose_coordinate_identity(candidates)
            recovered = chosen is not None and identity is not None
            if recovered:
                outcome = "COORDINATE_IDENTITY_RECOVERED"
            elif not pages:
                outcome = "NO_TEXT_TRIGGER_FOR_COORDINATE"
            elif not all(candidates.get(k) for k in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")):
                outcome = "MISSING_COORDINATE_CONCEPT_CANDIDATES"
            else:
                outcome = "COORDINATE_CANDIDATES_NO_IDENTITY"
            recovery_counts[outcome] += 1
            row.update(
                {
                    "current_v13_recovered": current_ok,
                    "current_v13_validation_errors": current.get("validation_errors") or [],
                    "page_count": doc.page_count,
                    "candidate_page_count": len(pages),
                    "candidate_pages": [p + 1 for p in pages[:80]],
                    "candidate_counts": {k: len(candidates.get(k, [])) for k in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")},
                    "coordinate_recovered": recovered,
                    "coordinate_outcome": outcome,
                    "coordinate_identity": identity,
                    "coordinate_selected": {
                        k: {
                            "value": str(v["value"]),
                            "raw_value": v["raw_value"],
                            "unit": v["unit"],
                            "page": v["page"],
                            "x": str(v["x"]),
                            "alias": v["alias"],
                            "row_text": v["row_text"],
                        }
                        for k, v in (chosen or {}).items()
                    },
                }
            )
        except Exception as exc:
            row.update(
                {
                    "coordinate_recovered": False,
                    "coordinate_outcome": "DIAGNOSTIC_ERROR",
                    "diagnostic_error": f"{type(exc).__name__}: {exc}",
                }
            )
            recovery_counts["DIAGNOSTIC_ERROR"] += 1
            errors.append(f"{sample['announcement_id']}: {type(exc).__name__}: {exc}")
        rows.append(row)

    recovered = sum(bool(r.get("coordinate_recovered")) for r in rows)
    report = {
        "gate": "S3G1J_V14_COORDINATE_ROW_IDENTITY_DIAGNOSTIC",
        "diagnostic_pass": not errors,
        "sample_count": len(rows),
        "recovered_count": recovered,
        "recovery_rate": recovered / len(rows) if rows else None,
        "outcome_counts": dict(sorted(recovery_counts.items())),
        "policy": {
            "exact_v13_unchanged_source_residuals": True,
            "no_full_authority_cases_excluded": True,
            "original_pdf_sha_required": True,
            "coordinate_words_only_no_ocr": True,
            "identity_tolerance_unchanged": str(IDENTITY_TOLERANCE),
            "max_page_span": MAX_PAGE_SPAN,
            "max_x_spread_points": str(MAX_X_SPREAD),
            "diagnostic_only_not_production_parser": True,
        },
        "rows": rows,
        "errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
