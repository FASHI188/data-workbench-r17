from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from build_forward_lifecycle_seed import build_rows, load_manifest, normalize_date


def test_normalize_date_accepts_exchange_formats() -> None:
    assert normalize_date("20260806") == "2026-08-06"
    assert normalize_date("2026-08-04") == "2026-08-04"


def test_build_forward_seed_uses_fresh_master_identity(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "hard_gate_status": "PASS_CANDIDATE",
        "sse": {"sha256_raw": "a" * 64, "url": "https://sse.example"},
        "szse": {"sha256_all_pages": "b" * 64, "url_template": "https://szse.example/{page}", "as_of": "2026-08-12"},
    }), encoding="utf-8")
    master_path = tmp_path / "cn_main_a.csv"
    fields = ["exchange","board","security_type","code","name","listing_date","source_url","source_row_json","board_basis"]
    with master_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        w.writerow({"exchange":"SSE","board":"MAIN","security_type":"A_SHARE","code":"603468","name":"C津富","listing_date":"20260806","source_url":"https://sse.example","source_row_json":json.dumps({"A_STOCK_CODE":"603468"}),"board_basis":"OFFICIAL"})
        w.writerow({"exchange":"SZSE","board":"MAIN","security_type":"A_SHARE","code":"001232","name":"嘉立创","listing_date":"2026-08-04","source_url":"https://szse.example/1","source_row_json":json.dumps({"agdm":"001232"}),"board_basis":"OFFICIAL"})
    rows = build_rows(master_path, load_manifest(manifest_path))
    assert [(r["exchange"], r["code"], r["effective_date"]) for r in rows] == [
        ("SSE", "603468", "2026-08-06"),
        ("SZSE", "001232", "2026-08-04"),
    ]
    assert rows[0]["source_sha256"] == "a" * 64
    assert rows[1]["source_sha256"] == "b" * 64


def test_forward_seed_rejects_non_candidate_manifest(tmp_path: Path) -> None:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"hard_gate_status":"PENDING","sse":{"sha256_raw":"a"*64},"szse":{"sha256_all_pages":"b"*64}}), encoding="utf-8")
    with pytest.raises(ValueError, match="PASS_CANDIDATE"):
        load_manifest(p)
