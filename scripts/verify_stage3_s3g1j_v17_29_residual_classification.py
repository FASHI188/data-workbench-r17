#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json

from deterministic_gzip_stored import gzip_store_bytes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True)
    args = ap.parse_args()

    for payload in (b"", b"abc", bytes(range(256)) * 1000):
        encoded = gzip_store_bytes(payload)
        assert gzip.decompress(encoded) == payload
    probe = b"cross-runtime-deterministic-gzip\n"
    assert hashlib.sha256(gzip_store_bytes(probe)).hexdigest() == "270063595724a07a7edc1bb35cdef64ef0d5db699ae596e757130908d732ef02"

    s = json.load(open(args.summary, encoding="utf-8"))
    assert s["gate"] == "S3G1J_V17_29_FULL_BASIS_RESIDUAL_CLASSIFICATION_V1"
    assert s["input_document_rows"] == 121354
    assert s["pass_document_rows"] == 119990
    assert s["residual_document_rows"] == 1364
    assert s["class_counts"] == {
        "CANONICAL_PDF_ISSUER_MISMATCH": 83,
        "MULTI_CANDIDATE_SOURCE_INCOMPLETE_2_CANDIDATES": 85,
        "MULTI_CANDIDATE_SOURCE_INCOMPLETE_3_CANDIDATES": 2,
        "MULTI_CANDIDATE_VALUE_CONFLICT": 14,
        "SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_2": 12,
        "SINGLE_CANONICAL_IDENTITY_MISMATCH_TIER2_3": 71,
        "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_0": 550,
        "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_1": 421,
        "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_2": 119,
        "SINGLE_CANONICAL_NO_VALIDATED_BLOCK_TIER2_3": 7,
    }
    assert s["priority_counts"] == {
        "P0_SAFE_NEAR_COMPLETE_NO_IDENTITY_CONFLICT": 7,
        "P1_IDENTITY_CONFLICT_TIER2_3": 71,
        "P2_SAFE_PARTIAL_TIER2_2": 119,
        "P3_IDENTITY_CONFLICT_LOWER_EVIDENCE": 12,
        "P3_SAFE_PARTIAL_TIER2_1": 421,
        "P3_SOURCE_COMPLETENESS_REVIEW": 87,
        "P4_ISSUER_AUTHORITY_REVIEW": 83,
        "P4_SAFE_PARTIAL_TIER2_0": 550,
        "P4_SOURCE_VALUE_CONFLICT_REVIEW": 14,
    }
    assert s["p0_safe_near_complete_count"] == 7
    assert s["p0_announcement_ids"] == [
        "1202799494", "1204077386", "1205543437", "1209806910",
        "1219834247", "1223347318", "1223407043",
    ]
    assert s["tie_taxonomy"] == {"TIE_SOURCE_INCOMPLETE": 1267, "TIE_VALUE_CONFLICT": 14}
    assert s["migration_counts"] == {"RECOVERED_EXITED_RESIDUAL": 7, "UNCHANGED": 1364}
    assert s["recovered_exit_announcement_ids"] == [
        "1215186538", "1219426855", "1219792633", "1219840508",
        "1219879687", "1220087244", "1221006100",
    ]
    assert s["new_residual_count"] == 0
    assert s["common_residual_reclassification_count"] == 0
    assert s["classification_ledger_sha256"] == "31be1e40330be6b149e4eb630339131258b4212d1639e13bead207feae50afe5"
    assert s["classification_ledger_gzip_sha256"] == "34483c4096e21d943321bc12961a35a0685393401ee64b226a9a079255433bab"
    assert s["p0_ledger_sha256"] == "6c5866e3fdbf6381bb0b982b8642aa9c4d5ce9833469a97bcceda6dbea1d5633"
    assert s["p0_ledger_gzip_sha256"] == "a64a1ce56761b3c135e68cd89b79cb458f8fc65f6f8b5b8255dfb8b18f45c61b"
    assert s["migration_ledger_sha256"] == "c63b792afc9e3a29c073fa284ba5e7c4059426c16d40c4855bc39c904f29abe4"
    assert s["migration_ledger_gzip_sha256"] == "ca09698316d5c0460e926a1d5d2d33a46f3c78720ca9b1b9c2d32a800a05f784"
    assert s["production_data_changed"] is False
    assert s["parser_changed"] is False
    assert s["runtime_authority_changed"] is False
    assert s["stage3_status"] == "NOT_READY"
    assert s["stage4_alpha_locked"] is True
    assert s["pass"] is True and s["errors"] == []
    print(json.dumps(s, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
