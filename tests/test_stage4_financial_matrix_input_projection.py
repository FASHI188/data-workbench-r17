from __future__ import annotations

import csv
import gzip
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from project_stage4_financial_matrix_input import FIELDS, project_one


def write_source(path: Path) -> None:
    source_fields = FIELDS + ["raw_value", "unused_evidence"]
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=source_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow({
            "exchange": "SSE",
            "effective_code": "600000",
            "economic_date": "2025-12-31",
            "effective_session": "2026-04-01",
            "announcement_id": "123",
            "revision_sequence": "1",
            "report_family": "ANNUAL",
            "concept": "TOTAL_ASSETS",
            "normalized_cny_value": "5470381065.66",
            "raw_value": "5,470,381,065.66",
            "unused_evidence": "quoted,comma,value",
        })


def test_projection_parses_rfc4180_embedded_commas_and_keeps_required_values(tmp_path: Path) -> None:
    src = tmp_path / "source.csv.gz"
    dst = tmp_path / "projected.csv.gz"
    write_source(src)
    rows, sha = project_one(src, dst)
    assert rows == 1
    assert len(sha) == 64
    with gzip.open(dst, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == FIELDS
        row = next(reader)
        assert row["normalized_cny_value"] == "5470381065.66"
        assert row["announcement_id"] == "123"
        assert "raw_value" not in row
        assert list(reader) == []


def test_projection_is_deterministic(tmp_path: Path) -> None:
    src = tmp_path / "source.csv.gz"
    a = tmp_path / "a.csv.gz"
    b = tmp_path / "b.csv.gz"
    write_source(src)
    _, sha_a = project_one(src, a)
    _, sha_b = project_one(src, b)
    assert sha_a == sha_b
    assert a.read_bytes() == b.read_bytes()


def test_projection_fails_if_required_field_is_missing(tmp_path: Path) -> None:
    src = tmp_path / "bad.csv.gz"
    dst = tmp_path / "out.csv.gz"
    with gzip.open(src, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[x for x in FIELDS if x != "effective_session"])
        writer.writeheader()
    try:
        project_one(src, dst)
    except ValueError as exc:
        assert "effective_session" in str(exc)
    else:
        raise AssertionError("missing required PIT field must fail closed")
