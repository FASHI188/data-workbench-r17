#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import fitz
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.capco.org.cn/xhgg/hyfl/hyfljg/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
TZ = ZoneInfo("Asia/Shanghai")
CODE_RE = re.compile(r"^(?:00|001|002|003|600|601|603|605)\d{3}$")
GENERIC_CODE_RE = re.compile(r"^\d{6}$")
INDUSTRY_CODE_RE = re.compile(r"^[A-Z]{1,2}\d{0,4}$|^\d{2,4}$")
FIELDS = [
    "publication_title","publication_date","effective_session","available_at",
    "source_page_url","source_page_sha256","source_pdf_url","source_pdf_sha256",
    "source_pdf_bytes","source_code","effective_code","company_name",
    "industry_code_primary","industry_codes_json","industry_names_json","raw_columns_json",
    "classification_system","parse_method"
]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def get(s: requests.Session, url: str) -> requests.Response:
    r = s.get(url, headers={"User-Agent": UA, "Referer": "https://www.capco.org.cn/"}, timeout=90)
    r.raise_for_status()
    return r


def discover_publications(s: requests.Session) -> list[dict]:
    found: dict[str, dict] = {}
    for i in range(5):
        u = urljoin(BASE, "index.html" if i == 0 else f"index_{i}.html")
        r = get(s, u)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.stripped_strings)
            if "上市公司行业分类结果" not in title:
                continue
            detail = urljoin(u, a["href"])
            found[detail] = {"title": title, "detail_url": detail}
    out = []
    for detail, x in sorted(found.items()):
        r = get(s, detail)
        soup = BeautifulSoup(r.text, "html.parser")
        text = " ".join(soup.stripped_strings)
        dm = re.search(r"发布时间[：:]?\s*(20\d{2})[-年](\d{1,2})[-月](\d{1,2})", text)
        if not dm:
            dm = re.search(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})", text)
        pub = f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}" if dm else ""
        pdfs = []
        for a in soup.find_all("a", href=True):
            href = urljoin(detail, a["href"])
            label = " ".join(a.stripped_strings)
            if ".pdf" in href.lower():
                pdfs.append({"title": label, "url": href})
        preferred = [p for p in pdfs if "按股票代码" in p["title"]]
        if not preferred:
            preferred = [p for p in pdfs if "行业分类结果" in p["title"] and "按行业" not in p["title"]]
        if not preferred and len(pdfs) == 1:
            preferred = pdfs
        out.append({
            **x,
            "publication_date": pub,
            "detail_sha256": sha(r.content),
            "pdf_candidates": pdfs,
            "preferred_pdf": preferred[0] if preferred else None,
        })
    return out


def load_intervals(path: Path) -> dict[tuple[str, str], tuple[date, date | None]]:
    out = {}
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            out[(r["exchange"], r["code"])] = (
                date.fromisoformat(r["listed_from"]),
                date.fromisoformat(r["listed_to_exclusive"]) if r.get("listed_to_exclusive") else None,
            )
    return out


def load_transitions() -> list[dict]:
    p = ROOT / "config/security_code_transitions.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def active(iv: tuple[date, date | None] | None, d: date) -> bool:
    return bool(iv and d >= iv[0] and (iv[1] is None or d < iv[1]))


def effective_code_for(code: str, d: date, intervals: dict, transitions: list[dict]) -> str | None:
    for ex in ("SSE", "SZSE"):
        if active(intervals.get((ex, code)), d):
            return code
    for t in transitions:
        if t["old_code"] == code and d >= date.fromisoformat(t["effective_date"]):
            new = t["new_code"]
            if active(intervals.get((t["exchange"], new)), d):
                return new
    return None


def g3_days(root: Path) -> list[date]:
    days = set()
    for p in sorted(root.rglob("szse_*.csv.gz")):
        with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
            rd = csv.DictReader(f)
            if not rd.fieldnames or "trade_date" not in rd.fieldnames:
                continue
            for r in rd:
                if r.get("trade_date"):
                    days.add(date.fromisoformat(r["trade_date"]))
    return sorted(days)


def next_session(pub: date, days: list[date]) -> date | None:
    i = bisect.bisect_right(days, pub)
    return days[i] if i < len(days) else None


def cell_text(x: object) -> str:
    return re.sub(r"\s+", "", "" if x is None else str(x)).strip()


def extract_table_rows(raw: bytes) -> tuple[list[list[str]], dict]:
    doc = fitz.open(stream=raw, filetype="pdf")
    rows: list[list[str]] = []
    methods = defaultdict(int)
    for page in doc:
        extracted = False
        try:
            tabs = page.find_tables()
            for table in tabs.tables:
                for row in table.extract():
                    vals = [cell_text(x) for x in row]
                    if any(vals):
                        rows.append(vals)
                        methods["PYMUPDF_TABLE"] += 1
                        extracted = True
        except Exception:
            pass
        if extracted:
            continue
        # Fallback for older PDFs without table geometry: retain line tokens.
        lines = [cell_text(x) for x in (page.get_text("text") or "").splitlines() if cell_text(x)]
        for i, token in enumerate(lines):
            if GENERIC_CODE_RE.fullmatch(token):
                rows.append(lines[i:i+8])
                methods["TEXT_WINDOW"] += 1
    return rows, {"page_count": doc.page_count, "method_counts": dict(methods)}


def normalize_record(row: list[str]) -> dict | None:
    vals = [cell_text(x) for x in row if cell_text(x)]
    if not vals:
        return None
    idx = next((i for i, x in enumerate(vals) if GENERIC_CODE_RE.fullmatch(x)), None)
    if idx is None:
        return None
    code = vals[idx]
    tail = vals[idx+1:]
    if not tail:
        return None
    company = tail[0]
    rest = tail[1:]
    codes = [x for x in rest if INDUSTRY_CODE_RE.fullmatch(x)]
    names = [x for x in rest if not INDUSTRY_CODE_RE.fullmatch(x)]
    # Prefer combined regulatory code such as C35 / I65. If only separate door/category
    # tokens exist, preserve all codes and synthesize no new value.
    primary = next((x for x in codes if re.fullmatch(r"[A-Z]{1,2}\d{2,4}", x)), "")
    if not primary:
        letter = next((x for x in codes if re.fullmatch(r"[A-Z]", x)), "")
        digits = next((x for x in codes if re.fullmatch(r"\d{2,4}", x)), "")
        if letter and digits:
            primary = letter + digits
    return {
        "source_code": code,
        "company_name": company,
        "industry_code_primary": primary,
        "industry_codes": codes,
        "industry_names": names,
        "raw_columns": vals,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--g2-intervals", required=True)
    ap.add_argument("--g3-root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    s = requests.Session(); errors: list[str] = []
    intervals = load_intervals(Path(a.g2_intervals)); transitions = load_transitions(); days = g3_days(Path(a.g3_root))
    if len(days) != 2808:
        errors.append(f"G3 trading-day count {len(days)} != 2808")
    publications = discover_publications(s)
    selected = [p for p in publications if p["publication_date"] and "2015" <= p["publication_date"][:4] <= "2026"]
    ledger = []; pub_audit = []; seen_pub_dates = set()
    for p in selected:
        pdf = p.get("preferred_pdf")
        if not pdf:
            errors.append(f"no preferred PDF for {p['title']} {p['detail_url']}")
            continue
        try:
            r = get(s, pdf["url"])
            if not r.content.startswith(b"%PDF"):
                raise ValueError(f"not PDF type={r.headers.get('Content-Type')}")
            rows, diag = extract_table_rows(r.content)
            normalized = [x for x in (normalize_record(row) for row in rows) if x]
            pub_day = date.fromisoformat(p["publication_date"]); eff = next_session(pub_day, days)
            if eff is None:
                pub_audit.append({"title": p["title"], "publication_date": p["publication_date"], "status": "OUTSIDE_G3_AFTER_END"})
                continue
            mainboard = []; duplicates = []
            local_seen = set()
            for n in normalized:
                ecode = effective_code_for(n["source_code"], eff, intervals, transitions)
                if not ecode:
                    continue
                if ecode in local_seen:
                    duplicates.append(ecode); continue
                local_seen.add(ecode)
                mainboard.append(n)
                system = "CAPCO_2023_GUIDE" if pub_day >= date(2023,5,1) else "CSRC_2012_GUIDE"
                ledger.append({
                    "publication_title": p["title"], "publication_date": p["publication_date"],
                    "effective_session": eff.isoformat(), "available_at": datetime.combine(eff, datetime.min.time(), tzinfo=TZ).isoformat(),
                    "source_page_url": p["detail_url"], "source_page_sha256": p["detail_sha256"],
                    "source_pdf_url": pdf["url"], "source_pdf_sha256": sha(r.content), "source_pdf_bytes": str(len(r.content)),
                    "source_code": n["source_code"], "effective_code": ecode, "company_name": n["company_name"],
                    "industry_code_primary": n["industry_code_primary"],
                    "industry_codes_json": json.dumps(n["industry_codes"], ensure_ascii=False),
                    "industry_names_json": json.dumps(n["industry_names"], ensure_ascii=False),
                    "raw_columns_json": json.dumps(n["raw_columns"], ensure_ascii=False),
                    "classification_system": system, "parse_method": "PYMUPDF_TABLE_WITH_TEXT_FALLBACK",
                })
            if duplicates:
                errors.append(f"duplicate mainboard codes in {p['title']}: {duplicates[:20]} count={len(duplicates)}")
            pub_audit.append({
                "title": p["title"], "publication_date": p["publication_date"], "effective_session": eff.isoformat(),
                "detail_url": p["detail_url"], "pdf_url": pdf["url"], "pdf_sha256": sha(r.content), "pdf_bytes": len(r.content),
                "raw_detected_rows": len(normalized), "mainboard_rows": len(mainboard), **diag,
            })
            seen_pub_dates.add(p["publication_date"])
        except Exception as exc:
            errors.append(f"{p['title']}: {exc!r}")
    ledger.sort(key=lambda r:(r["effective_session"],r["effective_code"],r["publication_title"]))
    path = out / "stage3_industry_classification_ledger.csv.gz"
    with gzip.open(path,"wt",encoding="utf-8",newline="",compresslevel=9) as f:
        w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(ledger)
    per_pub = defaultdict(int)
    for r in ledger: per_pub[(r["publication_title"],r["publication_date"])]+=1
    low = [{"title":k[0],"publication_date":k[1],"mainboard_rows":v} for k,v in per_pub.items() if v < 1000]
    if low:
        errors.append(f"industry publications with implausibly low mainboard rows: {low[:20]} count={len(low)}")
    report = {
        "gate":"S3G3B_POINT_IN_TIME_INDUSTRY_CLASSIFICATION_LEDGER","pass":not errors,
        "discovered_publications":len(publications),"selected_2015_2026_publications":len(selected),
        "publication_snapshots_with_rows":len(per_pub),"ledger_rows":len(ledger),"publication_audit":pub_audit,
        "low_coverage_publications":low,"ledger_sha256":sha(path.read_bytes()),
        "availability_policy":"CAPCO publication date is date-only; classification becomes usable on the first strictly later frozen G3 trading session.",
        "current_industry_backfill_used":False,"errors":errors,
    }
    (out/"stage3_industry_classification_audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ('gate','pass','discovered_publications','selected_2015_2026_publications','publication_snapshots_with_rows','ledger_rows','low_coverage_publications','errors')},ensure_ascii=False,indent=2))
    return 0 if not errors else 2

if __name__ == "__main__": raise SystemExit(main())
