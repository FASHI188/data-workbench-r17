#!/usr/bin/env python3
from __future__ import annotations

import classify_stage3_s3g1j_v17_29_residuals as classifier
from deterministic_gzip_stored import deterministic_csv_gz

classifier.deterministic_csv_gz = deterministic_csv_gz
classifier.EXPECTED_OUTPUT_HASHES = {
    "classification_ledger_sha256": "31be1e40330be6b149e4eb630339131258b4212d1639e13bead207feae50afe5",
    "classification_ledger_gzip_sha256": "34483c4096e21d943321bc12961a35a0685393401ee64b226a9a079255433bab",
    "p0_ledger_sha256": "6c5866e3fdbf6381bb0b982b8642aa9c4d5ce9833469a97bcceda6dbea1d5633",
    "p0_ledger_gzip_sha256": "a64a1ce56761b3c135e68cd89b79cb458f8fc65f6f8b5b8255dfb8b18f45c61b",
    "migration_ledger_sha256": "c63b792afc9e3a29c073fa284ba5e7c4059426c16d40c4855bc39c904f29abe4",
    "migration_ledger_gzip_sha256": "ca09698316d5c0460e926a1d5d2d33a46f3c78720ca9b1b9c2d32a800a05f784",
}

if __name__ == "__main__":
    raise SystemExit(classifier.main())
