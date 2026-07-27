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
    "same_day_variant_count","same_day_variant_ids","same_day_variant_titles",
    "same_day_tied_top_count","same_day_tied_top_ids","prior_canonical_announcement_id"
]

REPORT_PHRASES = {
    "ANNUAL": "年度报告",
    "SEMI": "半年度报告",
    "Q1": "第一季度报告",
    "Q3": "第三季度报告",
}
REVISION_TOKENS = ("修订版","更正版","更新版","更新后","修正版","更正后","修订稿")
NOTICE_TOKENS = ("修订公告","更正公告","补充公告","修正公告","关于")
FOREIGN_TOKENS = ("H股","H 股","英文版","英文报告","英文")


def clean_title(v: str) -> str:
    v = re.sub(r"<[^>]+>", "", v or "")
    return re.sub(r"\s+", "", v).strip()


def title_class(title: str, family: str) -> tuple[str, int] | None:
    t = clean_title(title)
    phrase = REPORT_PHRASES[family]
    if phrase not in t:
        return None
    if "摘要" in t:
        return None
    if any(x in t for x in FOREIGN_TOKENS):
        return ("FOREIGN_LANGUAGE_OR_H_SHARE", -1000)
    if any(x in t for x in NOTICE_TOKENS):
        # Some issuers embed the actual report inside a numbered title such as
        # “公告2022-013（公司2022年第一季度报告）”.  Do not reject numbered wrappers.
        numbered_wrapper = bool(re.match(r"^公告\d{4}[-—－]?\d+", t)) and phrase in t
        if not numbered_wrapper:
            return ("NOTICE_NOT_REPORT", -900)
    score = 0
    revised = any(x in t for x in REVISION_TOKENS)
    if revised:
        score += 100
    if "全文" in t:
        score += 30
    elif "正文" in t:
        score += 20
    else:
        score += 10
    if t.startswith("公告"):
        score += 1
    cls = "REVISED_FULL_REPORT" if revised else "PRIMARY_FULL_REPORT"
    return cls, score


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

    full = [r for r in rows if r.get("is_full_report_candidate") == "1" and r.get("economic_date")]
    moments: dict[tuple[str,str,str,str], list[dict]] = defaultdict(list)
    for r in full:
        moments[(r["org_id"], r["report_family"], r["economic_date"], r["source_published_at"])].append(r)

    chosen_moments: list[dict] = []
    ignored_foreign = 0
    ignored_notice = 0
    fallback_foreign_moments = []
    tied_moments = []

    for key, variants in moments.items():
        ranked = []
        foreign = []
        notices = []
        for r in variants:
            tc = title_class(r["announcement_title"], r["report_family"])
            if tc is None:
                continue
            cls, score = tc
            if cls == "FOREIGN_LANGUAGE_OR_H_SHARE":
                foreign.append(r)
                continue
            if cls == "NOTICE_NOT_REPORT":
                notices.append(r)
                continue
            ranked.append((score, cls, r))
        ignored_foreign += len(foreign)
        ignored_notice += len(notices)
        if not ranked:
            if foreign:
                fallback_foreign_moments.append({
                    "key": list(key),
                    "announcement_ids": [x["announcement_id"] for x in foreign],
                    "titles": [x["announcement_title"] for x in foreign],
                })
            continue
        best = max(x[0] for x in ranked)
        top = [x for x in ranked if x[0] == best]
        # For a same-date tie we keep one deterministic representative only for
        # transport, but explicitly mark the tie so the PDF/value layer must compare
        # all tied documents before accepting numeric values.
        top.sort(key=lambda x: int(x[2]["announcement_id"]) if x[2]["announcement_id"].isdigit() else x[2]["announcement_id"])
        score, cls, r = top[-1]
        if len(top) > 1:
            tied_moments.append({
                "key": list(key),
                "top_ids": [x[2]["announcement_id"] for x in top],
                "top_titles": [x[2]["announcement_title"] for x in top],
            })
        chosen_moments.append({
            **r,
            "selection_class": cls,
            "same_day_variant_count": len(variants),
            "same_day_variant_ids": json.dumps([x["announcement_id"] for x in variants], ensure_ascii=False),
            "same_day_variant_titles": json.dumps([x["announcement_title"] for x in variants], ensure_ascii=False),
            "same_day_tied_top_count": len(top),
            "same_day_tied_top_ids": json.dumps([x[2]["announcement_id"] for x in top], ensure_ascii=False),
        })

    periods: dict[tuple[str,str,str], list[dict]] = defaultdict(list)
    for r in chosen_moments:
        periods[(r["org_id"],r["report_family"],r["economic_date"])].append(r)

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
                "same_day_tied_top_count": str(r["same_day_tied_top_count"]),
                "same_day_tied_top_ids": r["same_day_tied_top_ids"],
                "prior_canonical_announcement_id": prev,
            })
            prev = r["announcement_id"]

    output.sort(key=lambda r:(r["source_published_at"],r["exchange"],r["source_code"],r["report_family"],r["economic_date"],int(r["revision_sequence"])))
    csv_path = out / "stage3_financial_report_versions.csv.gz"
    with gzip.open(csv_path,"wt",encoding="utf-8",newline="",compresslevel=9) as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(output)

    period_keys = set(periods)
    candidate_period_keys = {(r["org_id"],r["report_family"],r["economic_date"]) for r in full}
    uncovered = sorted(candidate_period_keys - period_keys)
    report = {
        "gate":"S3G1G_FINANCIAL_REPORT_VERSION_SELECTION",
        "pass": not errors,
        "ledger_rows":len(rows),
        "broad_full_report_candidates":len(full),
        "broad_period_groups":len(candidate_period_keys),
        "canonical_revision_moments":len(output),
        "canonical_period_groups":len(period_keys),
        "uncovered_period_groups":len(uncovered),
        "uncovered_period_samples":[list(x) for x in uncovered[:100]],
        "ignored_foreign_or_h_share_documents":ignored_foreign,
        "ignored_notice_documents":ignored_notice,
        "foreign_only_publication_moments":len(fallback_foreign_moments),
        "foreign_only_publication_samples":fallback_foreign_moments[:50],
        "same_day_tied_top_moments":len(tied_moments),
        "same_day_tied_top_samples":tied_moments[:100],
        "selection_policy":"For each issuer/report-period/publication-date, prefer Chinese A-share full report; revised/update version outranks original; 全文 outranks 正文; H-share/English and notice-only documents are excluded from A-share numeric authority. Same-day top-score ties remain explicit and must be value-compared before numeric acceptance.",
        "errors":errors,
    }
    (out/"stage3_financial_report_versions_audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if not errors else 2

if __name__ == "__main__":
    raise SystemExit(main())
