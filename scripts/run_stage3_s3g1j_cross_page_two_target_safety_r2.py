#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
from typing import Any

import audit_stage3_s3g1j_cross_page_two_target_safety as core


def exact_residual_identity(row: dict[str, str]) -> tuple[str, int, str, list[str], int]:
    if row.get("document_status") != "ERROR":
        raise ValueError("candidate target is not an ERROR residual")
    if row.get("tie_candidate_count") != "1" or row.get("tie_resolution") != "TIE_SOURCE_INCOMPLETE":
        raise ValueError("candidate target is not a single-canonical source-incomplete residual")
    candidates = json.loads(row.get("candidate_evidence_json") or "[]")
    if len(candidates) != 1:
        raise ValueError("candidate target must have exactly one candidate evidence object")
    candidate = candidates[0]
    if str(candidate.get("id") or "") != str(row.get("announcement_id") or ""):
        raise ValueError("candidate announcement identity drift")
    validation = [str(x) for x in (candidate.get("validation_errors") or [])]
    tier2 = int(candidate.get("tier2_found") or 0)
    if tier2 != 3 or "NO_VALIDATED_BALANCE_SHEET_BLOCK" not in validation:
        raise ValueError("candidate target no longer has expected fail-closed candidate evidence")
    sha = str(candidate.get("sha256") or "")
    size = int(candidate.get("bytes") or 0)
    url = str(candidate.get("url") or "")
    if not sha or size <= 0 or not url:
        raise ValueError("candidate source identity incomplete")
    return sha, size, url, validation, tier2


def build_full_population_routing(documents: Path) -> dict[str, Any]:
    if core.sha256_file(documents) != core.SOURCE_DOCUMENTS_GZIP_SHA256:
        raise ValueError("accepted V17.29 documents gzip SHA drift")
    if core.sha256_gzip_plaintext(documents) != core.SOURCE_DOCUMENTS_PLAINTEXT_SHA256:
        raise ValueError("accepted V17.29 documents plaintext SHA drift")

    input_rows = 0
    routes: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    with gzip.open(documents, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            input_rows += 1
            aid = str(row.get("announcement_id") or "")
            if aid not in core.TARGETS:
                continue
            if aid in seen_targets:
                raise ValueError(f"duplicate target document row {aid}")
            seen_targets.add(aid)
            sha, size, url, validation, tier2 = exact_residual_identity(row)
            target = core.TARGETS[aid]
            if not core.is_exact_target(aid, str(row.get("economic_date") or ""), sha, size):
                raise ValueError(f"target source/date identity drift {aid}")
            if url != target["source_url"]:
                raise ValueError(f"target source URL drift {aid}")
            routes.append({
                "announcement_id": aid,
                "economic_date": str(row.get("economic_date") or ""),
                "source_sha256": sha,
                "source_bytes": size,
                "source_url": url,
                "document_status": str(row.get("document_status") or ""),
                "tie_resolution": str(row.get("tie_resolution") or ""),
                "candidate_tier2_found": tier2,
                "candidate_validation_errors": validation,
            })

    routes.sort(key=lambda x: x["announcement_id"])
    if input_rows != 121354:
        raise ValueError(f"accepted V17.29 document population changed {input_rows}")
    if [x["announcement_id"] for x in routes] != sorted(core.TARGETS):
        raise ValueError(f"exact target routing drift {routes}")
    return {
        "input_document_rows": input_rows,
        "candidate_route_count": len(routes),
        "formal_v17_29_delegate_count": input_rows - len(routes),
        "candidate_route_announcement_ids": [x["announcement_id"] for x in routes],
        "candidate_rows": routes,
        "residual_source_identity_origin": "SINGLE_CANDIDATE_EVIDENCE_JSON",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--documents", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    if [x["announcement_id"] for x in evidence["cross_page_exact_source_candidates"]] != sorted(core.TARGETS):
        raise ValueError("governance eligible target set drift")
    if evidence["classification_result"]["candidate_parser_implementation_authorized"] is not False:
        raise ValueError("governance unexpectedly authorizes formal parser implementation")
    if evidence["classification_result"]["candidate_parser_promotion_authorized"] is not False:
        raise ValueError("governance unexpectedly authorizes candidate promotion")

    routing = build_full_population_routing(Path(args.documents))
    recoveries: list[dict[str, Any]] = []
    for aid in sorted(core.TARGETS):
        target = core.TARGETS[aid]
        raw = core.fetch_exact_pdf(target)
        recovered = core.recover_exact_target(raw, target)
        recoveries.append({
            "announcement_id": aid,
            "source_code": target["source_code"],
            "economic_date": target["economic_date"],
            "source_url": target["source_url"],
            "source_sha256": target["source_sha256"],
            "source_bytes": target["source_bytes"],
            **recovered,
        })

    mutation_checks = []
    for aid, target in sorted(core.TARGETS.items()):
        mutation_checks.append({
            "announcement_id": aid,
            "wrong_sha_delegates": not core.is_exact_target(aid, target["economic_date"], "0" * 64, target["source_bytes"]),
            "wrong_bytes_delegates": not core.is_exact_target(aid, target["economic_date"], target["source_sha256"], target["source_bytes"] + 1),
            "wrong_date_delegates": not core.is_exact_target(aid, "1900-01-01", target["source_sha256"], target["source_bytes"]),
        })
    if not all(all(row[k] for k in ("wrong_sha_delegates", "wrong_bytes_delegates", "wrong_date_delegates")) for row in mutation_checks):
        raise ValueError("mutated target identity did not delegate")

    report = {
        "gate": "S3G1J_V17_29_TWO_TARGET_CROSS_PAGE_CANDIDATE_SAFETY_V1",
        "method": core.METHOD,
        "source_run": core.SOURCE_RUN,
        "source_artifact_id": core.SOURCE_ARTIFACT_ID,
        "source_artifact_digest": core.SOURCE_ARTIFACT_DIGEST,
        "routing": routing,
        "recoveries": recoveries,
        "mutation_delegation_checks": mutation_checks,
        "candidate_experiment_pass": True,
        "candidate_parser_implementation_authorized": False,
        "candidate_parser_promotion_authorized": False,
        "formal_parser_changed": False,
        "runtime_authority_changed": False,
        "production_data_changed": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_live_locked": True,
        "main_changed": False,
        "errors": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "gate": report["gate"],
        "routing": routing,
        "recoveries": [
            {
                "announcement_id": x["announcement_id"],
                "formal_validation_errors": x["formal_v17_29_snapshot"]["validation_errors"],
                "cross_page_pattern": x["candidate_recovery"]["cross_page_pattern"],
                "dual_column_identity": x["candidate_recovery"]["dual_column_identity"],
            }
            for x in recoveries
        ],
        "candidate_experiment_pass": True,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
