#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import requests

from stage3_financial_pdf_parser_v7 import parse_pdf_bytes

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "config/stage3_s3g1j_v10_diagnostic_samples.json"
OUT = ROOT / "data/stage3_source_probe_v11/s3g1j_v11_recovery_48.json"


def _download(session: requests.Session, sample: dict) -> bytes:
    response = session.get(sample["url"], timeout=90)
    response.raise_for_status()
    raw = response.content
    actual = hashlib.sha256(raw).hexdigest()
    if actual != sample["sha256"]:
        raise AssertionError(
            f"{sample['announcement_id']} SHA mismatch expected={sample['sha256']} actual={actual}"
        )
    return raw


def main() -> int:
    spec = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    samples = spec.get("samples") or []
    if len(samples) != int(spec.get("sample_count") or -1):
        raise ValueError("sample_count contract mismatch")

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 S3G1J-V11-recovery"})
    rows = []
    diagnostic_errors: list[str] = []

    for sample in samples:
        row = {
            k: sample[k]
            for k in (
                "shard",
                "source_code",
                "report_family",
                "economic_date",
                "announcement_id",
                "url",
                "sha256",
                "era",
            )
        }
        try:
            raw = _download(session, sample)
            parsed = parse_pdf_bytes(raw)
            validation_errors = parsed.get("validation_errors") or []
            balance = parsed.get("balance_sheet_block")
            recovered = bool(balance) and not validation_errors
            row.update(
                {
                    "recovered": recovered,
                    "validation_errors": validation_errors,
                    "balance_sheet_block": balance,
                    "tier1_found": parsed.get("tier1_found"),
                    "tier2_found": parsed.get("tier2_found"),
                }
            )
        except Exception as exc:
            row.update(
                {
                    "recovered": False,
                    "diagnostic_error": f"{type(exc).__name__}: {exc}",
                }
            )
            diagnostic_errors.append(
                f"{sample.get('announcement_id')}: {type(exc).__name__}: {exc}"
            )
        rows.append(row)

    recovered = [r for r in rows if r.get("recovered")]
    remaining = [r for r in rows if not r.get("recovered") and not r.get("diagnostic_error")]
    family = Counter((r["report_family"], bool(r.get("recovered"))) for r in rows)
    era = Counter((r["era"], bool(r.get("recovered"))) for r in rows)
    report = {
        "gate": "S3G1J_V11_1_STRATIFIED_RECOVERY_48",
        "diagnostic_pass": not diagnostic_errors,
        "sample_count": len(rows),
        "recovered_count": len(recovered),
        "remaining_count": len(remaining),
        "recovery_rate": len(recovered) / len(rows) if rows else None,
        "family_counts": {
            f"{family_name}|{'RECOVERED' if ok else 'REMAINING'}": count
            for (family_name, ok), count in sorted(family.items())
        },
        "era_counts": {
            f"{era_name}|{'RECOVERED' if ok else 'REMAINING'}": count
            for (era_name, ok), count in sorted(era.items())
        },
        "policy": {
            "same_48_failures_as_v10_1": True,
            "official_pdf_sha_required": True,
            "recovered_requires_validated_balance_block": True,
            "recovered_requires_no_validation_errors": True,
            "production_identity_tolerance_unchanged": "0.005",
            "diagnostic_does_not_promote_s3g1j": True,
        },
        "rows": rows,
        "diagnostic_errors": diagnostic_errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not diagnostic_errors else 2


if __name__ == "__main__":
    sys.exit(main())
