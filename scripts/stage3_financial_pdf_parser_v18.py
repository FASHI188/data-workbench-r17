#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
from decimal import Decimal

import stage3_financial_pdf_parser_v17 as accepted

METHOD = "V17_26_EXACT_SOURCE_BALANCE_ONLY_PRODUCTION"
ALLOWED_CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
FILTER_REASON = "V17_26_EXACT_SOURCE_UNVALIDATED_NON_BALANCE_CONCEPT"

TARGETS = {
    "320e3a950a4768e73766d57a09bcf34d893d4da949b8ed5a1b2f887852e76229": {
        "economic_date": "2019-09-30",
        "announcement_id": "1207035181",
        "values": {
            "TOTAL_ASSETS": "760508375.73",
            "TOTAL_LIABILITIES": "176499397.46",
            "TOTAL_EQUITY": "584008978.27",
        },
    },
    "fa72059d35715f20df620691538528f720fe3ae42581c172c853f26799befb93": {
        "economic_date": "2024-09-30",
        "announcement_id": "1221568845",
        "values": {
            "TOTAL_ASSETS": "3642768851.01",
            "TOTAL_LIABILITIES": "2382626915.88",
            "TOTAL_EQUITY": "1260141935.13",
        },
    },
}


def _validate_target(parsed: dict, target: dict) -> None:
    if list(parsed.get("validation_errors") or []):
        raise ValueError(
            f"V17.26 target retained validation errors {target['announcement_id']}"
        )
    block = parsed.get("balance_sheet_block")
    if not isinstance(block, dict):
        raise ValueError(
            f"V17.26 target lacks validated balance block {target['announcement_id']}"
        )
    if Decimal(str(block.get("identity_relative_error"))) != Decimal("0"):
        raise ValueError(
            f"V17.26 target identity is not exact {target['announcement_id']}"
        )
    if block.get("column_role_gate_pass") is not True:
        raise ValueError(
            f"V17.26 target column-role gate failed {target['announcement_id']}"
        )

    observations = parsed.get("observations") or {}
    for concept, expected in target["values"].items():
        observation = observations.get(concept) or {}
        if observation.get("status") != "FOUND":
            raise ValueError(
                f"V17.26 target missing validated concept "
                f"{target['announcement_id']} {concept}"
            )
        actual = str(observation.get("normalized_cny_value", ""))
        if Decimal(actual) != Decimal(expected):
            raise ValueError(
                f"V17.26 target value mismatch {target['announcement_id']} {concept} "
                f"expected={expected} actual={actual}"
            )


def _balance_only(parsed: dict, digest: str, target: dict) -> dict:
    _validate_target(parsed, target)
    out = copy.deepcopy(parsed)
    observations = out.get("observations") or {}
    filtered: list[str] = []
    scoped: dict[str, dict] = {}
    for concept, observation in observations.items():
        if concept in ALLOWED_CONCEPTS:
            scoped[concept] = copy.deepcopy(observation)
            continue
        if (observation or {}).get("status") == "FOUND":
            filtered.append(concept)
        scoped[concept] = {
            "status": "NOT_FOUND",
            "reason": FILTER_REASON,
        }
    for concept in ALLOWED_CONCEPTS:
        if concept not in scoped:
            raise ValueError(
                f"V17.26 target observation map missing {concept} "
                f"{target['announcement_id']}"
            )

    block = copy.deepcopy(out["balance_sheet_block"])
    block["production_runtime_generation"] = "V17.26"
    block["exact_source_sha256"] = digest
    block["validated_observation_scope"] = list(ALLOWED_CONCEPTS)
    block["filtered_unvalidated_concepts"] = sorted(filtered)
    block["non_balance_values_promoted"] = False

    out["observations"] = scoped
    out["tier1_found"] = 0
    out["tier2_found"] = len(ALLOWED_CONCEPTS)
    out["parser_version"] = METHOD
    out["balance_sheet_block"] = block
    out["validation_errors"] = []
    return out


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    """Preserve V17.25 globally and narrow two exact-source recoveries to A/L/E.

    The two source-locked documents were accepted only on balance-sheet evidence.
    Other parsed concepts are therefore not promoted merely because the document's
    A=L+E block became valid. Every non-target PDF returns the accepted V17.25
    result object unchanged.
    """
    parsed = dict(accepted.parse_pdf_bytes(raw, economic_date))
    digest = hashlib.sha256(raw).hexdigest()
    target = TARGETS.get(digest)
    if target is None or economic_date != target["economic_date"]:
        return parsed
    return _balance_only(parsed, digest, target)
