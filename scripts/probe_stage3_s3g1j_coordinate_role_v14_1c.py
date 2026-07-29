#!/usr/bin/env python3
from __future__ import annotations

import re

import probe_stage3_s3g1j_coordinate_role_v14_1b as probe


def _line_role(line: str) -> str | None:
    raw = re.sub(r"\s+", "", line or "").lower()
    raw = raw.replace("（续）", "").replace("(续)", "").replace("-续", "")
    if not raw or "目录" in raw:
        return None

    dual_tokens = (
        "合并及母公司资产负债表",
        "合并及公司资产负债表",
        "合并及银行资产负债表",
        "合并资产负债表和母公司资产负债表",
        "合并资产负债表及母公司资产负债表",
        "合并资产负债表及资产负债表",
    )
    if any(token in raw for token in dual_tokens):
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


def _nearest_statement_role(doc, page_1b: int, max_lookback: int = 8) -> tuple[str | None, dict]:
    start = max(1, page_1b - max_lookback)
    events = []
    for p in range(start, page_1b + 1):
        text = doc[p - 1].get_text("text") or ""
        for idx, line in enumerate(text.splitlines()):
            role = _line_role(line)
            if role:
                events.append({"page": p, "line_index": idx, "role": role, "line": line.strip()})
    if not events:
        return None, {"page": page_1b, "events": []}
    chosen = sorted(events, key=lambda e: (e["page"], e["line_index"]))[-1]
    return chosen["role"], {"page": page_1b, "events": events[-12:], "chosen": chosen}


def _qualify(doc, chosen: dict) -> tuple[bool, dict]:
    reasons = []
    scope = {}
    columns = {}
    statement_roles = {}

    for concept, selected in chosen.items():
        role, role_evidence = _nearest_statement_role(doc, int(selected["page"]))
        statement_roles[concept] = {"role": role, "evidence": role_evidence}
        if role not in ("GROUP", "DUAL_GROUP_PARENT"):
            reasons.append(f"{concept}:NEAREST_STATEMENT_ROLE={role}")

        ok, reason = probe._row_scope_ok(selected)
        scope[concept] = {"ok": ok, "reason": reason}
        if not ok:
            reasons.append(f"{concept}:{reason}")

        # A confirmed GROUP statement uses its left-most numeric amount as the
        # current period. A DUAL statement additionally requires the explicit
        # 本集团-vs-本公司/本行 split inherited from V14.1b.
        context = {"group_title": role in ("GROUP", "DUAL_GROUP_PARENT")}
        column = probe._column_role(doc, selected, context)
        columns[concept] = column
        if not column.get("group_current"):
            reasons.append(
                f"{concept}:NOT_GROUP_CURRENT role={column.get('role')} period={column.get('period')}"
            )

    roles = {x.get("role") for x in statement_roles.values()}
    if "PARENT" in roles:
        reasons.append("PARENT_STATEMENT_ROW_SELECTED")
    if None in roles:
        reasons.append("UNBOUND_STATEMENT_ROLE")

    return not reasons, {
        "nearest_statement_roles": statement_roles,
        "scope_checks": scope,
        "column_role_checks": columns,
        "reasons": reasons,
    }


probe._qualify = _qualify

if __name__ == "__main__":
    raise SystemExit(probe.main())
