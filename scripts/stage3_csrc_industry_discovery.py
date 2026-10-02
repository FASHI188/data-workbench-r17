#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

LISTS = [
    "https://www.csrc.gov.cn/csrc/c100103/common_list.shtml",
    "https://www.csrc.gov.cn/csrc/c100103/common_list_2.shtml",
]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def get(session: requests.Session, url: str) -> requests.Response:
    r = session.get(
        url,
        headers={"User-Agent": UA, "Referer": "https://www.csrc.gov.cn/"},
        timeout=90,
    )
    r.raise_for_status()
    return r


def norm_title(title: str) -> str:
    return re.sub(r"[.。\s]+$", "", re.sub(r"\s+", "", title or ""))


def discover_csrc_publications(session: requests.Session) -> list[dict]:
    details: dict[str, dict] = {}
    index_evidence: list[dict] = []
    for list_url in LISTS:
        r = get(session, list_url)
        soup = BeautifulSoup(r.content, "html.parser")
        hits = 0
        for a in soup.find_all("a", href=True):
            title = " ".join(a.stripped_strings).strip()
            if "上市公司行业分类结果" not in title:
                continue
            href = urljoin(r.url, a["href"])
            if "content.shtml" not in href:
                continue
            details[href] = {"title": norm_title(title), "detail_url": href}
            hits += 1
        index_evidence.append(
            {
                "url": r.url,
                "sha256": sha(r.content),
                "bytes": len(r.content),
                "classification_links_found": hits,
            }
        )

    out: list[dict] = []
    for detail_url, base in sorted(details.items()):
        r = get(session, detail_url)
        soup = BeautifulSoup(r.content, "html.parser")
        plain = " ".join(soup.stripped_strings)
        dm = re.search(r"日期[：:]?\s*(20\d{2})[-年](\d{1,2})[-月](\d{1,2})", plain)
        if not dm:
            dm = re.search(r"(20\d{2})-(\d{2})-(\d{2})", plain)
        pub = (
            f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
            if dm
            else ""
        )
        pdfs = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = urljoin(r.url, a["href"])
            label = " ".join(a.stripped_strings).strip()
            if ".pdf" not in href.lower():
                continue
            if href in seen:
                continue
            seen.add(href)
            pdfs.append({"title": label, "url": href})
        preferred = next(
            (p for p in pdfs if "行业分类结果" in p["title"]),
            pdfs[0] if len(pdfs) == 1 else None,
        )
        out.append(
            {
                **base,
                "publication_date": pub,
                "detail_final_url": r.url,
                "detail_sha256": sha(r.content),
                "pdf_candidates": pdfs,
                "preferred_pdf": preferred,
                "source_authority": "CSRC_PRIMARY",
                "index_evidence": index_evidence,
            }
        )

    # A migrated page can occasionally be linked more than once.  One official
    # publication period/date enters the PIT ledger once.
    dedup: dict[tuple[str, str], dict] = {}
    for rec in out:
        key = (norm_title(str(rec.get("title") or "")), str(rec.get("publication_date") or ""))
        if key not in dedup:
            dedup[key] = rec
    return sorted(
        dedup.values(),
        key=lambda x: (x.get("publication_date") or "", x.get("title") or ""),
    )
