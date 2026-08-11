#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

EXPECTED_IDS = {
    "1202799494", "1204077386", "1205543437",
    "1209806910", "1223347318", "1223407043",
}
BANK_EXCLUDED_ID = "1219834247"


def load_targets(evidence_path: Path) -> dict[str, dict]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    boundary = evidence["surviving_p0_root_cause_boundary"]
    targets = {str(row["announcement_id"]): row for row in boundary["diagnostic_only"]}
    if set(targets) != EXPECTED_IDS:
        raise ValueError(f"diagnostic target set drift {sorted(targets)}")
    blocked = {str(row["announcement_id"]) for row in boundary["do_not_promote"]}
    if blocked != {BANK_EXCLUDED_ID}:
        raise ValueError(f"bank isolation boundary drift {sorted(blocked)}")
    if int(boundary["safe_exact_source_candidate_count"]) != 0:
        raise ValueError("surviving P0 unexpectedly already has safe candidate")
    return targets


def normalize_row(row: dict[str, str], target: dict) -> dict[str, str]:
    aid = str(row.get("announcement_id") or "")
    if aid != str(target["announcement_id"]):
        raise ValueError(f"announcement mismatch row={aid} target={target['announcement_id']}")
    if row.get("document_status") != "ERROR":
        raise ValueError(f"{aid}: expected residual ERROR row")
    if row.get("tie_candidate_count") != "1" or row.get("tie_resolution") != "TIE_SOURCE_INCOMPLETE":
        raise ValueError(f"{aid}: expected single-canonical incomplete residual")

    candidates = json.loads(row.get("candidate_evidence_json") or "[]")
    if len(candidates) != 1:
        raise ValueError(f"{aid}: expected exactly one candidate evidence row")
    candidate = candidates[0]
    if str(candidate.get("id") or "") != aid:
        raise ValueError(f"{aid}: candidate announcement identity drift")

    expected_sha = str(target["source_sha256"])
    candidate_sha = str(candidate.get("sha256") or "")
    if candidate_sha != expected_sha:
        raise ValueError(f"{aid}: candidate source SHA drift expected={expected_sha} actual={candidate_sha}")

    candidate_url = str(candidate.get("url") or "")
    candidate_bytes = int(candidate.get("bytes") or 0)
    if not candidate_url:
        raise ValueError(f"{aid}: candidate source URL missing")
    if candidate_bytes <= 0:
        raise ValueError(f"{aid}: candidate source bytes missing")

    selected_url = str(row.get("selected_source_url") or "")
    canonical_url = str(row.get("canonical_source_url") or "")
    if selected_url and selected_url != candidate_url:
        raise ValueError(f"{aid}: selected source URL drift")
    if canonical_url and canonical_url != candidate_url:
        raise ValueError(f"{aid}: canonical source URL drift")

    existing_selected_sha = str(row.get("selected_source_sha256") or "")
    existing_selected_bytes = str(row.get("selected_source_bytes") or "")
    if existing_selected_sha and existing_selected_sha != candidate_sha:
        raise ValueError(f"{aid}: non-empty selected source SHA conflicts with candidate evidence")
    if existing_selected_bytes and int(existing_selected_bytes) != candidate_bytes:
        raise ValueError(f"{aid}: non-empty selected source bytes conflict with candidate evidence")

    out = dict(row)
    out["selected_source_url"] = candidate_url
    out["selected_source_sha256"] = candidate_sha
    out["selected_source_bytes"] = str(candidate_bytes)
    return out


def build_input(documents_path: Path, evidence_path: Path, out_path: Path) -> dict:
    targets = load_targets(evidence_path)
    found: dict[str, dict[str, str]] = {}
    fieldnames: list[str] | None = None
    with gzip.open(documents_path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        required = {
            "announcement_id", "document_status", "tie_candidate_count", "tie_resolution",
            "candidate_evidence_json", "selected_source_url", "selected_source_sha256",
            "selected_source_bytes", "canonical_source_url",
        }
        missing = required - set(fieldnames)
        if missing:
            raise ValueError(f"accepted document ledger missing columns {sorted(missing)}")
        for row in reader:
            aid = str(row.get("announcement_id") or "")
            if aid not in targets:
                continue
            if aid in found:
                raise ValueError(f"duplicate target document row {aid}")
            found[aid] = normalize_row(row, targets[aid])

    if set(found) != set(targets):
        raise ValueError(f"missing target rows {sorted(set(targets)-set(found))}")
    assert fieldnames is not None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for aid in sorted(found):
            writer.writerow(found[aid])

    return {
        "target_count": len(found),
        "target_ids": sorted(found),
        "source_identity_origin": "SINGLE_CANDIDATE_EVIDENCE_JSON",
        "accepted_ledger_mutated": False,
        "temporary_diagnostic_input_only": True,
        "all_candidate_source_identities_match_governance_evidence": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--documents", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", required=True)
    args = ap.parse_args()
    summary = build_input(Path(args.documents), Path(args.evidence), Path(args.out))
    Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
