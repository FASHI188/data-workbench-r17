#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FAMILIES = {
    "FINANCIAL_REPORT",
    "ANNOUNCEMENT",
    "INDUSTRY",
    "EVENT_SURPRISE",
}
REQUIRED_FIELDS = {
    "exchange",
    "code",
    "feature_family",
    "feature_name",
    "economic_date",
    "source_published_at",
    "available_at",
    "effective_session",
    "revision_id",
    "source_url",
    "source_sha256",
    "raw_value",
    "unit",
    "methodology_version",
}
REQUIRED_GATES = {
    "stage2_fingerprint_exact_match",
    "all_records_have_source_sha256",
    "all_records_have_available_at",
    "no_effective_session_before_availability",
    "date_only_sources_use_conservative_next_session",
    "revisions_are_append_only",
    "surprise_requires_prior_expectation",
    "unknown_publication_time_cannot_be_assumed_intraday",
    "feature_source_and_methodology_version_are_auditable",
}
FORBIDDEN_AUTHORITATIVE = {
    "AKSHARE_WRAPPER_OUTPUT",
    "EASTMONEY",
    "TONGHUASHUN",
    "SINA_FINANCE",
    "MEDIA_REPRINT",
    "SELF_MEDIA",
}


def canonical_sha(obj: object) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def flatten_primary(node: object) -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "primary" and isinstance(value, list):
                out.update(str(x) for x in value)
            else:
                out.update(flatten_primary(value))
    elif isinstance(node, list):
        for value in node:
            out.update(flatten_primary(value))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", default="config/stage3_feature_contract.json")
    ap.add_argument("--source-authority", default="config/stage3_source_authority.json")
    ap.add_argument("--stage2-manifest", default="data/stage2_final/manifest.json")
    ap.add_argument("--out", default="data/stage3_contract")
    args = ap.parse_args()

    contract_path = ROOT / args.contract
    authority_path = ROOT / args.source_authority
    stage2_path = ROOT / args.stage2_manifest
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    contract = json.loads(contract_path.read_text(encoding="utf-8")) if contract_path.exists() else {}
    authority = json.loads(authority_path.read_text(encoding="utf-8")) if authority_path.exists() else {}
    stage2 = json.loads(stage2_path.read_text(encoding="utf-8")) if stage2_path.exists() else {}
    if not contract:
        errors.append(f"missing contract: {contract_path}")
    if not authority:
        errors.append(f"missing source authority: {authority_path}")
    if not stage2:
        errors.append(f"missing Stage2 manifest: {stage2_path}")

    dependency = contract.get("depends_on_stage2") or {}
    expected_fp = dependency.get("dataset_fingerprint")
    actual_fp = stage2.get("stage2_dataset_fingerprint")
    if stage2.get("status") != "PASS" or stage2.get("all_hard_gates_pass") is not True:
        errors.append("Stage2 is not a frozen PASS dependency")
    if not expected_fp or expected_fp != actual_fp:
        errors.append(f"Stage2 fingerprint mismatch expected={expected_fp} actual={actual_fp}")
    if stage2.get("alpha_training_allowed") is not True:
        errors.append("Stage2 does not allow downstream feature/model work")

    families = set(contract.get("feature_families") or [])
    if families != REQUIRED_FAMILIES:
        errors.append(f"feature families mismatch: {sorted(families)}")

    authority_families = set((authority.get("families") or {}).keys())
    if authority_families != REQUIRED_FAMILIES:
        errors.append(f"source-authority families mismatch: {sorted(authority_families)}")
    primary_sources = flatten_primary(authority.get("families") or {})
    forbidden_primary = sorted(primary_sources & FORBIDDEN_AUTHORITATIVE)
    if forbidden_primary:
        errors.append(f"non-authoritative sources configured as primary: {forbidden_primary}")
    declared_non_authoritative = set(authority.get("non_authoritative_by_default") or [])
    if not FORBIDDEN_AUTHORITATIVE.issubset(declared_non_authoritative):
        errors.append("source-authority config does not explicitly demote all default non-authoritative sources")

    fields = set(contract.get("required_fields") or [])
    missing_fields = sorted(REQUIRED_FIELDS - fields)
    if missing_fields:
        errors.append(f"missing required feature fields: {missing_fields}")

    gates = contract.get("hard_gates") or {}
    missing_gates = sorted(k for k in REQUIRED_GATES if gates.get(k) is not True)
    if missing_gates:
        errors.append(f"required hard gates not enabled: {missing_gates}")

    timing = contract.get("timing_policy") or {}
    for key in (
        "timestamped_source",
        "date_only_source",
        "non_trading_day_source",
        "after_cutoff_source",
        "revision_policy",
        "surprise_policy",
        "training_join_policy",
    ):
        if not str(timing.get(key) or "").strip():
            errors.append(f"missing timing policy: {key}")

    report = {
        "gate": "S3G0_POINT_IN_TIME_FEATURE_CONTRACT",
        "pass": not errors,
        "stage3_version": contract.get("version"),
        "source_authority_version": authority.get("version"),
        "stage2_version": stage2.get("version"),
        "stage2_dataset_fingerprint": actual_fp,
        "contract_sha256": canonical_sha(contract) if contract else None,
        "source_authority_sha256": canonical_sha(authority) if authority else None,
        "feature_families": sorted(families),
        "primary_sources": sorted(primary_sources),
        "required_field_count": len(fields),
        "hard_gate_count": sum(1 for v in gates.values() if v is True),
        "errors": errors,
    }
    (out / "stage3_contract_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
