#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SOURCE = Path(__file__).with_name("build_stage4_v1_feature_matrix.py")
EXPECTED_SOURCE_SHA256 = "eb91749f9d21a6f0c56ddeddfdb4d2b046447437c7b9f1d995a0a19d68fa008b"
OLD = "SELECT count(*) rows,"
NEW = "SELECT count(*) AS row_count,"


def main() -> None:
    raw = SOURCE.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != EXPECTED_SOURCE_SHA256:
        raise SystemExit(
            f"refusing compatibility patch: source sha mismatch expected={EXPECTED_SOURCE_SHA256} actual={actual}"
        )
    text = raw.decode("utf-8")
    if text.count(OLD) != 1:
        raise SystemExit(f"refusing compatibility patch: expected exactly one alias target, got {text.count(OLD)}")
    patched = text.replace(OLD, NEW, 1)
    patched_sha = hashlib.sha256(patched.encode("utf-8")).hexdigest()
    print(
        f"STAGE4_MATRIX_R3_EXACT_ALIAS_PATCH source_sha256={actual} patched_sha256={patched_sha}",
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
