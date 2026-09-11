#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED_STAGE2_VERSION = "V3.2.25-stage2-final-freeze"
EXPECTED_STAGE2_FP = "f17f7ab63f4532dda635eb7366e7df7bf5497a5ce814410105312bccb53125bb"
EXPECTED_PREFIX = {
    "S3G0_POINT_IN_TIME_FEATURE_CONTRACT": "S3G0",
    "S3G1E_PERIODIC_FILING_LEDGER": "S3G1E",
    "S3G1G_REPORT_VERSION_SELECTION": "S3G1G",
    "S3G1H_PDF_PARSER_PROBE": "S3G1H",
    "S3G1I_POPULATION_PDF_PROBE": "S3G1I",
    "S3G1J_FINANCIAL_RAW_VALUES": "S3G1J",
    "S3G2_ANNOUNCEMENT_LEDGER": "S3G2",
    "S3G3A_INDUSTRY_SOURCE_PROBE": "S3G3A",
    "S3G3B_INDUSTRY_LEDGER": "S3G3B",
    "S3G4A_FORECAST_PARSER_PROBE": "S3G4A",
    "S3G4_EARNINGS_SURPRISE": "S3G4",
    "S3GU_TRADING_UNIVERSE_POLICY": "S3GU",
}
VOLATILE_AUDIT_KEYS = {
    "run_id", "workflow_run_id", "artifact", "artifact_digest", "head_sha",
    "generated_at", "created_at", "updated_at", "completed_at", "frozen_at_utc",
}


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def walk_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def audit_candidates(root: Path) -> list[dict]:
    out = []
    for p in root.rglob("*.json"):
        try:
            obj = load(p)
        except Exception:
            continue
        for d in walk_dicts(obj):
            if isinstance(d.get("gate"), str) and "pass" in d:
                out.append({"path": str(p.relative_to(root)), "record": d})
                break
    return out


def find_clean_gate(candidates: list[dict], prefix: str) -> list[dict]:
    matches = []
    for x in candidates:
        d = x["record"]
        gate = str(d.get("gate") or "")
        if prefix in gate and d.get("pass") is True and not d.get("errors"):
            matches.append(x)
    return matches


def semantic_audit_record(record: dict) -> dict:
    """Drop transport/execution metadata while preserving gate semantics and data hashes."""
    return {k: v for k, v in record.items() if k not in VOLATILE_AUDIT_KEYS}


def semantic_gate_digest(clean: list[dict]) -> str:
    records = [semantic_audit_record(x["record"]) for x in clean]
    records.sort(key=lambda x: canonical_bytes(x))
    return sha_bytes(canonical_bytes(records))


def stage3_fingerprint_basis(policy_sha: str, audit_basis: dict) -> dict:
    """Dataset identity intentionally excludes workflow run IDs and artifact ZIP digests."""
    return {
        "stage2_version": EXPECTED_STAGE2_VERSION,
        "stage2_fingerprint": EXPECTED_STAGE2_FP,
        "trading_universe_policy_sha256": policy_sha,
        "gate_semantic_audits": audit_basis,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--resolved", required=True, help="JSON map containing live run/artifact metadata")
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    outdir = Path(a.out); outdir.mkdir(parents=True, exist_ok=True)
    lock = load(Path(a.lock)); policy = load(Path(a.policy)); resolved = load(Path(a.resolved)); evidence = Path(a.evidence_root)
    errors: list[str] = []

    stage2 = lock.get("stage2") or {}
    if stage2.get("version") != EXPECTED_STAGE2_VERSION or stage2.get("fingerprint") != EXPECTED_STAGE2_FP:
        errors.append(f"wrong Stage2 lock {stage2}")

    gates = lock.get("required_gates") or {}
    if set(gates) != set(EXPECTED_PREFIX):
        errors.append(f"required gate set mismatch missing={sorted(set(EXPECTED_PREFIX)-set(gates))} extra={sorted(set(gates)-set(EXPECTED_PREFIX))}")
    for key, spec in gates.items():
        if not isinstance(spec.get("run_id"), int): errors.append(f"unlocked run_id {key}: {spec.get('run_id')}")
        if not spec.get("artifact"): errors.append(f"missing artifact name {key}")
    remaining = lock.get("remaining_unlocked_gates") or []
    if remaining: errors.append(f"remaining_unlocked_gates not empty: {remaining}")

    if policy.get("status") != "ACTIVE": errors.append("trading universe policy not ACTIVE")
    if policy.get("allowed_boards") != ["SSE_MAIN_A", "SZSE_MAIN_A"]: errors.append(f"wrong allowed boards {policy.get('allowed_boards')}")
    excluded = set(policy.get("excluded_boards") or [])
    if not {"SSE_STAR","SZSE_CHINEXT","BSE","NEEQ"}.issubset(excluded): errors.append(f"excluded boards incomplete {sorted(excluded)}")
    pr = policy.get("price_rule") or {}
    if float(pr.get("maximum_exclusive", -1)) != 70.0 or pr.get("price_equal_70_is_excluded") is not True: errors.append(f"wrong <70 price rule {pr}")
    if pr.get("forbid_current_price_backfill_into_history") is not True: errors.append("current price backfill into history not forbidden")
    policy_sha = sha_bytes(Path(a.policy).read_bytes())

    if set(resolved) != set(gates): errors.append(f"resolved gate set mismatch missing={sorted(set(gates)-set(resolved))} extra={sorted(set(resolved)-set(gates))}")
    transport_provenance = {}
    audit_basis = {}
    for key, spec in gates.items():
        live = resolved.get(key) or {}
        if live.get("run_id") != spec.get("run_id"): errors.append(f"run mismatch {key}")
        if live.get("artifact") != spec.get("artifact"): errors.append(f"artifact name mismatch {key}")
        if live.get("conclusion") != "success": errors.append(f"run not success {key}: {live.get('conclusion')}")
        digest = str(live.get("digest") or "")
        if not digest.startswith("sha256:"): errors.append(f"invalid artifact digest {key}: {digest}")
        gate_root = evidence / key
        if not gate_root.exists():
            errors.append(f"missing downloaded evidence directory {key}")
            continue
        candidates = audit_candidates(gate_root)
        clean = find_clean_gate(candidates, EXPECTED_PREFIX[key])
        if not clean:
            errors.append(f"no clean pass audit JSON for {key}; candidates={[x['record'].get('gate') for x in candidates][:20]}")
            continue
        transport_provenance[key] = {
            "run_id": spec.get("run_id"),
            "artifact": spec.get("artifact"),
            "digest": digest,
        }
        audit_basis[key] = {
            "audit_gates": sorted({str(x["record"].get("gate")) for x in clean}),
            "semantic_sha256": semantic_gate_digest(clean),
        }

    basis = stage3_fingerprint_basis(policy_sha, audit_basis)
    fp = sha_bytes(canonical_bytes(basis))
    report = {
        "gate": "STAGE3_FINAL_FREEZE_CANONICAL_AUDIT",
        "pass": not errors,
        "stage3_dataset_fingerprint": fp,
        "fingerprint_algorithm": "SHA-256 over canonical semantic gate evidence; workflow run IDs and artifact archive digests are transport provenance only",
        "fingerprint_basis": basis,
        "transport_provenance": transport_provenance,
        "errors": errors,
    }
    (outdir / "stage3_final_freeze_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
