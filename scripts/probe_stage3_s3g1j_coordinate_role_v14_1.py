#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

import fitz
import requests

import probe_stage3_s3g1j_coordinate_rows_v14 as v14

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/stage3_source_probe_v14/s3g1j_coordinate_role_v14_1.json"

GROUP_TITLE_PATTERNS = (
    "合并资产负债表",
    "合并及母公司资产负债表",
    "合并及公司资产负债表",
    "合并及银行资产负债表",
    "合并资产负债表和母公司资产负债表",
    "合并资产负债表及母公司资产负债表",
    "合并资产负债表及资产负债表",
    "consolidatedbalancesheet",
    "consolidatedstatementoffinancialposition",
)
PARENT_ONLY_PATTERNS = (
    "母公司资产负债表",
    "公司资产负债表",
    "银行资产负债表",
    "balancesheetofparentcompany",
)
SPECIAL_SCOPE_PREFIXES = (
    "信托", "受托", "委托", "分部", "分行业", "分产品", "客户资金",
)
GROUP_HEADERS = ("本集团", "集团")
PARENT_HEADERS = ("本公司", "本行", "母公司", "公司")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _download(session: requests.Session, sample: dict) -> bytes:
    response = session.get(
        sample["url"],
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V14.1-role-diagnostic",
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


def _statement_context(doc: fitz.Document, pages_1b: list[int]) -> dict:
    pages = sorted({p for p in pages_1b if p >= 1})
    scan = set()
    for p in pages:
        for q in range(max(1, p - 2), min(doc.page_count, p + 1) + 1):
            scan.add(q)
    evidence = []
    group_title = False
    parent_only_title = False
    for p in sorted(scan):
        text = doc[p - 1].get_text("text") or ""
        n = _norm(text)
        group_here = [x for x in GROUP_TITLE_PATTERNS if _norm(x) in n]
        parent_here = [x for x in PARENT_ONLY_PATTERNS if _norm(x) in n]
        if group_here:
            group_title = True
        if parent_here and not group_here and "合并" not in n:
            parent_only_title = True
        if group_here or parent_here or "本集团" in text or "本公司" in text or "本行" in text:
            evidence.append(
                {
                    "page": p,
                    "group_title_hits": group_here,
                    "parent_title_hits": parent_here,
                    "has_group_header": any(x in text for x in GROUP_HEADERS),
                    "has_parent_header": any(x in text for x in PARENT_HEADERS),
                    "top_lines": [x.strip() for x in text.splitlines() if x.strip()][:45],
                }
            )
    return {
        "group_title": group_title,
        "parent_only_title": parent_only_title,
        "evidence": evidence[:12],
    }


def _word_center_x(word: tuple) -> Decimal:
    return (Decimal(str(word[0])) + Decimal(str(word[2]))) / Decimal("2")


def _page_role_split(page: fitz.Page) -> dict | None:
    words = page.get_text("words", sort=True) or []
    group_x = []
    parent_x = []
    for w in words:
        if len(w) < 5:
            continue
        text = str(w[4]).strip()
        n = _norm(text)
        if n in {_norm(x) for x in GROUP_HEADERS}:
            group_x.append(_word_center_x(w))
        if n in {_norm(x) for x in PARENT_HEADERS}:
            parent_x.append(_word_center_x(w))
    if not group_x or not parent_x:
        return None
    gx = min(group_x)
    # pick the first parent header to the right of the group header
    right = sorted(x for x in parent_x if x > gx)
    if not right:
        return None
    px = right[0]
    return {"group_header_x": gx, "parent_header_x": px, "split_x": (gx + px) / Decimal("2")}


def _numeric_xs_for_selected_row(doc: fitz.Document, selected: dict) -> list[Decimal]:
    pno = int(selected["page"]) - 1
    rows = v14._rows_from_words(doc[pno])
    target = None
    selected_text = _norm(selected["row_text"])
    for row in rows:
        if _norm(row["text"][:500]) == selected_text:
            target = row
            break
    if target is None:
        # fallback to alias + closest y-less text match
        alias_n = _norm(selected["alias"])
        matches = [row for row in rows if alias_n in _norm(row["text"])]
        if len(matches) == 1:
            target = matches[0]
    if target is None:
        return []
    return sorted({x["x0"] for x in v14._numeric_word_candidates(target)})


def _row_scope_ok(selected: dict) -> tuple[bool, str | None]:
    text_n = _norm(selected["row_text"])
    alias_n = _norm(selected["alias"])
    pos = text_n.find(alias_n)
    prefix = text_n[:pos] if pos >= 0 else ""
    for token in SPECIAL_SCOPE_PREFIXES:
        if _norm(token) in prefix:
            return False, f"SPECIAL_SCOPE_PREFIX:{token}"
    return True, None


def _column_role(doc: fitz.Document, selected: dict, context: dict) -> dict:
    pno = int(selected["page"]) - 1
    selected_x = Decimal(str(selected["x"]))
    row_xs = _numeric_xs_for_selected_row(doc, selected)
    split = _page_role_split(doc[pno])

    result = {
        "selected_x": str(selected_x),
        "row_numeric_xs": [str(x) for x in row_xs],
        "page_role_split": {
            k: str(v) for k, v in split.items()
        } if split else None,
    }

    if split:
        is_group = selected_x < split["split_x"]
        group_xs = [x for x in row_xs if x < split["split_x"]]
        is_current = bool(group_xs) and abs(selected_x - min(group_xs)) <= Decimal("3")
        result.update(
            {
                "role": "GROUP" if is_group else "PARENT",
                "period": "CURRENT" if is_group and is_current else ("PRIOR_OR_PARENT" if not is_current else "CURRENT"),
                "group_current": bool(is_group and is_current),
            }
        )
        return result

    # No dual-role header. A confirmed consolidated/group statement with two or
    # more numeric columns uses the left-most numeric amount as current period.
    if context.get("group_title"):
        if row_xs:
            is_current = abs(selected_x - min(row_xs)) <= Decimal("3")
            result.update(
                {
                    "role": "GROUP",
                    "period": "CURRENT" if is_current else "PRIOR",
                    "group_current": is_current,
                }
            )
            return result
        result.update({"role": "GROUP", "period": "UNKNOWN", "group_current": False})
        return result

    result.update({"role": "AMBIGUOUS", "period": "UNKNOWN", "group_current": False})
    return result


def _qualify(doc: fitz.Document, chosen: dict) -> tuple[bool, dict]:
    pages = [int(v["page"]) for v in chosen.values()]
    context = _statement_context(doc, pages)
    scope = {}
    columns = {}
    reasons = []

    if not context["group_title"]:
        reasons.append("NO_EXPLICIT_CONSOLIDATED_OR_GROUP_STATEMENT_TITLE")

    for concept, selected in chosen.items():
        ok, reason = _row_scope_ok(selected)
        scope[concept] = {"ok": ok, "reason": reason}
        if not ok:
            reasons.append(f"{concept}:{reason}")
        role = _column_role(doc, selected, context)
        columns[concept] = role
        if not role.get("group_current"):
            reasons.append(
                f"{concept}:NOT_GROUP_CURRENT role={role.get('role')} period={role.get('period')}"
            )

    return not reasons, {
        "context": context,
        "scope_checks": scope,
        "column_role_checks": columns,
        "reasons": reasons,
    }


def main() -> int:
    spec = json.loads(v14.SAMPLE_PATH.read_text(encoding="utf-8"))
    all_samples = {str(x["announcement_id"]): x for x in (spec.get("samples") or [])}
    session = requests.Session()
    rows = []
    errors = []
    counts = Counter()

    for aid in sorted(v14.RESIDUAL_IDS):
        sample = all_samples[aid]
        row = {
            k: sample[k]
            for k in ("shard", "source_code", "report_family", "economic_date", "announcement_id", "url", "sha256", "era")
        }
        try:
            raw = _download(session, sample)
            doc = fitz.open(stream=raw, filetype="pdf")
            pages = v14._candidate_pages(doc)
            candidates = v14._collect_coordinate_candidates(doc, pages)
            chosen, identity = v14._choose_coordinate_identity(candidates)
            raw_recovered = chosen is not None
            role_qualified = False
            role_audit = None
            if chosen:
                role_qualified, role_audit = _qualify(doc, chosen)
            if role_qualified:
                outcome = "ROLE_QUALIFIED_COORDINATE_RECOVERY"
            elif raw_recovered:
                outcome = "RAW_IDENTITY_REJECTED_BY_ROLE_GATE"
            else:
                outcome = "NO_COORDINATE_IDENTITY"
            counts[outcome] += 1
            row.update(
                {
                    "raw_coordinate_recovered": raw_recovered,
                    "role_qualified_recovered": role_qualified,
                    "outcome": outcome,
                    "identity": identity,
                    "selected": {
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
                    "role_audit": role_audit,
                }
            )
        except Exception as exc:
            counts["DIAGNOSTIC_ERROR"] += 1
            row.update(
                {
                    "raw_coordinate_recovered": False,
                    "role_qualified_recovered": False,
                    "outcome": "DIAGNOSTIC_ERROR",
                    "diagnostic_error": f"{type(exc).__name__}: {exc}",
                }
            )
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        rows.append(row)

    qualified = sum(bool(r.get("role_qualified_recovered")) for r in rows)
    report = {
        "gate": "S3G1J_V14_1_COORDINATE_ROLE_AND_PERIOD_DIAGNOSTIC",
        "diagnostic_pass": not errors,
        "sample_count": len(rows),
        "raw_coordinate_recovered_count": sum(bool(r.get("raw_coordinate_recovered")) for r in rows),
        "role_qualified_recovered_count": qualified,
        "role_qualified_recovery_rate": qualified / len(rows) if rows else None,
        "outcome_counts": dict(sorted(counts.items())),
        "policy": {
            "identity_alone_is_insufficient": True,
            "explicit_group_or_consolidated_statement_role_required": True,
            "selected_numeric_column_must_be_group_current_period": True,
            "special_scope_prefixes_rejected": list(SPECIAL_SCOPE_PREFIXES),
            "no_ocr": True,
            "no_later_full_report_backfill": True,
            "identity_tolerance_unchanged": str(v14.IDENTITY_TOLERANCE),
            "diagnostic_only": True,
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
