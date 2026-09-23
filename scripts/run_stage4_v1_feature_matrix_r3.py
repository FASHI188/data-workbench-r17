#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SOURCE = Path(__file__).with_name("build_stage4_v1_feature_matrix.py")
EXPECTED_SOURCE_GIT_BLOB_SHA1 = "6ee96c9a1f822e47c1acd24d71f5476642f36acf"
OLD = "SELECT count(*) rows,"
NEW = "SELECT count(*) AS row_count,"


def git_blob_sha1(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def main() -> None:
    raw = SOURCE.read_bytes()
    actual_blob = git_blob_sha1(raw)
    if actual_blob != EXPECTED_SOURCE_GIT_BLOB_SHA1:
        raise SystemExit(
            "refusing compatibility patch: source git blob mismatch "
            f"expected={EXPECTED_SOURCE_GIT_BLOB_SHA1} actual={actual_blob}"
        )
    text = raw.decode("utf-8")
    if text.count(OLD) != 1:
        raise SystemExit(f"refusing compatibility patch: expected exactly one alias target, got {text.count(OLD)}")
    patched = text.replace(OLD, NEW, 1)
    patched_sha256 = hashlib.sha256(patched.encode("utf-8")).hexdigest()
    print(
        "STAGE4_MATRIX_R3_EXACT_ALIAS_PATCH "
        f"source_git_blob_sha1={actual_blob} patched_sha256={patched_sha256}",
        file=sys.stderr,
    )
    namespace = {
        "__name__": "__main__",
        "__file__": str(SOURCE),
        "__package__": None,
    }
    exec(compile(patched, str(SOURCE), "exec"), namespace, namespace)


if __name__ == "__main__":
    main()
