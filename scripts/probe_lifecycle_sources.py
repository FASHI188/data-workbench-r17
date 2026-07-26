#!/usr/bin/env python3
"""Discover exchange-owned machine sources for historical LIST/DELIST events.

Diagnostics only: this script never writes lifecycle facts. It downloads the public
SSE delisting page / SZSE company-notice page plus referenced JavaScript assets and
extracts candidate API URLs, sqlId/catalog identifiers, and lifecycle-related snippets.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
TARGETS = {
    "sse_delisting": "https://www.sse.com.cn/assortment/stock/list/delisting/",
    "szse_company_notice": "https://www.szse.cn/disclosure/notice/company/",
}
KEYS = re.compile(
    r"(?i)(delist|终止上市|暂停上市|DELIST_DATE|COMPANY_STATUS|sqlId|commonQuery|downloadStock|ShowReport|CATALOGID|notice/company)"
)
URLISH = re.compile(r"https?://[^\"'<>\s]+|/[A-Za-z0-9_./?=&%{}:-]{12,}")
SCRIPT_RE = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.I)


def get(session: requests.Session, url: str, referer: str | None = None) -> bytes:
    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"}
    if referer:
        headers["Referer"] = referer
    r = session.get(url, headers=headers, timeout=35)
    r.raise_for_status()
    return r.content


def text(raw: bytes) -> str:
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def snippets(body: str, radius: int = 220) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in KEYS.finditer(body):
        lo = max(0, m.start() - radius)
        hi = min(len(body), m.end() + radius)
        s = re.sub(r"\s+", " ", body[lo:hi]).strip()
        if s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= 300:
            break
    return out


def main() -> int:
    outdir = Path("data/lifecycle_probe")
    outdir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    report: dict[str, object] = {"targets": {}}

    for key, url in TARGETS.items():
        raw = get(session, url)
        body = text(raw)
        (outdir / f"{key}.html").write_bytes(raw)
        scripts = [urljoin(url, x) for x in SCRIPT_RE.findall(body)]
        target_report: dict[str, object] = {
            "url": url,
            "status": "fetched",
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "page_snippets": snippets(body),
            "page_urlish": sorted({x for x in URLISH.findall(body) if KEYS.search(x)})[:300],
            "scripts": [],
        }
        for i, script_url in enumerate(scripts):
            entry: dict[str, object] = {"url": script_url}
            try:
                sraw = get(session, script_url, referer=url)
                sbody = text(sraw)
                entry.update(
                    {
                        "bytes": len(sraw),
                        "sha256": hashlib.sha256(sraw).hexdigest(),
                        "matches": snippets(sbody),
                        "urlish": sorted({x for x in URLISH.findall(sbody) if KEYS.search(x)})[:300],
                    }
                )
                if entry["matches"] or entry["urlish"]:
                    (outdir / f"{key}_script_{i:03d}.js").write_bytes(sraw)
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            if entry.get("matches") or entry.get("urlish") or entry.get("error"):
                target_report["scripts"].append(entry)
        report["targets"][key] = target_report

    path = outdir / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
