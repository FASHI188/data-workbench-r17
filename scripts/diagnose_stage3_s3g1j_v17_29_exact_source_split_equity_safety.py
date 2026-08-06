#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

FULL_DOCUMENTS_GZIP_SHA256 = "7589750684ec26280c095d4b3a2d21b114c6bb77a882f4633c2ea128de5f38f3"
FULL_DOCUMENTS_PLAINTEXT_SHA256 = "c4e251d769860f86f037889f0bcc58a76ee53526f1f0ac120aa2aa15a996cba5"
ROOT_CAUSE_GZIP_SHA256 = "e3ba4e23b81dcb24d24def114cd6a70289c2f7df654b1d81238638675ec1a92c"
ROOT_CAUSE_PLAINTEXT_SHA256 = "0861076fdf2547d1269df2b6c6000fbf1ea3b5998ad1658ae3c7fa028157ce1a"
FORMAL_V17_28_PARSER_BLOB_SHA = "b299accbd9b19c6f909b883738378b0119f855b9"
IDENTITY_TOLERANCE = Decimal("0.005")
FORMAL_V17_28_EXISTING_TARGET_SHAS = {
    "b2aa4afa67e2b02010d5ba708d4e5fe02138623ff4bc48718c03029111a64568",
    "0bd1da8bdac0aff2a3e99b83adc29e7b60e959c99dd29b8ab88cbda1344b441c",
}
SAFE_IDS = (
    "1215186538",
    "1219426855",
    "1219792633",
    "1219840508",
    "1219879687",
    "1220087244",
    "1221006100",
)
TARGET_FIELDS = [
    "announcement_id", "source_code", "report_family", "economic_date",
    "canonical_source_url", "source_sha256", "source_bytes", "page_count",
    "group_asset_current", "group_asset_prior", "group_liability_current",
    "group_liability_prior", "group_equity_current", "group_equity_prior",
    "current_identity_residual", "prior_identity_residual",
    "population_match_count", "route", "candidate_experiment_eligible",
    "candidate_parser_implementation_authorized",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_gzip_plaintext(path: Path) -> str:
    h = hashlib.sha256()
    with gzip.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def deterministic_csv_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=TARGET_FIELDS, lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: row.get(key, "") for key in TARGET_FIELDS})


def load_root_cause(path: Path) -> dict[str, dict[str, str]]:
    if sha256_file(path) != ROOT_CAUSE_GZIP_SHA256:
        raise ValueError("root-cause ledger gzip SHA mismatch")
    if sha256_gzip_plaintext(path) != ROOT_CAUSE_PLAINTEXT_SHA256:
        raise ValueError("root-cause ledger plaintext SHA mismatch")
    rows: dict[str, dict[str, str]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            aid = row["announcement_id"]
            if aid in rows:
                raise ValueError(f"duplicate root-cause row {aid}")
            rows[aid] = row
    safe = tuple(sorted(aid for aid, row in rows.items() if row["classification"] == "SAFE_EXACT_SOURCE_CANDIDATE"))
    if safe != SAFE_IDS:
        raise ValueError(f"safe population drift {safe}")
    return rows


def target_map(root_rows: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for aid in SAFE_IDS:
        row = root_rows[aid]
        sha = row["source_sha256"]
        if len(sha) != 64 or sha in targets:
            raise ValueError(f"invalid or duplicate source SHA {aid}")
        if sha in FORMAL_V17_28_EXISTING_TARGET_SHAS:
            raise ValueError(f"new target overlaps formal V17.28 target {aid}")
        if row["source_identity_locked"] != "True":
            raise ValueError(f"source identity not locked {aid}")
        if row["current_identity_residual"] != "0.00" or row["prior_identity_residual"] != "0.00":
            raise ValueError(f"identity residual changed {aid}")
        values = {
            concept: [row[f"group_{concept}_current"], row[f"group_{concept}_prior"]]
            for concept in ("asset", "liability", "equity")
        }
        for index in range(2):
            residual = Decimal(values["asset"][index]) - Decimal(values["liability"][index]) - Decimal(values["equity"][index])
            relative = abs(residual) / max(abs(Decimal(values["asset"][index])), Decimal("1"))
            if residual != 0 or relative > IDENTITY_TOLERANCE:
                raise ValueError(f"dual-column identity changed {aid}")
        targets[sha] = {
            "announcement_id": aid,
            "source_code": row["source_code"],
            "report_family": row["report_family"],
            "economic_date": row["economic_date"],
            "canonical_source_url": row["canonical_source_url"],
            "source_sha256": sha,
            "source_bytes": int(row["source_bytes"]),
            "page_count": int(row["page_count"]),
            "values": values,
        }
    return targets


def route_source(source_sha256: str, source_bytes: int, economic_date: str, targets: dict[str, dict[str, Any]]) -> str:
    target = targets.get(source_sha256)
    if target is None:
        return "DELEGATE_FORMAL_V17_28_UNCHANGED"
    if int(source_bytes) != target["source_bytes"] or economic_date != target["economic_date"]:
        return "DELEGATE_FORMAL_V17_28_UNCHANGED"
    return "V17_29_PRE_CANDIDATE_EXACT_SOURCE_DIAGNOSTIC"


def dispatch_contract(
    formal_result: dict[str, Any],
    source_sha256: str,
    source_bytes: int,
    economic_date: str,
    targets: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Model the future wrapper boundary without implementing a parser.

    A non-target returns the exact same formal V17.28 object. A target returns
    only a diagnostic envelope; this function never extracts or promotes values.
    """
    route = route_source(source_sha256, source_bytes, economic_date, targets)
    if route == "DELEGATE_FORMAL_V17_28_UNCHANGED":
        return formal_result
    return {
        "route": route,
        "formal_result": formal_result,
        "candidate_parser_implementation_authorized": False,
    }


def candidate_identities(row: dict[str, str]) -> list[dict[str, Any]]:
    items = json.loads(row.get("candidate_evidence_json") or "[]")
    if not isinstance(items, list):
        raise ValueError(f"candidate evidence is not list {row.get('announcement_id')}")
    return [item for item in items if isinstance(item, dict)]


def scan_population(documents: Path, targets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if sha256_file(documents) != FULL_DOCUMENTS_GZIP_SHA256:
        raise ValueError("full documents gzip SHA mismatch")
    if sha256_gzip_plaintext(documents) != FULL_DOCUMENTS_PLAINTEXT_SHA256:
        raise ValueError("full documents plaintext SHA mismatch")
    target_hits: dict[str, list[dict[str, Any]]] = {sha: [] for sha in targets}
    route_counts: Counter[str] = Counter()
    routing_hash = hashlib.sha256()
    row_count = 0
    candidate_count = 0
    with gzip.open(documents, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            row_count += 1
            candidates = candidate_identities(row)
            candidate_count += len(candidates)
            matched: list[tuple[str, dict[str, Any]]] = []
            for item in candidates:
                sha = str(item.get("sha256") or "")
                route = route_source(sha, int(item.get("bytes") or 0), row["economic_date"], targets)
                if route != "DELEGATE_FORMAL_V17_28_UNCHANGED":
                    matched.append((sha, item))
            if len(matched) > 1:
                raise ValueError(f"multiple safe routes in document {row['announcement_id']}")
            document_route = "DELEGATE_FORMAL_V17_28_UNCHANGED"
            if matched:
                sha, item = matched[0]
                target = targets[sha]
                if row["announcement_id"] != target["announcement_id"]:
                    raise ValueError(f"safe SHA mapped to wrong document {row['announcement_id']}")
                if str(item.get("id") or "") != target["announcement_id"]:
                    raise ValueError(f"safe candidate ID mismatch {target['announcement_id']}")
                if str(item.get("url") or "") != target["canonical_source_url"]:
                    raise ValueError(f"safe candidate URL mismatch {target['announcement_id']}")
                if row["canonical_source_url"] != target["canonical_source_url"]:
                    raise ValueError(f"canonical URL mismatch {target['announcement_id']}")
                if row["document_status"] != "ERROR" or int(item.get("tier2_found") or 0) != 3:
                    raise ValueError(f"target formal baseline changed {target['announcement_id']}")
                target_hits[sha].append({
                    "announcement_id": row["announcement_id"],
                    "candidate_id": str(item.get("id") or ""),
                    "candidate_sha256": sha,
                    "candidate_bytes": int(item.get("bytes") or 0),
                    "economic_date": row["economic_date"],
                    "document_status": row["document_status"],
                    "tier2_found": int(item.get("tier2_found") or 0),
                })
                document_route = "V17_29_PRE_CANDIDATE_EXACT_SOURCE_DIAGNOSTIC"
            route_counts[document_route] += 1
            routing_hash.update(f"{row['announcement_id']}|{document_route}\n".encode("utf-8"))
    if row_count != 121354:
        raise ValueError(f"full population count changed {row_count}")
    if route_counts != Counter({
        "DELEGATE_FORMAL_V17_28_UNCHANGED": 121347,
        "V17_29_PRE_CANDIDATE_EXACT_SOURCE_DIAGNOSTIC": 7,
    }):
        raise ValueError(f"routing counts changed {dict(route_counts)}")
    for sha, matches in target_hits.items():
        if len(matches) != 1:
            raise ValueError(f"target population match count changed {targets[sha]['announcement_id']}={len(matches)}")
    return {
        "document_rows": row_count,
        "candidate_rows": candidate_count,
        "route_counts": dict(sorted(route_counts.items())),
        "routing_semantic_sha256": routing_hash.hexdigest(),
        "target_hits": target_hits,
    }


def negative_route_tests(targets: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for sha, target in targets.items():
        mutated_sha = ("0" if sha[0] != "0" else "1") + sha[1:]
        if route_source(mutated_sha, target["source_bytes"], target["economic_date"], targets) != "DELEGATE_FORMAL_V17_28_UNCHANGED":
            raise ValueError("mutated SHA escaped fail-closed route")
        counts["MUTATED_SHA_DELEGATED"] += 1
        if route_source(sha, target["source_bytes"] + 1, target["economic_date"], targets) != "DELEGATE_FORMAL_V17_28_UNCHANGED":
            raise ValueError("wrong byte length escaped fail-closed route")
        counts["WRONG_BYTES_DELEGATED"] += 1
        wrong_date = "1900-01-01" if target["economic_date"] != "1900-01-01" else "1900-01-02"
        if route_source(sha, target["source_bytes"], wrong_date, targets) != "DELEGATE_FORMAL_V17_28_UNCHANGED":
            raise ValueError("wrong economic date escaped fail-closed route")
        counts["WRONG_DATE_DELEGATED"] += 1
    return dict(sorted(counts.items()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--documents", required=True)
    ap.add_argument("--root-cause-ledger", required=True)
    ap.add_argument("--out-root", required=True)
    args = ap.parse_args()
    root_rows = load_root_cause(Path(args.root_cause_ledger))
    targets = target_map(root_rows)
    population = scan_population(Path(args.documents), targets)
    negative = negative_route_tests(targets)
    target_rows: list[dict[str, Any]] = []
    for sha in sorted(targets, key=lambda x: targets[x]["announcement_id"]):
        target = targets[sha]
        source = root_rows[target["announcement_id"]]
        target_rows.append({
            **{key: source[key] for key in TARGET_FIELDS if key in source},
            "population_match_count": len(population["target_hits"][sha]),
            "route": "V17_29_PRE_CANDIDATE_EXACT_SOURCE_DIAGNOSTIC",
            "candidate_experiment_eligible": True,
            "candidate_parser_implementation_authorized": False,
        })
    out = Path(args.out_root)
    out.mkdir(parents=True, exist_ok=True)
    ledger = out / "stage3_s3g1j_v17_29_exact_source_safety_targets.csv.gz"
    deterministic_csv_gz(ledger, target_rows)
    contract = {
        "gate": "S3G1J_V17_29_PRE_CANDIDATE_EXACT_SOURCE_SPLIT_EQUITY_SAFETY",
        "formal_runtime_generation": "V17.28",
        "formal_parser_blob_sha": FORMAL_V17_28_PARSER_BLOB_SHA,
        "target_count": 7,
        "target_announcement_ids": [row["announcement_id"] for row in target_rows],
        "target_sha256_by_announcement_id": {row["announcement_id"]: row["source_sha256"] for row in target_rows},
        "activation_identity": ["source_sha256", "source_bytes", "economic_date"],
        "activation_rule_scope": "EXACT_ALLOWLIST_ONLY",
        "non_target_behavior": "RETURN_FORMAL_V17_28_OBJECT_UNCHANGED",
        "formal_existing_target_overlap_count": 0,
        "candidate_experiment_eligible": True,
        "candidate_parser_implementation_authorized": False,
        "candidate_parser_promotion_authorized": False,
        "next_gate": "SEPARATE_CANDIDATE_IMPLEMENTATION_PR_WITH_EXACT_NON_TARGET_OUTPUT_REGRESSION",
    }
    contract_path = out / "stage3_s3g1j_v17_29_exact_source_safety_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "gate": contract["gate"],
        "source_full_documents_artifact_id": 8927455692,
        "source_root_cause_artifact_id": 8971708686,
        "full_population_document_rows": population["document_rows"],
        "full_population_candidate_rows": population["candidate_rows"],
        "route_counts": population["route_counts"],
        "routing_semantic_sha256": population["routing_semantic_sha256"],
        "target_population_match_count": 7,
        "all_target_population_matches_unique": True,
        "all_non_targets_delegate_formal_v17_28_unchanged": True,
        "negative_route_counts": negative,
        "target_ledger_gzip_sha256": sha256_file(ledger),
        "target_ledger_plaintext_sha256": sha256_gzip_plaintext(ledger),
        "contract_sha256": sha256_file(contract_path),
        "gzip_mtime": 0,
        "gzip_embedded_filename": "",
        "pdf_binaries_redownloaded": False,
        "ocr_used": False,
        "equity_inferred_from_assets_minus_liabilities": False,
        "fuzzy_alias_matching_enabled": False,
        "source_policy_changed": False,
        "point_in_time_policy_changed": False,
        "issuer_gate_changed": False,
        "accounting_tolerance": str(IDENTITY_TOLERANCE),
        "accounting_tolerance_changed": False,
        "parser_implemented": False,
        "runtime_authority_changed": False,
        "production_data_changed": False,
        "candidate_experiment_eligible": True,
        "candidate_parser_implementation_authorized": False,
        "stage3_status": "NOT_READY",
        "stage4_alpha_live_locked": True,
        "pass": True,
        "errors": [],
    }
    summary_path = out / "stage3_s3g1j_v17_29_exact_source_safety_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
