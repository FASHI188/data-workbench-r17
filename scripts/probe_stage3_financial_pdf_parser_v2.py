#!/usr/bin/env python3
from __future__ import annotations

import json
from decimal import Decimal

import requests

from probe_stage3_financial_pdf_parser import ROOT, SAMPLES, get_pdf, relerr, sha
from stage3_financial_pdf_parser_v2 import parse_pdf_bytes


def main() -> int:
    out = ROOT / "data/stage3_source_probe_v2"
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    results = []
    errors = []
    for spec in SAMPLES:
        try:
            raw = get_pdf(s, spec["url"])
            parsed = parse_pdf_bytes(raw)
            checks = []
            if parsed.get("validation_errors"):
                errors.extend(f"{spec['name']}: {x}" for x in parsed["validation_errors"])
            for concept, expected_s in spec["expected"].items():
                o = parsed["observations"][concept]
                if o["status"] != "FOUND":
                    errors.append(f"{spec['name']} {concept}: NOT_FOUND")
                    checks.append({"concept": concept, "pass": False, "reason": "NOT_FOUND"})
                    continue
                actual = Decimal(str(o["normalized_cny_value"]))
                expected = Decimal(expected_s)
                err = relerr(actual, expected)
                ok = err <= Decimal("0.000001")
                if not ok:
                    errors.append(f"{spec['name']} {concept}: actual={actual} expected={expected} relerr={err}")
                checks.append({
                    "concept": concept,
                    "pass": ok,
                    "actual": str(actual),
                    "expected": str(expected),
                    "relative_error": str(err),
                })
            if parsed["tier1_found"] < int(spec["required_tier1"]):
                errors.append(f"{spec['name']}: tier1 coverage {parsed['tier1_found']} < {spec['required_tier1']}")
            if parsed["tier2_found"] < int(spec["required_tier2"]):
                errors.append(f"{spec['name']}: tier2 coverage {parsed['tier2_found']} < {spec['required_tier2']}")
            results.append({
                "name": spec["name"],
                "url": spec["url"],
                "bytes": len(raw),
                "sha256": sha(raw),
                "required_tier1": spec["required_tier1"],
                "required_tier2": spec["required_tier2"],
                "expected_checks": checks,
                "validation_errors": parsed.get("validation_errors") or [],
            })
        except Exception as exc:
            errors.append(f"{spec['name']}: {exc!r}")
            results.append({"name": spec["name"], "url": spec["url"], "error": repr(exc)})
    report = {
        "gate": "S3G1J_REPAIR_PARSER_V2_PROBE",
        "pass": not errors,
        "sample_count": len(SAMPLES),
        "authority": "CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256",
        "results": results,
        "errors": errors,
    }
    (out / "financial_pdf_parser_v2_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
