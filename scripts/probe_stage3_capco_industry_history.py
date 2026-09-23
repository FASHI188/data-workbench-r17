#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import fitz
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
BASES = [
    "https://www.capco.org.cn/xhgg/hyfl/hyfljg/",
    "https://www.capco.org.cn/pub/zgssgsxh/xhgg/hyfl/hyfljg/",
]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def get(session: requests.Session, url: str) -> requests.Response:
    r = session.get(url, headers={"User-Agent": UA, "Referer": "https://www.capco.org.cn/"}, timeout=60)
    r.raise_for_status()
    return r


def decode_html(raw: bytes) -> tuple[str, str]:
    candidates = []
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            text = raw.decode(enc)
            score = sum(text.count(x) for x in ("上市公司行业分类结果", "行业分类结果", "发布时间", "按股票代码"))
            candidates.append((score, enc, text))
        except Exception:
            pass
    if not candidates:
        return raw.decode("latin1", errors="replace"), "latin1"
    candidates.sort(key=lambda x: (x[0], x[1] == "utf-8"), reverse=True)
    _, enc, text = candidates[0]
    return text, enc


def index_urls() -> list[str]:
    out = []
    for base in BASES:
        for i in range(5):
            out.append(urljoin(base, "index.html" if i == 0 else f"index_{i}.html"))
    return out


def main() -> int:
    out = ROOT / "data/stage3_source_probe"
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    entries: dict[str, dict] = {}
    nonfatal = []
    index_evidence = []

    for u in index_urls():
        try:
            r = get(s, u)
            text, encoding = decode_html(r.content)
            soup = BeautifulSoup(text, "html.parser")
            hit_count = 0
            for a in soup.find_all("a", href=True):
                title = " ".join(a.stripped_strings).strip()
                if "上市公司行业分类结果" not in title:
                    continue
                href = urljoin(r.url, a["href"])
                entries[href] = {"title": title, "detail_url": href}
                hit_count += 1
            index_evidence.append({
                "requested_url": u,
                "final_url": r.url,
                "sha256": sha(r.content),
                "bytes": len(r.content),
                "decoded_as": encoding,
                "classification_links_found": hit_count,
            })
        except Exception as exc:
            nonfatal.append(f"index {u}: {exc!r}")

    details = []
    for u, e in sorted(entries.items()):
        try:
            r = get(s, u)
            text_decoded, encoding = decode_html(r.content)
            soup = BeautifulSoup(text_decoded, "html.parser")
            text = " ".join(soup.stripped_strings)
            dm = re.search(r"发布时间[：:]?\s*(20\d{2})[-年](\d{1,2})[-月](\d{1,2})", text)
            if not dm:
                dm = re.search(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})", text)
            pub = f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}" if dm else ""

            pdfs = []
            for a in soup.find_all("a", href=True):
                href = urljoin(r.url, a["href"])
                label = " ".join(a.stripped_strings).strip()
                # Some CAPCO pages expose an attachment without a literal .pdf suffix;
                # keep explicit result-attachment links and verify by PDF magic below.
                if ".pdf" in href.lower() or "行业分类结果" in label or "按股票代码" in label:
                    pdfs.append({"title": label, "url": href})
            dedup = []
            seen = set()
            for p in pdfs:
                if p["url"] not in seen:
                    seen.add(p["url"]); dedup.append(p)
            pdfs = dedup
            preferred = [x for x in pdfs if "按股票代码" in x["title"]]
            if not preferred:
                preferred = [x for x in pdfs if "行业分类结果" in x["title"] and "按行业" not in x["title"]]
            if not preferred:
                preferred = pdfs

            attachments = []
            for p in preferred[:3]:
                try:
                    pr = get(s, p["url"])
                    rec = {
                        "title": p["title"],
                        "requested_url": p["url"],
                        "final_url": pr.url,
                        "sha256": sha(pr.content),
                        "bytes": len(pr.content),
                        "pdf_magic": pr.content.startswith(b"%PDF"),
                        "content_type": pr.headers.get("Content-Type"),
                    }
                    if rec["pdf_magic"]:
                        d = fitz.open(stream=pr.content, filetype="pdf")
                        txt = "\n".join(d[i].get_text("text") or "" for i in range(min(4, d.page_count)))
                        rec["pages"] = d.page_count
                        rec["sample_codes"] = sorted(set(re.findall(r"(?<!\d)\d{6}(?!\d)", txt)))[:30]
                        rec["text_sample"] = txt[:4000]
                    attachments.append(rec)
                except Exception as exc:
                    attachments.append({"title": p["title"], "url": p["url"], "error": repr(exc), "pdf_magic": False})
            details.append({
                **e,
                "publication_date": pub,
                "detail_final_url": r.url,
                "detail_sha256": sha(r.content),
                "detail_decoded_as": encoding,
                "attachments": attachments,
            })
        except Exception as exc:
            nonfatal.append(f"detail {u}: {exc!r}")

    years = []
    for d in details:
        m = re.search(r"(20\d{2})", d["title"])
        if m:
            years.append(int(m.group(1)))
    covered = [y for y in years if 2015 <= y <= 2025]
    usable = [d for d in details if d["publication_date"] and any(x.get("pdf_magic") for x in d["attachments"])]
    fatal = []
    if not entries:
        fatal.append("no classification result entries discovered")
    if len(usable) < 20:
        fatal.append(f"usable official result publications too few: {len(usable)}")
    if not covered:
        fatal.append("no 2015-2025 industry classifications discovered")
    elif min(covered) > 2015 or max(covered) < 2025:
        fatal.append(f"historical coverage does not span 2015-2025: {min(covered)}-{max(covered)}")

    report = {
        "gate": "S3G3A_CAPCO_INDUSTRY_HISTORY_SOURCE_PROBE_V2",
        "pass": not fatal,
        "index_evidence": index_evidence,
        "discovered_entries": len(entries),
        "usable_publications": len(usable),
        "covered_year_min": min(covered) if covered else None,
        "covered_year_max": max(covered) if covered else None,
        "details": details,
        "nonfatal_errors": nonfatal,
        "errors": fatal,
    }
    (out / "capco_industry_history_probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("gate", "pass", "discovered_entries", "usable_publications", "covered_year_min", "covered_year_max", "errors")}, ensure_ascii=False, indent=2))
    return 0 if not fatal else 2


if __name__ == "__main__":
    raise SystemExit(main())
