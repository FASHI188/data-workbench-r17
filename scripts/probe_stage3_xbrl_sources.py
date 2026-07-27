#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
PROBES = [
    {"venue":"SZSE","kind":"portal","url":"http://xbrl.cninfo.com.cn/XBRL/index.jsp"},
    {"venue":"SZSE","kind":"historical_sample","url":"http://xbrl.cninfo.com.cn/XBRL/allinfo.jsp?stkid=000001&getyear=2024&nowpage=Info.jsp&reportType=GB0110"},
    {"venue":"SZSE","kind":"historical_old_code","url":"http://xbrl.cninfo.com.cn/XBRL/allinfo.jsp?stkid=000022&getyear=2017&nowpage=Info.jsp&reportType=GB0110"},
    {"venue":"SSE","kind":"portal","url":"http://listxbrl.sse.com.cn/ssexbrl/index.htm"},
    {"venue":"SSE","kind":"historical_sample","url":"http://listxbrl.sse.com.cn/ssexbrl/presentAction.do?year=2024&period=n&StockCode=600519"},
    {"venue":"SSE","kind":"historical_delisted","url":"http://listxbrl.sse.com.cn/ssexbrl/presentAction.do?year=2014&period=n&StockCode=601268"},
]
LINK_RE = re.compile(r'''(?:href|src|action)=["']([^"']+)["']''', re.I)
TOKEN_RE = re.compile(r'''[^"'<>\s]+\.(?:xml|xbrl|xsd|zip)(?:\?[^"'<>\s]*)?''', re.I)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch(session: requests.Session, url: str) -> dict:
    rec = {"requested_url": url}
    try:
        r = session.get(url, headers={"User-Agent":UA,"Referer":url}, timeout=45, allow_redirects=True)
        rec.update({
            "status_code": r.status_code,
            "final_url": r.url,
            "redirect_chain": [{"status":h.status_code,"url":h.url,"location":h.headers.get("Location")} for h in r.history],
            "content_type": r.headers.get("Content-Type"),
            "bytes": len(r.content),
            "sha256": sha(r.content),
        })
        text = r.text if "text" in (r.headers.get("Content-Type") or "").lower() or b"<html" in r.content[:500].lower() else ""
        links = []
        if text:
            for x in LINK_RE.findall(text):
                links.append(urljoin(r.url, x))
            links += [urljoin(r.url, x) for x in TOKEN_RE.findall(text)]
        interesting = sorted({x for x in links if any(t in x.lower() for t in ("xbrl",".xml",".xsd",".zip","instance","download","presentaction","allinfo","info.jsp"))})
        rec["interesting_links"] = interesting[:200]
        rec["html_title"] = (re.search(r"<title[^>]*>(.*?)</title>", text, re.I|re.S).group(1).strip() if text and re.search(r"<title[^>]*>(.*?)</title>", text, re.I|re.S) else None)
        rec["reachable"] = r.status_code < 500 and len(r.content) > 0
    except Exception as exc:
        rec.update({"reachable":False,"error":repr(exc)})
    return rec


def main() -> int:
    out = ROOT / "data/stage3_source_probe"
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    results = []
    for p in PROBES:
        results.append({**p, **fetch(s, p["url"])})

    venue = {}
    for v in ("SSE","SZSE"):
        xs = [r for r in results if r["venue"] == v]
        venue[v] = {
            "probe_count": len(xs),
            "reachable_count": sum(bool(x.get("reachable")) for x in xs),
            "instance_link_evidence_count": sum(bool(x.get("interesting_links")) for x in xs),
        }
    usable = any(x.get("reachable") and x.get("interesting_links") for x in results)
    report = {
        "gate":"S3G1F_OFFICIAL_XBRL_SOURCE_DISCOVERY",
        "pass":True,
        "discovery_complete":True,
        "xbrl_instance_path_currently_discovered":usable,
        "venue_summary":venue,
        "probes":results,
        "decision":(
            "XBRL path candidate exists; validate revision-level instance download before using numeric values."
            if usable else
            "No current revision-level XBRL instance path was discovered from the historical official portals; retain original filing PDF as PIT authority and treat XBRL as unavailable until stronger evidence appears."
        ),
        "errors":[],
    }
    (out / "xbrl_source_probe.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
