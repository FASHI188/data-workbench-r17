#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

FIELDS = [
    "exchange",
    "effective_code",
    "economic_date",
    "effective_session",
    "announcement_id",
    "revision_sequence",
    "report_family",
    "concept",
    "normalized_cny_value",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def project_one(src: Path, dst: Path) -> tuple[int, str]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with gzip.open(src, "rt", encoding="utf-8", newline="") as inp:
        reader = csv.DictReader(inp)
        if reader.fieldnames is None:
            raise ValueError(f"missing CSV header: {src}")
        missing = [field for field in FIELDS if field not in reader.fieldnames]
        if missing:
            raise ValueError(f"missing required fields in {src}: {missing}")
        raw_buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=raw_buffer, mode="wb", compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="", write_through=True) as text:
                writer = csv.DictWriter(
                    text,
                    fieldnames=FIELDS,
                    extrasaction="ignore",
                    quoting=csv.QUOTE_MINIMAL,
                    lineterminator="\n",
                )
                writer.writeheader()
                for row in reader:
                    writer.writerow({field: row.get(field, "") for field in FIELDS})
                    count += 1
        dst.write_bytes(raw_buffer.getvalue())
    return count, sha256_file(dst)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--historical", required=True)
    ap.add_argument("--forward-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expected-historical-rows", type=int, required=True)
    ap.add_argument("--expected-forward-rows", type=int, required=True)
    ap.add_argument("--expected-forward-shards", type=int, required=True)
    args = ap.parse_args()

    historical = Path(args.historical)
    forward_files = sorted(Path(args.forward_root).glob("financial_values_shard*.csv.gz"))
    if len(forward_files) != args.expected_forward_shards:
        raise ValueError(
            f"forward shard count mismatch expected={args.expected_forward_shards} actual={len(forward_files)}"
        )

    out = Path(args.out)
    hist_dst = out / "historical" / historical.name
    hist_rows, hist_sha = project_one(historical, hist_dst)

    forward_rows = 0
    forward_outputs = []
    for src in forward_files:
        dst = out / "forward" / src.name
        rows, sha = project_one(src, dst)
        forward_rows += rows
        forward_outputs.append({"source": src.name, "output": dst.name, "rows": rows, "sha256": sha})

    report = {
        "gate": "STAGE4_FINANCIAL_MATRIX_INPUT_PROJECTION",
        "pass": hist_rows == args.expected_historical_rows and forward_rows == args.expected_forward_rows,
        "parser": "PYTHON_STDLIB_CSV_RFC4180",
        "projection_fields": FIELDS,
        "row_filtering": False,
        "row_reordering": False,
        "value_transformation": False,
        "historical": {
            "rows": hist_rows,
            "expected_rows": args.expected_historical_rows,
            "sha256": hist_sha,
            "output": str(hist_dst),
        },
        "forward": {
            "rows": forward_rows,
            "expected_rows": args.expected_forward_rows,
            "shards": len(forward_files),
            "expected_shards": args.expected_forward_shards,
            "outputs": forward_outputs,
        },
        "alpha_training_allowed": False,
        "live_signal_allowed": False,
        "authoritative_model_output": False,
    }
    report_path = out / "projection_audit.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
