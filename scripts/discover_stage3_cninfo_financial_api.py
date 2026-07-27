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
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
KEYWORDS = ["主要财务指标", "盈利能力", "营运能力", "成长能力", "偿债能力", "财务分析"]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def get(s: requests.Session, url: str) -> requests.Response:
    r = s.get(url, headers={"User-Agent": UA, "Referer": HOME}, timeout=60)
    r.raise_for_status()
    return r


def js_urls_from_text(text: str, base: str) -> set[str]:
    urls = set()
    for m in re.findall(r'''(?:src=|href=)["']([^"']+\.js(?:\?[^"']*)?)["']''', text):
        urls.add(urljoin(base, m))
    for m in re.findall(r'''["']([^"']+\.js)["']''', text):
        if m.startswith("/") or m.startswith("static/"):
            urls.add(urljoin(base, m))
    return urls


def contexts(text: str, term: str, radius: int = 1000) -> list[str]:
    out = []
    pos = 0
    while True:
        i = text.find(term, pos)
        if i < 0:
            break
        out.append(text[max(0, i - radius): min(len(text), i + radius)])
        pos = i + len(term)
        if len(out) >= 30:
            break
    return out


def main() -> int:
    outdir = ROOT / "data/stage3_source_probe"
    outdir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    errors = []
    assets: dict[str, dict] = {}
    api_hits: list[dict] = []

    home = get(s, HOME)
    js_urls = js_urls_from_text(home.text, HOME)

    for manifest_name in ("asset-manifest.json", "manifest.json"):
        try:
            r = get(s, urljoin(HOME, manifest_name))
            assets[urljoin(HOME, manifest_name)] = {
                "bytes": len(r.content), "sha256": sha(r.content), "content_type": r.headers.get("Content-Type")
            }
            try:
                obj = r.json()
                blob = json.dumps(obj, ensure_ascii=False)
                for m in re.findall(r'''["']?([^"'\s,]+\.js)["']?''', blob):
                    js_urls.add(urljoin(HOME, m))
            except Exception:
                js_urls.update(js_urls_from_text(r.text, HOME))
        except Exception as exc:
            errors.append(f"optional {manifest_name}: {exc!r}")

    # Home-page scripts may reference lazy chunks by URL literals. Iterate twice.
    fetched: set[str] = set()
    frontier = sorted(js_urls)
    for _round in range(2):
        next_frontier: set[str] = set()
        for url in frontier:
            if url in fetched:
                continue
            fetched.add(url)
            try:
                r = get(s, url)
                text = r.text
                assets[url] = {
                    "bytes": len(r.content),
                    "sha256": sha(r.content),
                    "content_type": r.headers.get("Content-Type"),
                }
                next_frontier.update(js_urls_from_text(text, url))
                for term in KEYWORDS:
                    for ctx in contexts(text, term):
                        endpoints = sorted(set(re.findall(r'''p_sysapi\d+''', ctx)))
                        routes = sorted(set(re.findall(r'''/[A-Za-z][A-Za-z0-9_-]{2,40}''', ctx)))[:50]
                        api_hits.append(
                            {
                                "keyword": term,
                                "asset_url": url,
                                "asset_sha256": assets[url]["sha256"],
                                "p_sysapi_candidates": endpoints,
                                "route_candidates": routes,
                                "context": ctx,
                            }
                        )
            except Exception as exc:
                errors.append(f"asset {url}: {exc!r}")
        frontier = sorted(next_frontier - fetched)

    endpoint_set = sorted({x for h in api_hits for x in h["p_sysapi_candidates"]})
    report = {
        "gate": "S3G1C_CNINFO_FINANCIAL_API_DISCOVERY",
        "pass": bool(api_hits),
        "home_url": HOME,
        "home_sha256": sha(home.content),
        "assets_fetched": len(assets),
        "assets": assets,
        "keywords": KEYWORDS,
        "hit_count": len(api_hits),
        "p_sysapi_candidates": endpoint_set,
        "hits": api_hits[:100],
        "nonfatal_errors": errors,
    }
    if not api_hits:
        report["errors"] = ["No financial-analysis keyword found in official front-end assets"]
    else:
        report["errors"] = []
    (outdir / "cninfo_financial_api_discovery.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: report[k] for k in ("gate", "pass", "assets_fetched", "hit_count", "p_sysapi_candidates", "errors")}, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
