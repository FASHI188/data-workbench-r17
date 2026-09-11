#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import promote_stage3_s3g1j_v17_26_full_shards as v1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--target-values", required=True)
    parser.add_argument("--target-documents", required=True)
    parser.add_argument("--out-report", required=True)
    parser.add_argument("--source-run", type=int, default=30692117760)
    args = parser.parse_args()

    root = Path(args.root)
    target_docs, target_values = v1.load_target_evidence(
        Path(args.target_values), Path(args.target_documents)
    )

    manifests = sorted(root.rglob("financial_extract_shard*.manifest.json"))
    if len(manifests) != 64:
        raise ValueError(f"expected 64 source manifests, got {len(manifests)}")
    identities = [v1.shard_id(path) for path in manifests]
    if sorted(identities) != list(range(64)) or len(set(identities)) != 64:
        raise ValueError(f"source shard identities changed {identities}")

    target_locations: dict[str, int] = {}
    previous_target_numeric_counts = {aid: 0 for aid in v1.TARGETS}
    promoted_numeric_total = 0
    promoted_document_total = 0
    promoted_document_error_total = 0
    source_document_error_total = 0

    for manifest_path in manifests:
        shard = v1.shard_id(manifest_path)
        directory = manifest_path.parent
        numeric_path = directory / f"financial_values_shard{shard:02d}.csv.gz"
        docs_path = directory / f"financial_documents_shard{shard:02d}.csv.gz"
        if not numeric_path.exists() or not docs_path.exists():
            raise ValueError(f"missing source shard files {shard}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if int(manifest.get("shards", -1)) != 64:
            raise ValueError(f"source shard geometry changed {shard}")
        if manifest.get("runtime_generation") != "V17.25":
            raise ValueError(f"source shard generation changed {shard}")
        if manifest.get("gate") != "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_25":
            raise ValueError(f"source shard gate changed {shard}")
        if manifest.get("source_format") != "PDF":
            raise ValueError(f"source shard format changed {shard}")
        if manifest.get("original_pdf_authority") is not True:
            raise ValueError(f"source PDF authority changed {shard}")
        if manifest.get("current_f10_historical_backfill_used") is not False:
            raise ValueError(f"source F10 policy changed {shard}")
        if manifest.get("stage4_alpha_locked") is not True:
            raise ValueError(f"source Stage4/Alpha lock changed {shard}")

        docs = v1.read_gz(docs_path)
        numeric = v1.read_gz(numeric_path)
        if len(docs) != int(manifest["document_rows"]):
            raise ValueError(f"source document count mismatch shard {shard}")
        if len(numeric) != int(manifest["numeric_rows"]):
            raise ValueError(f"source numeric count mismatch shard {shard}")
        if v1.sha256(docs_path) != manifest.get("documents_sha256"):
            raise ValueError(f"source document SHA mismatch shard {shard}")
        if v1.sha256(numeric_path) != manifest.get("numeric_sha256"):
            raise ValueError(f"source numeric SHA mismatch shard {shard}")

        source_document_errors = sum(
            row["document_status"] != "PASS" or bool(row["document_error"])
            for row in docs
        )
        source_error_count = int(manifest.get("error_count", -1))
        source_errors = list(manifest.get("errors") or [])
        if source_error_count != source_document_errors:
            raise ValueError(
                f"source shard document-error count mismatch {shard}: "
                f"manifest={source_error_count} rows={source_document_errors}"
            )
        if len(source_errors) != source_error_count:
            raise ValueError(f"source shard error ledger mismatch {shard}")
        if (manifest.get("pass") is True) != (source_error_count == 0):
            raise ValueError(f"source shard pass/error semantics changed {shard}")
        source_document_error_total += source_document_errors

        found_targets = [
            row["announcement_id"]
            for row in docs
            if row["announcement_id"] in v1.TARGETS
        ]
        for aid in found_targets:
            if aid in target_locations:
                raise ValueError(f"duplicate target document across shards {aid}")
            target_locations[aid] = shard

        for row in numeric:
            aid = row["announcement_id"]
            if aid in previous_target_numeric_counts:
                previous_target_numeric_counts[aid] += 1

        docs = [row for row in docs if row["announcement_id"] not in v1.TARGETS]
        numeric = [row for row in numeric if row["announcement_id"] not in v1.TARGETS]
        for row in numeric:
            row["extraction_method"] = v1.METHOD
            row["methodology_version"] = v1.METHODOLOGY

        for aid, location in target_locations.items():
            if location == shard:
                docs.append(dict(target_docs[aid]))
                numeric.extend(dict(row) for row in target_values[aid])

        docs.sort(key=lambda row: row["announcement_id"])
        numeric.sort(key=lambda row: (row["announcement_id"], row["concept"]))
        v1.write_gz(docs_path, v1.DOC_FIELDS, docs)
        v1.write_gz(numeric_path, v1.NUMERIC_FIELDS, numeric)

        promoted_document_errors = sum(
            row["document_status"] != "PASS" or bool(row["document_error"])
            for row in docs
        )
        if promoted_document_errors != source_document_errors:
            raise ValueError(
                f"promotion changed shard document errors {shard}: "
                f"source={source_document_errors} promoted={promoted_document_errors}"
            )

        manifest["gate"] = v1.GATE
        manifest["parser_method"] = v1.METHOD
        manifest["methodology_version"] = v1.METHODOLOGY
        manifest["runtime_generation"] = v1.GENERATION
        manifest["document_rows"] = len(docs)
        manifest["numeric_rows"] = len(numeric)
        manifest["numeric_sha256"] = v1.sha256(numeric_path)
        manifest["documents_sha256"] = v1.sha256(docs_path)
        manifest["pass"] = promoted_document_errors == 0
        manifest["error_count"] = promoted_document_errors
        manifest["source_full_run"] = args.source_run
        manifest["document_error_count"] = promoted_document_errors
        manifest["exact_source_balance_only_targets"] = sorted(v1.TARGETS)
        manifest["non_balance_values_promoted_for_targets"] = False
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        promoted_numeric_total += len(numeric)
        promoted_document_total += len(docs)
        promoted_document_error_total += promoted_document_errors

    if set(target_locations) != set(v1.TARGETS):
        raise ValueError(f"target shard population changed {target_locations}")
    if previous_target_numeric_counts != {aid: 9 for aid in v1.TARGETS}:
        raise ValueError(
            f"source target numeric population changed {previous_target_numeric_counts}"
        )
    if source_document_error_total != 1378:
        raise ValueError(
            f"source document error total changed {source_document_error_total}"
        )
    if promoted_document_total != 121354:
        raise ValueError(f"promoted document total changed {promoted_document_total}")
    if promoted_numeric_total != 1051778:
        raise ValueError(f"promoted numeric total changed {promoted_numeric_total}")
    if promoted_document_error_total != 1378:
        raise ValueError(
            f"promoted document error total changed {promoted_document_error_total}"
        )

    report = {
        "gate": "S3G1J_V17_26_FULL_SHARD_EVIDENCE_PROMOTION_V3",
        "pass": True,
        "source_run": args.source_run,
        "source_generation": "V17.25",
        "promoted_generation": v1.GENERATION,
        "shard_count": 64,
        "target_shard_locations": target_locations,
        "previous_target_numeric_counts": previous_target_numeric_counts,
        "promoted_target_numeric_counts": {aid: 3 for aid in v1.TARGETS},
        "document_rows": promoted_document_total,
        "numeric_rows": promoted_numeric_total,
        "source_document_errors": source_document_error_total,
        "promoted_document_errors": promoted_document_error_total,
        "non_target_values_changed": False,
        "non_balance_values_promoted_for_targets": False,
        "errors": [],
    }
    out = Path(args.out_report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
