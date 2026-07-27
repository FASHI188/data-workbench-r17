#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
URL = "https://webapi.cninfo.com.cn/shgs/company.js"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
TARGETS = {
    "KEY_RATIOS": "#Key-Financial-Ratios-table",
    "BALANCE_SHEET": "#Balance-Sheet-table",
    "INCOME_STATEMENT": "#Income-Statement-table",
    "CASH_FLOW": "#Cash-Flow-Statement-table",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch() -> requests.Response:
    r = requests.get(
        URL,
        headers={
            "User-Agent": UA,
            "Referer": "https://webapi.cninfo.com.cn/shgs/company.html?companyid=000001",
        },
        timeout=60,
    )
    r.raise_for_status()
    return r


def decode(raw: bytes) -> str:
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("latin1")


def balanced_object(text: str, start: int) -> str | None:
    """Return a JS object literal beginning at/after start using brace/string balancing."""
    i = text.find("{", start)
    if i < 0:
        return None
    depth = 0
    quote = None
    esc = False
    for j in range(i, len(text)):
        ch = text[j]
        if quote:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[i : j + 1]
    return None


def parse_calls(text: str) -> list[dict]:
    calls = []
    token = "loadBootstrapTableData("
    pos = 0
    while True:
        i = text.find(token, pos)
        if i < 0:
            break
        obj = balanced_object(text, i + len(token))
        if obj:
            table = re.search(r'''table\s*:\s*["']([^"']+)["']''', obj)
            api = re.search(r'''apiName\s*:\s*["']([^"']+)["']''', obj)
            url_param = re.search(r'''urlParam\s*:\s*\{([^}]*)\}''', obj)
            calls.append(
                {
                    "offset": i,
                    "table": table.group(1) if table else None,
                    "api_name": api.group(1) if api else None,
                    "url_param_raw": url_param.group(1) if url_param else None,
                    "object_literal": obj,
                }
            )
        pos = i + len(token)
    return calls


def target_contexts(text: str) -> list[dict]:
    out = []
    for label, needle in TARGETS.items():
        for m in re.finditer(re.escape(needle), text):
            a = max(0, m.start() - 12000)
            b = min(len(text), m.end() + 12000)
            ctx = text[a:b]
            out.append(
                {
                    "target": label,
                    "needle": needle,
                    "offset": m.start(),
                    "endpoint_tokens": sorted(
                        set(re.findall(r'''(?:stock/p_stock\d+|sysapi/p_sysapi\d+|p_stock\d+|p_sysapi\d+)''', ctx))
                    ),
                    "api_name_tokens": sorted(
                        set(re.findall(r'''apiName\s*:\s*["']([^"']+)["']''', ctx))
                    ),
                    "context": ctx,
                }
            )
    return out


def main() -> int:
    outdir = ROOT / "data/stage3_source_probe"
    outdir.mkdir(parents=True, exist_ok=True)
    r = fetch()
    text = decode(r.content)
    calls = parse_calls(text)
    contexts = target_contexts(text)

    mapping = {}
    for label, target in TARGETS.items():
        exact = [c for c in calls if c.get("table") == target]
        mapping[label] = exact

    errors = []
    for label in TARGETS:
        if not mapping[label]:
            errors.append(f"No exact loadBootstrapTableData call found for {label}")
        elif not any(c.get("api_name") for c in mapping[label]):
            errors.append(f"Exact call for {label} has no apiName")

    report = {
        "gate": "S3G1C2_EXACT_CNINFO_FINANCIAL_TABLE_CALLS",
        "pass": not errors,
        "source_url": URL,
        "source_bytes": len(r.content),
        "source_sha256": sha(r.content),
        "total_load_bootstrap_calls": len(calls),
        "target_mapping": mapping,
        "target_contexts": contexts,
        "errors": errors,
    }
    (outdir / "cninfo_financial_table_calls.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "gate": report["gate"],
                "pass": report["pass"],
                "source_sha256": report["source_sha256"],
                "total_load_bootstrap_calls": report["total_load_bootstrap_calls"],
                "mapping": {
                    k: [
                        {
                            "table": x.get("table"),
                            "api_name": x.get("api_name"),
                            "url_param_raw": x.get("url_param_raw"),
                        }
                        for x in v
                    ]
                    for k, v in mapping.items()
                },
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
