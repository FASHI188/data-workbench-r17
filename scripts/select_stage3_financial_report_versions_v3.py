#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

FIELDS = [
    "exchange","source_code","effective_code","org_id","report_family","economic_date",
    "revision_sequence","source_published_at","effective_session","available_at",
    "canonical_announcement_id","canonical_title","canonical_source_url","selection_class",
    "same_day_variant_count","same_day_variant_ids","same_day_variant_titles","same_day_variant_urls",
    "same_day_tied_top_count","same_day_tied_top_ids","same_day_tied_top_titles","same_day_tied_top_urls",
    "prior_canonical_announcement_id"
]

REPORT_PHRASES = {
    "ANNUAL": ("年度报告", "年报"),
    "SEMI": ("半年度报告", "半年报"),
    "Q1": ("第一季度报告", "一季度报告"),
    "Q3": ("第三季度报告", "三季度报告"),
}
REVISION_TOKENS = ("修订版","更正版","更新版","更新后","修正版","更正后","修订稿")
NOTICE_TOKENS = ("修订公告","更正公告","补充公告","修正公告","关于")
CANCEL_TOKENS = ("已取消", "取消", "作废")
FOREIGN_TOKENS = (
    "H股","H 股","英文版","英文报告","英文","翻译稿","翻译件","境外参股公司","Santos"
)


def clean_title(v: str) -> str:
    v = re.sub(r"<[^>]+>", "", v or "")
    return re.sub(r"\s+", "", v).strip()


def _family_phrase(title: str, family: str) -> str | None:
    return next((phrase for phrase in REPORT_PHRASES[family] if phrase in title), None)


def title_class(title: str, family: str) -> tuple[str, int] | None:
    """Classify a CNINFO periodic-report title for full-statement authority.

    V3 deliberately separates *body/正文* from full-report authority.  A body can
    be point-in-time information, but it is not assumed to contain the complete
    financial statements required by S3G1J.  Explicit 全文 and unsuffixed report
    titles are therefore preferred to 正文 rather than the reverse.
    """
    t = clean_title(title)
    phrase = _family_phrase(t, family)
    if not phrase:
        return None
    if "摘要" in t:
        return ("SUMMARY_NOT_FULL_AUTHORITY", -1000)
    if any(x in t for x in FOREIGN_TOKENS):
        return ("FOREIGN_LANGUAGE_H_SHARE_OR_FOREIGN_ISSUER", -1000)
    if any(x in t for x in CANCEL_TOKENS):
        return ("CANCELLED_NOT_AUTHORITY", -1000)
    if any(x in t for x in NOTICE_TOKENS):
        numbered_wrapper = bool(re.match(r"^公告\d{4}[-—－]?\d+", t)) and phrase in t
        if not numbered_wrapper:
            return ("NOTICE_NOT_REPORT", -900)
    if "报告公告" in t and not re.search(r"公司20\d{2}年(?:第一季度|第三季度|半年度|年度)报告公告", t):
        return ("NOTICE_NOT_REPORT", -900)

    revised = any(x in t for x in REVISION_TOKENS)
    base = 100 if revised else 0
    if "正文" in t:
        return ("PARTIAL_REPORT_BODY", base + 10)
    if "全文" in t:
        return (("REVISED_FULL_REPORT" if revised else "PRIMARY_FULL_REPORT"), base + 30)
    return (("REVISED_FULL_REPORT" if revised else "PRIMARY_FULL_REPORT"), base + 20)


def read_ledger(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = read_ledger(Path(a.ledger))
    errors: list[str] = []

    moments: dict[tuple[str,str,str,str], list[tuple[int,str,dict]]] = defaultdict(list)
    partial_by_moment: dict[tuple[str,str,str,str], list[dict]] = defaultdict(list)
    ignored_foreign = 0
    ignored_notice = 0
    ignored_summary = 0
    ignored_cancelled = 0
    explicit_full_synonym_rescues = 0
    strong_full_rows = 0

    for r in rows:
        if not r.get("economic_date"):
            continue
        tc = title_class(r.get("announcement_title", ""), r["report_family"])
        if tc is None:
            continue
        cls, score = tc
        if cls == "FOREIGN_LANGUAGE_H_SHARE_OR_FOREIGN_ISSUER":
            ignored_foreign += 1
            continue
        if cls == "NOTICE_NOT_REPORT":
            ignored_notice += 1
            continue
        if cls == "SUMMARY_NOT_FULL_AUTHORITY":
            ignored_summary += 1
            continue
        if cls == "CANCELLED_NOT_AUTHORITY":
            ignored_cancelled += 1
            continue

        key = (r["org_id"], r["report_family"], r["economic_date"], r["source_published_at"])
        if cls == "PARTIAL_REPORT_BODY":
            partial_by_moment[key].append(r)
            continue

        title = clean_title(r.get("announcement_title", ""))
        legacy_full = r.get("is_full_report_candidate") == "1"
        explicit_full = "全文" in title
        if not legacy_full and not explicit_full:
            # V3 is intentionally narrow: it repairs strong explicit-full aliases
            # missed by the old phrase grammar, but does not promote every newly
            # recognized unsuffixed synonym without PDF-level validation.
            continue
        if explicit_full:
            strong_full_rows += 1
        if explicit_full and not legacy_full:
            explicit_full_synonym_rescues += 1
        moments[key].append((score, cls, r))

    chosen_moments: list[dict] = []
    tied_moments = []
    partial_body_only = []

    all_keys = set(moments) | set(partial_by_moment)
    for key in sorted(all_keys):
        ranked = moments.get(key, [])
        if not ranked:
            bodies = partial_by_moment.get(key, [])
            if bodies:
                partial_body_only.append({
                    "key": list(key),
                    "announcement_ids": [x["announcement_id"] for x in bodies],
                    "titles": [x["announcement_title"] for x in bodies],
                    "urls": [x["source_url"] for x in bodies],
                })
            continue

        best = max(x[0] for x in ranked)
        top = [x for x in ranked if x[0] == best]
        top.sort(key=lambda x: int(x[2]["announcement_id"]) if x[2]["announcement_id"].isdigit() else x[2]["announcement_id"])
        score, cls, r = top[-1]
        variants = [x[2] for x in ranked]
        variants.sort(key=lambda x: int(x["announcement_id"]) if x["announcement_id"].isdigit() else x["announcement_id"])
        if len(top) > 1:
            tied_moments.append({
                "key": list(key),
                "top_ids": [x[2]["announcement_id"] for x in top],
                "top_titles": [x[2]["announcement_title"] for x in top],
                "top_urls": [x[2]["source_url"] for x in top],
            })
        chosen_moments.append({
            **r,
            "selection_class": cls,
            "same_day_variant_count": len(variants),
            "same_day_variant_ids": json.dumps([x["announcement_id"] for x in variants], ensure_ascii=False),
            "same_day_variant_titles": json.dumps([x["announcement_title"] for x in variants], ensure_ascii=False),
            "same_day_variant_urls": json.dumps([x["source_url"] for x in variants], ensure_ascii=False),
            "same_day_tied_top_count": len(top),
            "same_day_tied_top_ids": json.dumps([x[2]["announcement_id"] for x in top], ensure_ascii=False),
            "same_day_tied_top_titles": json.dumps([x[2]["announcement_title"] for x in top], ensure_ascii=False),
            "same_day_tied_top_urls": json.dumps([x[2]["source_url"] for x in top], ensure_ascii=False),
        })

    periods: dict[tuple[str,str,str], list[dict]] = defaultdict(list)
    for r in chosen_moments:
        periods[(r["org_id"], r["report_family"], r["economic_date"])].append(r)

    output = []
    for key, vs in periods.items():
        vs.sort(key=lambda r: (r["source_published_at"], int(r["announcement_id"]) if r["announcement_id"].isdigit() else r["announcement_id"]))
        prev = ""
        for seq, r in enumerate(vs, start=1):
            output.append({
                "exchange": r["exchange"],
                "source_code": r["source_code"],
                "effective_code": r["effective_code"],
                "org_id": r["org_id"],
                "report_family": r["report_family"],
                "economic_date": r["economic_date"],
                "revision_sequence": str(seq),
                "source_published_at": r["source_published_at"],
                "effective_session": r["effective_session"],
                "available_at": r["available_at"],
                "canonical_announcement_id": r["announcement_id"],
                "canonical_title": r["announcement_title"],
                "canonical_source_url": r["source_url"],
                "selection_class": r["selection_class"],
                "same_day_variant_count": str(r["same_day_variant_count"]),
                "same_day_variant_ids": r["same_day_variant_ids"],
                "same_day_variant_titles": r["same_day_variant_titles"],
                "same_day_variant_urls": r["same_day_variant_urls"],
                "same_day_tied_top_count": str(r["same_day_tied_top_count"]),
                "same_day_tied_top_ids": r["same_day_tied_top_ids"],
                "same_day_tied_top_titles": r["same_day_tied_top_titles"],
                "same_day_tied_top_urls": r["same_day_tied_top_urls"],
                "prior_canonical_announcement_id": prev,
            })
            prev = r["announcement_id"]

    output.sort(key=lambda r:(r["source_published_at"],r["exchange"],r["source_code"],r["report_family"],r["economic_date"],int(r["revision_sequence"])))
    csv_path = out / "stage3_financial_report_versions_v3.csv.gz"
    with gzip.open(csv_path, "wt", encoding="utf-8", newline="", compresslevel=9) as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(output)

    old_full_periods = {
        (r["org_id"], r["report_family"], r["economic_date"])
        for r in rows if r.get("is_full_report_candidate") == "1" and r.get("economic_date")
    }
    new_periods = set(periods)
    lost_old_periods = sorted(old_full_periods - new_periods)
    gained_periods = sorted(new_periods - old_full_periods)

    report = {
        "gate": "S3G1G_FINANCIAL_REPORT_VERSION_SELECTION_V3_DIAGNOSTIC",
        "pass": not errors,
        "ledger_rows": len(rows),
        "canonical_revision_moments": len(output),
        "canonical_period_groups": len(new_periods),
        "explicit_full_rows": strong_full_rows,
        "explicit_full_synonym_rescues": explicit_full_synonym_rescues,
        "partial_body_only_publication_moments": len(partial_body_only),
        "partial_body_only_samples": partial_body_only[:200],
        "ignored_summary_documents": ignored_summary,
        "ignored_cancelled_documents": ignored_cancelled,
        "ignored_foreign_h_share_or_foreign_issuer_documents": ignored_foreign,
        "ignored_notice_documents": ignored_notice,
        "same_day_tied_top_moments": len(tied_moments),
        "same_day_tied_top_samples": tied_moments[:100],
        "old_full_period_groups_not_in_v3": len(lost_old_periods),
        "old_full_period_group_samples_not_in_v3": [list(x) for x in lost_old_periods[:100]],
        "v3_period_groups_not_in_old_full_flag": len(gained_periods),
        "v3_new_period_group_samples": [list(x) for x in gained_periods[:100]],
        "selection_policy": (
            "Full-statement authority only. Family synonyms include 年度报告/年报, 半年度报告/半年报, "
            "第一季度报告/一季度报告, 第三季度报告/三季度报告. Explicit 全文 outranks an "
            "unsuffixed report. 正文 is recorded as partial-body evidence but is not assumed to contain "
            "complete financial statements. 摘要, cancelled, foreign-language/H-share and notice-only "
            "documents are excluded. Old is_full rows remain eligible; additionally, explicit 全文 rows "
            "missed solely by the old family-phrase grammar are rescued."
        ),
        "errors": errors,
    }
    (out / "stage3_financial_report_versions_v3_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
