#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parents[1]
HOME = "https://webapi.cninfo.com.cn/"
COMPANY_PAGES = [
    "https://webapi.cninfo.com.cn/shgs/company.html?companyid=000001",
    "https://webapi.cninfo.com.cn/shgs/company4.html?companyid=000001&language=en&headerImg=none",
]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
KEYWORDS = [
    "主要财务指标",
    "盈利能力",
    "营运能力",
    "成长能力",
    "偿债能力",
    "财务分析",
    "资产负债表",
    "利润表",
    "现金流量表",
    "Key Financial Ratios",
    "Balance Sheet",
    "Income Statement",
    "Cash Flow Statement",
]
ENDPOINT_RE = re.compile(r"(?:p_sysapi\d+|p_stock\d+|/api/(?:sysapi|stock)/[A-Za-z0-9_]+)")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def get(s: requests.Session, url: str) -> requests.Response:
    r = s.get(url, headers={"User-Agent": UA, "Referer": HOME}, timeout=60)
    r.raise_for_status()
    return r


def decode_variants(raw: bytes, response_text: str | None = None) -> list[str]:
    vals: list[str] = []
    if response_text:
        vals.append(response_text)
    for enc in ("utf-8", "gb18030", "latin1"):
        try:
            vals.append(raw.decode(enc))
        except Exception:
            pass
    expanded: list[str] = []
    for text in vals:
        expanded.append(text)
        # Minified bundles may preserve Chinese labels as JS unicode escapes.
        try:
            if "\\u" in text:
                expanded.append(re.sub(
                    r"\\u([0-9a-fA-F]{4})",
                    lambda m: chr(int(m.group(1), 16)),
                    text,
                ))
        except Exception:
            pass
    out: list[str] = []
    seen = set()
    for x in expanded:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def js_urls_from_text(text: str, base: str) -> set[str]:
    urls = set()
    for m in re.findall(r'''(?:src=|href=)["']([^"']+\.js(?:\?[^"']*)?)["']''', text):
        urls.add(urljoin(base, m))
    for m in re.findall(r'''["']([^"']+\.js(?:\?[^"']*)?)["']''', text):
        if m.startswith("/") or m.startswith("static/") or m.startswith("js/") or m.startswith("shgs/"):
            urls.add(urljoin(base, m))
    return urls


def contexts(text: str, term: str, radius: int = 1400) -> list[str]:
    out = []
    pos = 0
    while True:
        i = text.lower().find(term.lower(), pos)
        if i < 0:
            break
        out.append(text[max(0, i - radius): min(len(text), i + radius)])
        pos = i + max(1, len(term))
        if len(out) >= 40:
            break
    return out


def inspect_blob(raw: bytes, response_text: str, url: str, digest: str) -> tuple[list[dict], set[str], set[str]]:
    hits: list[dict] = []
    endpoints: set[str] = set()
    nested_js: set[str] = set()
    for text in decode_variants(raw, response_text):
        endpoints.update(ENDPOINT_RE.findall(text))
        nested_js.update(js_urls_from_text(text, url))
        for term in KEYWORDS:
            for ctx in contexts(text, term):
                local_endpoints = sorted(set(ENDPOINT_RE.findall(ctx)))
                routes = sorted(set(re.findall(r'''/[A-Za-z][A-Za-z0-9_./?=&-]{2,100}''', ctx)))[:80]
                hits.append(
                    {
                        "keyword": term,
                        "asset_url": url,
                        "asset_sha256": digest,
                        "endpoint_candidates": local_endpoints,
                        "route_candidates": routes,
                        "context": ctx,
                    }
                )
    return hits, endpoints, nested_js


def main() -> int:
    outdir = ROOT / "data/stage3_source_probe"
    outdir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    nonfatal = []
    assets: dict[str, dict] = {}
    api_hits: list[dict] = []
    all_endpoints: set[str] = set()
    js_urls: set[str] = set()
    page_evidence: list[dict] = []

    seed_urls = [HOME, *COMPANY_PAGES]
    for page_url in seed_urls:
        try:
            r = get(s, page_url)
            digest = sha(r.content)
            assets[page_url] = {
                "bytes": len(r.content),
                "sha256": digest,
                "content_type": r.headers.get("Content-Type"),
            }
            page_hits, page_endpoints, nested = inspect_blob(r.content, r.text, page_url, digest)
            api_hits.extend(page_hits)
            all_endpoints.update(page_endpoints)
            js_urls.update(nested)
            page_evidence.append(
                {
                    "url": page_url,
                    "sha256": digest,
                    "keyword_hits": len(page_hits),
                    "endpoint_candidates": sorted(page_endpoints),
                    "script_urls_found": len(nested),
                }
            )
        except Exception as exc:
            nonfatal.append(f"page {page_url}: {exc!r}")

    for manifest_name in ("asset-manifest.json", "manifest.json"):
        url = urljoin(HOME, manifest_name)
        try:
            r = get(s, url)
            digest = sha(r.content)
            assets[url] = {
                "bytes": len(r.content),
                "sha256": digest,
                "content_type": r.headers.get("Content-Type"),
            }
            hits, endpoints, nested = inspect_blob(r.content, r.text, url, digest)
            api_hits.extend(hits)
            all_endpoints.update(endpoints)
            js_urls.update(nested)
        except Exception as exc:
            nonfatal.append(f"optional {manifest_name}: {exc!r}")

    fetched: set[str] = set()
    frontier = sorted(js_urls)
    for _round in range(3):
        next_frontier: set[str] = set()
        for url in frontier:
            if url in fetched:
                continue
            fetched.add(url)
            try:
                r = get(s, url)
                digest = sha(r.content)
                assets[url] = {
                    "bytes": len(r.content),
                    "sha256": digest,
                    "content_type": r.headers.get("Content-Type"),
                }
                hits, endpoints, nested = inspect_blob(r.content, r.text, url, digest)
                api_hits.extend(hits)
                all_endpoints.update(endpoints)
                next_frontier.update(nested)
            except Exception as exc:
                nonfatal.append(f"asset {url}: {exc!r}")
        frontier = sorted(next_frontier - fetched)

    hit_endpoints = sorted({x for h in api_hits for x in h["endpoint_candidates"]})
    report = {
        "gate": "S3G1C_CNINFO_FINANCIAL_API_DISCOVERY_V2",
        "pass": bool(api_hits) and bool(all_endpoints),
        "home_url": HOME,
        "company_pages": COMPANY_PAGES,
        "pages": page_evidence,
        "assets_fetched": len(assets),
        "assets": assets,
        "keywords": KEYWORDS,
        "hit_count": len(api_hits),
        "all_endpoint_candidates": sorted(all_endpoints),
        "keyword_near_endpoint_candidates": hit_endpoints,
        "hits": api_hits[:160],
        "nonfatal_errors": nonfatal,
        "errors": [],
    }
    if not api_hits:
        report["errors"].append("No financial/F10 keyword found in official page/assets")
    if not all_endpoints:
        report["errors"].append("No official API endpoint token found in official page/assets")
    report["pass"] = not report["errors"]
    (outdir / "cninfo_financial_api_discovery.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "gate",
                    "pass",
                    "pages",
                    "assets_fetched",
                    "hit_count",
                    "all_endpoint_candidates",
                    "keyword_near_endpoint_candidates",
                    "errors",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
