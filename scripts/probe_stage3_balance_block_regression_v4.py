#!/usr/bin/env python3
from __future__ import annotations

import json
from decimal import Decimal

import requests

from probe_stage3_financial_pdf_parser import ROOT, get_pdf, sha
from stage3_financial_pdf_parser_v2 import parse_pdf_bytes

SAMPLES = [
    ("000536_2014_ANNUAL", "https://static.cninfo.com.cn/finalpage/2015-03-10/1200682838.PDF"),
    ("002448_2014_ANNUAL", "https://static.cninfo.com.cn/finalpage/2015-04-03/1200782615.PDF"),
    ("002477_2014_ANNUAL", "https://static.cninfo.com.cn/finalpage/2015-04-24/1200895700.PDF"),
    ("002646_2014_ANNUAL", "https://static.cninfo.com.cn/finalpage/2015-04-28/1200920754.PDF"),
    ("000692_2014_ANNUAL_REVISED", "https://static.cninfo.com.cn/finalpage/2015-06-27/1201202765.PDF"),
    ("601368_2015_SEMI", "https://static.cninfo.com.cn/finalpage/2015-08-26/1201495537.PDF"),
    ("002655_2015_ANNUAL", "https://static.cninfo.com.cn/finalpage/2016-02-29/1202003967.PDF"),
    ("002684_2015_ANNUAL", "https://static.cninfo.com.cn/finalpage/2016-04-02/1202134484.PDF"),
    ("002464_2015_ANNUAL", "https://static.cninfo.com.cn/finalpage/2016-04-26/1202245707.PDF"),
    ("002711_2015_ANNUAL", "https://static.cninfo.com.cn/finalpage/2016-04-26/1202242886.PDF"),
    ("002457_2016_SEMI", "https://static.cninfo.com.cn/finalpage/2016-08-26/1202617328.PDF"),
    ("002404_2016_ANNUAL", "https://static.cninfo.com.cn/finalpage/2017-03-21/1203179712.PDF"),
]


def _d(v: object) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def main() -> int:
    out = ROOT / "data/stage3_source_probe_v4"
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    errors: list[str] = []
    results = []

    for name, url in SAMPLES:
        rec = {"name": name, "url": url}
        try:
            raw = get_pdf(s, url)
            parsed = parse_pdf_bytes(raw)
            obs = parsed.get("observations") or {}
            triad = {}
            for concept in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"):
                o = obs.get(concept) or {}
                if o.get("status") != "FOUND":
                    errors.append(f"{name} {concept}: NOT_FOUND")
                    triad[concept] = None
                else:
                    triad[concept] = {
                        "value": o.get("normalized_cny_value"),
                        "raw": o.get("raw_value"),
                        "unit": o.get("unit"),
                        "page": o.get("page"),
                        "scope": o.get("extraction_scope"),
                    }
            if parsed.get("validation_errors"):
                errors.extend(f"{name}: {x}" for x in parsed["validation_errors"])
            block = parsed.get("balance_sheet_block")
            if not block:
                errors.append(f"{name}: NO_VALIDATED_BALANCE_SHEET_BLOCK")

            a = _d((obs.get("TOTAL_ASSETS") or {}).get("normalized_cny_value"))
            l = _d((obs.get("TOTAL_LIABILITIES") or {}).get("normalized_cny_value"))
            e = _d((obs.get("TOTAL_EQUITY") or {}).get("normalized_cny_value"))
            rel = None
            if a is not None and l is not None and e is not None:
                rel = abs(a - (l + e)) / max(abs(a), abs(l + e), Decimal("1"))
                if rel > Decimal("0.005"):
                    errors.append(f"{name}: identity rel={rel}")
            rec.update({
                "bytes": len(raw),
                "sha256": sha(raw),
                "page_count": parsed.get("page_count"),
                "balance_sheet_block": block,
                "triad": triad,
                "identity_relative_error": str(rel) if rel is not None else None,
                "validation_errors": parsed.get("validation_errors") or [],
            })
        except Exception as exc:
            errors.append(f"{name}: {exc!r}")
            rec["error"] = repr(exc)
        results.append(rec)

    report = {
        "gate": "S3G1J_BALANCE_BLOCK_REGRESSION_V4",
        "pass": not errors,
        "sample_count": len(SAMPLES),
        "authority": "CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256",
        "policy": "TOTAL_ASSETS, TOTAL_LIABILITIES and TOTAL_EQUITY must come from one monetary-unit-consistent balance-sheet block that passes A=L+E before the document can enter Stage3 financial truth.",
        "results": results,
        "errors": errors,
    }
    (out / "balance_block_regression_v4.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
