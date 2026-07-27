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
EXPECTED = {
    "KEY_RATIOS": "sysapi/p_sysapi1140",
    "BALANCE_SHEET": "sysapi/p_sysapi1143",
    "INCOME_STATEMENT": "sysapi/p_sysapi1141",
    "CASH_FLOW": "sysapi/p_sysapi1142",
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


def one(pattern: str, text: str, label: str, errors: list[str]) -> str | None:
    m = re.search(pattern, text)
    if not m:
        errors.append(f"cannot extract {label}")
        return None
    return m.group(1)


def main() -> int:
    outdir = ROOT / "data/stage3_source_probe"
    outdir.mkdir(parents=True, exist_ok=True)
    r = fetch()
    text = decode(r.content)
    errors: list[str] = []

    # The official current company.js dynamically routes three statement boxes through
    # one variable (o) and uses a dedicated variable (l) for the key-ratio table.
    balance = one(
        r'''"Balance-Sheet"===\w+\)\w+="([^"]+)"''',
        text,
        "Balance-Sheet API",
        errors,
    )
    income = one(
        r'''"Income-Statement"===\w+\)\w+="([^"]+)"''',
        text,
        "Income-Statement API",
        errors,
    )
    cash = one(
        r'''"Cash-Flow-Statement"===\w+\)\w+="([^"]+)"''',
        text,
        "Cash-Flow-Statement API",
        errors,
    )
    key = one(
        r'''#Key-Financial-Ratios-table",\w+=\$\(this\)\.attr\("data-rtype"\),\w+="([^"]+)"''',
        text,
        "Key-Financial-Ratios API",
        errors,
    )

    actual = {
        "KEY_RATIOS": key,
        "BALANCE_SHEET": balance,
        "INCOME_STATEMENT": income,
        "CASH_FLOW": cash,
    }

    # Require the same point-in-time request contract shown by the official F10 JS.
    statement_contract = re.search(
        r'''loadBootstrapTableData\(\{table:\w+,apiName:\w+,urlParam:\{scode:[^,}]+,sign:[^,}]+,rtype:[^}]+\},initTable:!1\}\)''',
        text,
    )
    key_contract = re.search(
        r'''loadBootstrapTableData\(\{table:\w+,apiName:\w+,urlParam:\{scode:[^,}]+,sign:[^,}]+,rtype:[^}]+\},initTable:!1\}\)''',
        text[text.find("#Key-Financial-Ratios-table") :],
    )
    sign_source = re.search(r'''sign:([A-Za-z0-9_.$]+\.F002N)''', text)

    if not statement_contract:
        errors.append("cannot verify statement request contract scode+sign+rtype")
    if not key_contract:
        errors.append("cannot verify key-ratio request contract scode+sign+rtype")
    if not sign_source:
        errors.append("cannot verify sign source ending in F002N")

    for label, expected in EXPECTED.items():
        if actual.get(label) != expected:
            errors.append(
                f"{label} API mismatch expected={expected} actual={actual.get(label)}"
            )

    endpoint_contexts = {}
    for label, api in actual.items():
        if not api:
            continue
        i = text.find(api)
        endpoint_contexts[label] = text[max(0, i - 1800) : min(len(text), i + 4200)]

    report = {
        "gate": "S3G1C2_EXACT_CNINFO_FINANCIAL_TABLE_CALLS_V2",
        "pass": not errors,
        "source_url": URL,
        "source_bytes": len(r.content),
        "source_sha256": sha(r.content),
        "mapping": actual,
        "expected_mapping": EXPECTED,
        "request_contract": {
            "required_params": ["scode", "sign", "rtype"],
            "rtype_semantics_from_official_ui": {
                "1": "Q1",
                "2": "SEMI_ANNUAL",
                "3": "Q3",
                "4": "ANNUAL",
            },
            "sign_source_expression": sign_source.group(1) if sign_source else None,
            "statement_contract_verified": bool(statement_contract),
            "key_ratio_contract_verified": bool(key_contract),
        },
        "endpoint_contexts": endpoint_contexts,
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
                "mapping": actual,
                "request_contract": report["request_contract"],
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
