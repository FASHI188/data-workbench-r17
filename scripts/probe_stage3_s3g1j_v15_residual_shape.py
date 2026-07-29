#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ERROR_RE = re.compile(
    r"\b(?P<announcement_id>\d{10})\s+"
    r"(?P<resolution>TIE_SOURCE_INCOMPLETE|CANONICAL_PDF_ISSUER_MISMATCH|TIE_VALUE_CONFLICT|SOURCE_ERROR):"
)


def stable_shard(announcement_id: str, shards: int = 64) -> int:
    return int(hashlib.sha256(announcement_id.encode()).hexdigest()[:16], 16) % shards


def read_versions(path: Path) -> dict[str, dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return {r["canonical_announcement_id"]: r for r in csv.DictReader(f)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", required=True)
    ap.add_argument("--run-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    versions = read_versions(Path(args.versions))
    text = Path(args.run_log).read_text(encoding="utf-8", errors="replace")

    # A manifest error is printed once inside its shard job. Deduplicate defensively
    # by (announcement_id, resolution) in case GitHub repeats a buffered log line.
    hits = {}
    for m in ERROR_RE.finditer(text):
        aid = m.group("announcement_id")
        resolution = m.group("resolution")
        shard = stable_shard(aid)
        if shard not in {0, 1, 7, 9}:
            continue
        hits[(aid, resolution)] = {"announcement_id": aid, "resolution": resolution, "shard": shard}

    rows = []
    resolution_counts = Counter()
    source_shape_counts = Counter()
    by_shard = Counter()
    missing_versions = []

    for _, hit in sorted(hits.items(), key=lambda item: (item[1]["shard"], item[1]["announcement_id"], item[1]["resolution"])):
        aid = hit["announcement_id"]
        version = versions.get(aid)
        if version is None:
            missing_versions.append(aid)
            tied_count = None
            shape = "VERSION_ROW_MISSING"
        else:
            tied_count = int(version.get("same_day_tied_top_count") or "1")
            shape = "TRUE_SAME_MOMENT_TIE" if tied_count > 1 else "SINGLE_CANONICAL_SOURCE"

        resolution_counts[hit["resolution"]] += 1
        source_shape_counts[f"{hit['resolution']}::{shape}"] += 1
        by_shard[(hit["shard"], hit["resolution"], shape)] += 1
        rows.append({
            **hit,
            "source_shape": shape,
            "same_day_tied_top_count": tied_count,
            "source_code": version.get("source_code") if version else None,
            "report_family": version.get("report_family") if version else None,
            "economic_date": version.get("economic_date") if version else None,
            "canonical_title": version.get("canonical_title") if version else None,
            "same_day_tied_top_ids": version.get("same_day_tied_top_ids") if version else None,
            "same_day_tied_top_titles": version.get("same_day_tied_top_titles") if version else None,
        })

    report = {
        "gate": "S3G1J_V15_V13_REPRESENTATIVE_RESIDUAL_SHAPE",
        "diagnostic_pass": not missing_versions,
        "v13_smoke_target_shards": [0, 1, 7, 9],
        "unique_error_records": len(rows),
        "resolution_counts": dict(sorted(resolution_counts.items())),
        "source_shape_counts": dict(sorted(source_shape_counts.items())),
        "by_shard": {
            f"shard{shard}:{resolution}:{shape}": count
            for (shard, resolution, shape), count in sorted(by_shard.items())
        },
        "true_tie_error_count": sum(
            1 for r in rows if r["source_shape"] == "TRUE_SAME_MOMENT_TIE"
        ),
        "single_canonical_error_count": sum(
            1 for r in rows if r["source_shape"] == "SINGLE_CANONICAL_SOURCE"
        ),
        "rows": rows,
        "missing_version_rows": sorted(set(missing_versions)),
        "policy": {
            "reads_completed_v13_smoke_logs_only": True,
            "no_pdf_redownload": True,
            "same_day_tied_top_count_from_exact_v12_1_smoke_ledger": True,
            "diagnostic_only": True,
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["diagnostic_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
