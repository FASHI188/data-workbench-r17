#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import fitz
import requests

import stage3_financial_pdf_parser as base
import stage3_financial_pdf_parser_v5 as v8

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "config/stage3_s3g1j_v10_diagnostic_samples.json"
OUT_DIR = ROOT / "data/stage3_source_probe_v10"
OUT_PATH = OUT_DIR / "s3g1j_failure_root_cause_v10.json"

CN_RELAXED_UNIT_RE = re.compile(
    r"(?:货币|金额)?单位\s*(?:[：:]|为|均为)?\s*(?:人民币)?\s*(百万元|亿元|万元|千元|元)"
)
EN_UNIT_RE = re.compile(
    r"\b(?:unit|currency)\s*[:：]?\s*(RMB|CNY|yuan|RMB\s*million|RMB\s*thousand|thousand\s*RMB|million\s*RMB)\b",
    re.I,
)
EN_BALANCE_TITLE_RE = re.compile(
    r"\b(?:consolidated\s+balance\s+sheet|consolidated\s+statement\s+of\s+financial\s+position|balance\s+sheet)\b",
    re.I,
)
CN_EXTRA_TITLE_VARIANTS = (
    "合并及公司资产负债表",
    "合并公司资产负债表",
    "合并资产负债表及公司资产负债表",
)
CN_ASSET_TERMINALS = ("资产总计", "资产合计")
CN_LIABILITY_TERMINALS = ("负债合计",)
CN_EQUITY_TERMINALS = ("所有者权益合计", "股东权益合计", "权益合计")
EN_ASSET_RE = re.compile(r"\btotal\s+assets\b", re.I)
EN_LIABILITY_RE = re.compile(r"\btotal\s+liabilit(?:y|ies)\b", re.I)
EN_EQUITY_RE = re.compile(
    r"\b(?:total\s+(?:owners'?|shareholders'?|stockholders'?)\s+equity|total\s+equity)\b",
    re.I,
)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _page_signal(doc: fitz.Document, pno: int) -> dict:
    text = doc[pno].get_text("text") or ""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    compact = _compact(text)
    current_unit, _ = base.detect_unit(text)
    relaxed_unit = CN_RELAXED_UNIT_RE.search(text)
    english_unit = EN_UNIT_RE.search(text)
    current_title_lines = [line for line in lines if v8._balance_title_kind(line)]
    extra_cn_titles = [line for line in lines if any(x in _compact(line) for x in CN_EXTRA_TITLE_VARIANTS)]
    english_titles = [line for line in lines if EN_BALANCE_TITLE_RE.search(line)]
    cn_asset = any(x in compact for x in CN_ASSET_TERMINALS)
    cn_liability = any(x in compact for x in CN_LIABILITY_TERMINALS)
    cn_equity = any(x in compact for x in CN_EQUITY_TERMINALS)
    en_asset = bool(EN_ASSET_RE.search(text))
    en_liability = bool(EN_LIABILITY_RE.search(text))
    en_equity = bool(EN_EQUITY_RE.search(text))
    triad_hits = sum((cn_asset or en_asset, cn_liability or en_liability, cn_equity or en_equity))
    return {
        "page": pno + 1,
        "current_unit": current_unit,
        "relaxed_cn_unit": relaxed_unit.group(1) if relaxed_unit else None,
        "english_unit": english_unit.group(1) if english_unit else None,
        "current_title_lines": current_title_lines[:4],
        "extra_cn_title_lines": extra_cn_titles[:4],
        "english_title_lines": english_titles[:4],
        "cn_asset_terminal": cn_asset,
        "cn_liability_terminal": cn_liability,
        "cn_equity_terminal": cn_equity,
        "en_asset_terminal": en_asset,
        "en_liability_terminal": en_liability,
        "en_equity_terminal": en_equity,
        "triad_hits": triad_hits,
    }


def _nearest_terminal_pages(signals: list[dict], start_page: int) -> dict[str, int | None]:
    out: dict[str, int | None] = {"assets": None, "liabilities": None, "equity": None}
    for sig in signals:
        if sig["page"] < start_page:
            continue
        if sig["page"] > start_page + 12:
            break
        if out["assets"] is None and (sig["cn_asset_terminal"] or sig["en_asset_terminal"]):
            out["assets"] = sig["page"]
        if out["liabilities"] is None and (sig["cn_liability_terminal"] or sig["en_liability_terminal"]):
            out["liabilities"] = sig["page"]
        if out["equity"] is None and (sig["cn_equity_terminal"] or sig["en_equity_terminal"]):
            out["equity"] = sig["page"]
    return out


def _classify(signals: list[dict], starts: list[tuple[int, int]], parsed: dict) -> tuple[str, dict]:
    english_pages = [s["page"] for s in signals if s["english_title_lines"]]
    extra_cn_pages = [s["page"] for s in signals if s["extra_cn_title_lines"]]
    current_title_pages = [s["page"] for s in signals if s["current_title_lines"]]
    relaxed_only_unit_pages = [
        s["page"] for s in signals if s["relaxed_cn_unit"] and not s["current_unit"]
    ]
    structural_pages = [
        s["page"]
        for s in signals
        if s["triad_hits"] >= 2 and (s["current_unit"] or s["relaxed_cn_unit"] or s["english_unit"])
    ]

    details = {
        "current_start_pages": [{"page": p + 1, "priority": pri} for p, pri in starts],
        "current_title_pages": current_title_pages,
        "extra_cn_title_pages": extra_cn_pages,
        "english_title_pages": english_pages,
        "relaxed_only_unit_pages": relaxed_only_unit_pages,
        "structural_pages": structural_pages,
        "validation_errors": parsed.get("validation_errors") or [],
    }

    if parsed.get("balance_sheet_block"):
        return "UNEXPECTEDLY_RECOVERED", details
    if english_pages:
        return "ENGLISH_STATEMENT_UNSUPPORTED", details
    if extra_cn_pages:
        return "CN_TITLE_VARIANT_UNSUPPORTED", details

    starts_1b = [p + 1 for p, _ in starts]
    if starts_1b:
        for start in starts_1b:
            near_relaxed = [p for p in relaxed_only_unit_pages if start <= p <= start + 4]
            if near_relaxed:
                details["unit_pattern_start_page"] = start
                return "CN_UNIT_PATTERN_UNSUPPORTED", details
        for start in starts_1b:
            terminals = _nearest_terminal_pages(signals, start)
            if all(terminals.values()):
                details["terminal_pages"] = terminals
                max_page = max(int(x) for x in terminals.values() if x is not None)
                if max_page > start + 4:
                    details["span_pages"] = max_page - start + 1
                    return "BALANCE_BLOCK_SPAN_GT5", details
        return "ALIAS_OR_ROW_LAYOUT_WITH_START", details

    if structural_pages:
        return "STRUCTURAL_CANDIDATE_OUTSIDE_CURRENT_DISCOVERY", details
    return "NO_RELIABLE_STATEMENT_SIGNAL_OR_SCANNED_LAYOUT", details


def _download(session: requests.Session, sample: dict) -> bytes:
    resp = session.get(sample["url"], timeout=90)
    resp.raise_for_status()
    raw = resp.content
    actual = hashlib.sha256(raw).hexdigest()
    if actual != sample["sha256"]:
        raise ValueError(
            f"sha256 mismatch for {sample['announcement_id']}: expected={sample['sha256']} actual={actual}"
        )
    return raw


def main() -> int:
    spec = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    samples = spec.get("samples") or []
    if len(samples) != int(spec.get("sample_count") or -1):
        raise ValueError("sample_count contract mismatch")

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 S3G1J-V10-diagnostic"})
    results = []
    errors: list[str] = []

    for sample in samples:
        row = dict(sample)
        try:
            raw = _download(session, sample)
            doc = fitz.open(stream=raw, filetype="pdf")
            signals = [_page_signal(doc, pno) for pno in range(doc.page_count)]
            starts = v8._balance_sheet_start_pages(doc)
            parsed = v8.parse_pdf_bytes(raw)
            cause, details = _classify(signals, starts, parsed)
            interesting = [
                s
                for s in signals
                if s["current_title_lines"]
                or s["extra_cn_title_lines"]
                or s["english_title_lines"]
                or s["triad_hits"] >= 2
                or (s["relaxed_cn_unit"] and not s["current_unit"])
            ]
            row.update(
                {
                    "downloaded_bytes": len(raw),
                    "actual_page_count": doc.page_count,
                    "current_parser_balance_block": parsed.get("balance_sheet_block"),
                    "current_parser_validation_errors": parsed.get("validation_errors") or [],
                    "root_cause_class": cause,
                    "diagnostic": details,
                    "interesting_page_signals": interesting[:24],
                }
            )
        except Exception as exc:
            row["root_cause_class"] = "DIAGNOSTIC_ERROR"
            row["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{sample.get('announcement_id')}: {type(exc).__name__}: {exc}")
        results.append(row)

    cause_counts = Counter(r.get("root_cause_class") for r in results)
    family_counts = Counter((r.get("report_family"), r.get("root_cause_class")) for r in results)
    era_counts = Counter((r.get("era"), r.get("root_cause_class")) for r in results)
    report = {
        "gate": "S3G1J_V10_STRATIFIED_FAILURE_ROOT_CAUSE_DIAGNOSTIC",
        "pass": not errors,
        "authority": "Frozen official CNINFO PDFs from failed V8 representative-shard canonical documents",
        "source_v8_smoke_run": 30352320664,
        "sample_count": len(samples),
        "policy": {
            "diagnostic_only": True,
            "do_not_relax_accounting_identity_tolerance": True,
            "do_not_backfill_current_f10": True,
            "do_not_weaken_tie_or_provenance_gates": True,
            "sha256_required": True,
        },
        "root_cause_counts": dict(sorted(cause_counts.items())),
        "family_root_cause_counts": {
            f"{family}|{cause}": count
            for (family, cause), count in sorted(family_counts.items())
        },
        "era_root_cause_counts": {
            f"{era}|{cause}": count for (era, cause), count in sorted(era_counts.items())
        },
        "results": results,
        "errors": errors,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
