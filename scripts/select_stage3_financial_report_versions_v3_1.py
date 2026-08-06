#!/usr/bin/env python3
from __future__ import annotations

import re

import select_stage3_financial_report_versions_v3 as v3


def title_class(title: str, family: str) -> tuple[str, int] | None:
    """V3.1: explicit 全文 wins even when a title also contains 正文.

    Example from the frozen ledger: `第一季度报告全文与正文`.  It is full
    authority, not a body-only document.  All other V3 source gates are kept.
    """
    t = v3.clean_title(title)
    phrase = v3._family_phrase(t, family)
    if not phrase:
        return None
    if "摘要" in t:
        return ("SUMMARY_NOT_FULL_AUTHORITY", -1000)
    if any(x in t for x in v3.FOREIGN_TOKENS):
        return ("FOREIGN_LANGUAGE_H_SHARE_OR_FOREIGN_ISSUER", -1000)
    if any(x in t for x in v3.CANCEL_TOKENS):
        return ("CANCELLED_NOT_AUTHORITY", -1000)
    if any(x in t for x in v3.NOTICE_TOKENS):
        numbered_wrapper = bool(re.match(r"^公告\d{4}[-—－]?\d+", t)) and phrase in t
        if not numbered_wrapper:
            return ("NOTICE_NOT_REPORT", -900)
    if "报告公告" in t and not re.search(r"公司20\d{2}年(?:第一季度|第三季度|半年度|年度)报告公告", t):
        return ("NOTICE_NOT_REPORT", -900)

    revised = any(x in t for x in v3.REVISION_TOKENS)
    base = 100 if revised else 0
    if "全文" in t:
        return (("REVISED_FULL_REPORT" if revised else "PRIMARY_FULL_REPORT"), base + 30)
    if "正文" in t:
        return ("PARTIAL_REPORT_BODY", base + 10)
    return (("REVISED_FULL_REPORT" if revised else "PRIMARY_FULL_REPORT"), base + 20)


v3.title_class = title_class


if __name__ == "__main__":
    raise SystemExit(v3.main())
