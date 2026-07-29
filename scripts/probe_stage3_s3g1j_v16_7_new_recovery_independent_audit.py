#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import fitz
import requests

CLAIMS = {
    "1202090846": {
        "source_code": "000100", "economic_date": "2015-12-31", "sha256": "a125e8185e9df0982756defc5db245c7c160e9c153edc4b4ea11f6dc5d9fdf09",
        "values": {"TOTAL_ASSETS": ("111754821", "千元", 101, "资产总计"), "TOTAL_LIABILITIES": ("74125380", "千元", 102, "负债合计"), "TOTAL_EQUITY": ("37629441", "千元", 102, "股东权益合计")},
    },
    "1203753366": {
        "source_code": "000100", "economic_date": "2017-06-30", "sha256": "74877ac680347a731c6f2e633b057378f29035487aeb105f9ad7395ece1e5423",
        "values": {"TOTAL_ASSETS": ("151316723", "千元", 57, "资产总计"), "TOTAL_LIABILITIES": ("101581000", "千元", 58, "负债合计"), "TOTAL_EQUITY": ("49735723", "千元", 58, "股东权益合计")},
    },
    "1207606864": {
        "source_code": "601633", "economic_date": "2019-12-31", "sha256": "a7758c2994fbd37e3739391d35ea5ff32d2e232b71f5c0f0b7983f36e7616e4e",
        "values": {"TOTAL_ASSETS": ("113096409468.96", "元", 114, "资产总计"), "TOTAL_LIABILITIES": ("58697179552.06", "元", 115, "负债合计"), "TOTAL_EQUITY": ("54399229916.90", "元", 115, "股东权益合计")},
    },
    "1212651259": {
        "source_code": "600808", "economic_date": "2021-12-31", "sha256": "7ceb048a0ad640fcb9568b9e40f745a793d91b10b4c8f7b46f16ae5ae4849d18",
        "values": {"TOTAL_ASSETS": ("91207743018", "元", 78, "资产总计"), "TOTAL_LIABILITIES": ("53796559540", "元", 79, "负债合计"), "TOTAL_EQUITY": ("37411183478", "元", 80, "股东权益合计")},
    },
    "1214450943": {
        "source_code": "600196", "economic_date": "2022-06-30", "sha256": "8ffeed728cbab0774c886913e5589b609035324e809e10a5164910d808312883",
        "values": {"TOTAL_ASSETS": ("98804453933.26", "元", 89, "资产总计"), "TOTAL_LIABILITIES": ("51070366988.01", "元", 90, "负债合计"), "TOTAL_EQUITY": ("47734086945.25", "元", 91, "股东权益合计")},
    },
    "1216276255": {
        "source_code": "601633", "economic_date": "2022-12-31", "sha256": "6642e7547b8f1c67c020209f19d7b882fbdf11d5f8af88ec5d45664880e65edc",
        "values": {"TOTAL_ASSETS": ("185357300473.07", "元", 169, "资产总计"), "TOTAL_LIABILITIES": ("120141392357.77", "元", 170, "负债合计"), "TOTAL_EQUITY": ("65215908115.30", "元", 170, "股东权益合计")},
    },
    "1225101866": {
        "source_code": "000938", "economic_date": "2025-12-31", "sha256": "2ffcd21150d98d8582b3cda68a368e70eaf17625e8ba2881a9ed30d7654aac5a",
        "values": {"TOTAL_ASSETS": ("96323416301.66", "元", 97, "资产总计"), "TOTAL_LIABILITIES": ("78839936203.05", "元", 98, "负债合计"), "TOTAL_EQUITY": ("17483480098.61", "元", 99, "股东权益合计")},
    },
}
UNIT_MULTIPLIER = {"元": Decimal("1"), "千元": Decimal("1000"), "万元": Decimal("10000"), "百万元": Decimal("1000000"), "亿元": Decimal("100000000")}
DATE_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {r["canonical_announcement_id"]: r for r in csv.DictReader(handle)}


def download(session: requests.Session, url: str) -> bytes:
    response = session.get(url, headers={"User-Agent": "Mozilla/5.0 independent-financial-statement-audit", "Referer": "https://www.cninfo.com.cn/"}, timeout=120)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise ValueError("not PDF")
    return response.content


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").replace(",", "").replace("合幵", "合并")


def cn_date(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{y}年{m}月{d}日"


def statement_events(doc: fitz.Document, start: int, end: int) -> list[dict]:
    events = []
    for page_1b in range(max(1, start), min(doc.page_count, end) + 1):
        text = doc[page_1b - 1].get_text("text") or ""
        for line in text.splitlines():
            c = compact(line)
            if "资产负债表" not in c:
                continue
            role = "OTHER"
            if "合并资产负债表" in c or "合并及" in c and "资产负债表" in c:
                role = "GROUP_OR_DUAL"
            elif "母公司资产负债表" in c or ("公司资产负债表" in c and "合并" not in c) or ("银行资产负债表" in c and "合并" not in c):
                role = "PARENT"
            elif c.startswith("资产负债表"):
                role = "GENERIC"
            events.append({"page": page_1b, "role": role, "line": line.strip()})
    return events


def nearest_statement_role(events: list[dict], page_1b: int) -> dict | None:
    eligible = [e for e in events if e["page"] <= page_1b]
    if not eligible:
        return None
    return max(eligible, key=lambda e: e["page"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    versions = read_versions(Path(args.versions))
    missing = sorted(set(CLAIMS) - set(versions))
    if missing:
        raise ValueError(f"missing claims from frozen versions: {missing}")

    session = requests.Session()
    rows = []
    errors = []
    for aid, claim in sorted(CLAIMS.items()):
        version = versions[aid]
        result = {"announcement_id": aid, "source_code": claim["source_code"], "economic_date": claim["economic_date"], "canonical_title": version["canonical_title"]}
        try:
            raw = download(session, version["canonical_source_url"])
            digest = hashlib.sha256(raw).hexdigest()
            doc = fitz.open(stream=raw, filetype="pdf")
            min_page = min(x[2] for x in claim["values"].values())
            max_page = max(x[2] for x in claim["values"].values())
            audit_start = max(1, min_page - 12)
            events = statement_events(doc, audit_start, max_page)
            value_checks = {}
            normalized = {}
            all_rows_present = True
            all_roles_group = True
            for concept, (raw_value, unit, page_1b, alias) in claim["values"].items():
                page_text = doc[page_1b - 1].get_text("text") or ""
                page_compact = compact(page_text)
                alias_present = compact(alias) in page_compact
                value_present = compact(raw_value) in page_compact
                role_event = nearest_statement_role(events, page_1b)
                role_group = bool(role_event) and role_event["role"] == "GROUP_OR_DUAL"
                value_checks[concept] = {
                    "page": page_1b,
                    "alias": alias,
                    "raw_value": raw_value,
                    "unit": unit,
                    "alias_present_on_claimed_page": alias_present,
                    "raw_value_present_on_claimed_page": value_present,
                    "nearest_statement_event": role_event,
                    "nearest_statement_is_group_or_dual": role_group,
                }
                all_rows_present = all_rows_present and alias_present and value_present
                all_roles_group = all_roles_group and role_group
                normalized[concept] = Decimal(raw_value) * UNIT_MULTIPLIER[unit]

            segment_text = "\n".join((doc[p - 1].get_text("text") or "") for p in range(audit_start, max_page + 1))
            date_present = compact(cn_date(claim["economic_date"])) in compact(segment_text)
            unit_present = all(compact(unit) in compact(segment_text) for _, unit, _, _ in claim["values"].values())
            identity_residual = abs(normalized["TOTAL_ASSETS"] - normalized["TOTAL_LIABILITIES"] - normalized["TOTAL_EQUITY"])
            identity_ok = identity_residual == 0
            sha_ok = digest == claim["sha256"]
            passed = sha_ok and all_rows_present and all_roles_group and date_present and unit_present and identity_ok
            if not passed:
                errors.append(f"{aid} independent audit failed")
            result.update({
                "sha256": digest,
                "sha256_matches_replay": sha_ok,
                "audit_page_window": [audit_start, max_page],
                "statement_events": events,
                "economic_date_present_in_audit_window": date_present,
                "declared_unit_present_in_audit_window": unit_present,
                "value_checks": value_checks,
                "identity_residual_cny": str(identity_residual),
                "identity_exact": identity_ok,
                "pass": passed,
            })
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{aid}: {result['error']}")
        rows.append(result)

    report = {
        "gate": "S3G1J_V16_7_NEW_RECOVERY_INDEPENDENT_OFFICIAL_PDF_AUDIT",
        "pass": not errors and len(rows) == 7 and all(r.get("pass") for r in rows),
        "sample_count": len(rows),
        "pass_count": sum(bool(r.get("pass")) for r in rows),
        "policy": {
            "does_not_call_v14_or_v16_parser": True,
            "uses_frozen_official_pdf_url": True,
            "checks_sha": True,
            "checks_claimed_page_alias_and_raw_value": True,
            "checks_nearest_statement_group_or_dual": True,
            "checks_economic_date_in_statement_window": True,
            "checks_declared_unit": True,
            "checks_exact_accounting_identity": True,
        },
        "rows": rows,
        "errors": errors,
        "stage4_alpha_locked": True,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "sample_count": len(rows), "pass_count": report["pass_count"], "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
