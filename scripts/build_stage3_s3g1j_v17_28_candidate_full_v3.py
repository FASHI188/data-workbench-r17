#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

import build_stage3_s3g1j_v17_28_candidate_full as v1
import build_stage3_s3g1j_v17_28_candidate_full_v2 as v2


FULL_V17_27_NUMERIC_SEMANTIC_SHA256 = (
    "bcb154cc4d80a81acd409e64dc35c2902a5aeb37726b313df936717caf400672"
)
INHERITED_PRE_V17_27_NUMERIC_SEMANTIC_SHA256 = (
    "05b914b03dbcc23d3f6eca560189afbfe6ea427913f9cf1380fa09cdea6aa8d7"
)
INHERITED_PRE_V17_27_NUMERIC_ROWS = 1051778
FULL_V17_27_NUMERIC_ROWS = 1051793


def _argument_value(name: str) -> str:
    try:
        index = sys.argv.index(name)
    except ValueError as exc:
        raise ValueError(f"missing required argument {name}") from exc
    if index + 1 >= len(sys.argv):
        raise ValueError(f"missing value for argument {name}")
    return sys.argv[index + 1]


def main() -> int:
    # V1/V2 incorrectly compared the full accepted V17.27 ledger against the
    # inherited pre-V17.27 subset SHA. The immutable source gzip is already
    # locked; the full 1,051,793-row 22-field multiset has its own identity.
    v1.SOURCE_EXISTING_NUMERIC_SEMANTIC_SHA256 = (
        FULL_V17_27_NUMERIC_SEMANTIC_SHA256
    )
    code = v2.main()
    if code != 0:
        return code

    out = Path(_argument_value("--out"))
    report_path = out / "stage3_s3g1j_v17_28_candidate_safety.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    actual_source = report.get("source_existing_numeric_semantic_sha256")
    actual_candidate = report.get("candidate_existing_numeric_semantic_sha256")
    if actual_source != FULL_V17_27_NUMERIC_SEMANTIC_SHA256:
        raise ValueError(
            "full V17.27 source semantic SHA mismatch "
            f"expected={FULL_V17_27_NUMERIC_SEMANTIC_SHA256} actual={actual_source}"
        )
    if actual_candidate != FULL_V17_27_NUMERIC_SEMANTIC_SHA256:
        raise ValueError(
            "candidate existing semantic SHA mismatch "
            f"expected={FULL_V17_27_NUMERIC_SEMANTIC_SHA256} actual={actual_candidate}"
        )
    if FULL_V17_27_NUMERIC_ROWS - INHERITED_PRE_V17_27_NUMERIC_ROWS != 15:
        raise ValueError("V17.27 inherited/full numeric scope delta changed")
    if (
        FULL_V17_27_NUMERIC_SEMANTIC_SHA256
        == INHERITED_PRE_V17_27_NUMERIC_SEMANTIC_SHA256
    ):
        raise ValueError("distinct numeric populations share an impossible identity")

    report.update(
        {
            "gate": "S3G1J_V17_28_SPLIT_GROUP_EQUITY_CANDIDATE_SAFETY_V3",
            "failed_v2_contract_reason": (
                "V2 compared the complete accepted V17.27 1,051,793-row "
                "numeric population against the 1,051,778-row inherited "
                "pre-V17.27 semantic SHA. Both identities are valid for "
                "different populations."
            ),
            "numeric_semantic_identity_scope": {
                "full_v17_27_rows": FULL_V17_27_NUMERIC_ROWS,
                "full_v17_27_semantic_sha256": (
                    FULL_V17_27_NUMERIC_SEMANTIC_SHA256
                ),
                "inherited_pre_v17_27_rows": (
                    INHERITED_PRE_V17_27_NUMERIC_ROWS
                ),
                "inherited_pre_v17_27_semantic_sha256": (
                    INHERITED_PRE_V17_27_NUMERIC_SEMANTIC_SHA256
                ),
                "v17_27_added_rows": 15,
                "populations_must_not_be_interchanged": True,
            },
        }
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "gate": report["gate"],
                "full_v17_27_numeric_semantic_sha256": actual_source,
                "candidate_existing_numeric_semantic_sha256": actual_candidate,
                "inherited_pre_v17_27_numeric_semantic_sha256": (
                    INHERITED_PRE_V17_27_NUMERIC_SEMANTIC_SHA256
                ),
                "pass": report.get("pass"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
