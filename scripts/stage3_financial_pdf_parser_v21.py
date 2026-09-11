#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
from decimal import Decimal

import stage3_financial_pdf_parser_v21_promotion_safety as promotion

METHOD = "V17_29_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION"
METHODOLOGY_VERSION = "V3.3.13-V17.29"
ALLOWED_CONCEPTS = promotion.ALLOWED_CONCEPTS
TARGETS = promotion.TARGETS
IDENTITY_TOLERANCE = promotion.IDENTITY_TOLERANCE

PROMOTION_SAFETY_PR = 107
PROMOTION_SAFETY_HEAD = "4ea4ac01bcca3e580d73fc37378c2658df8f4b28"
PROMOTION_SAFETY_RUN = 31311296836
PROMOTION_SAFETY_ARTIFACT_ID = 9037500964
PROMOTION_SAFETY_ARTIFACT = "stage3-s3g1j-v17-29-production-promotion-safety"
PROMOTION_SAFETY_ARTIFACT_DIGEST = (
    "sha256:967727cf95d9cd5d923e4f59f9cbedfe3e17599ceb31a1df06fa607ab75c4d12"
)
PROMOTION_DOCUMENTS_SHA256 = (
    "4e5d853ae9ba16dbfd6f0ca11e2310f00539ad18c8dfdc2b654f601ccf876e40"
)
PROMOTION_VALUES_SHA256 = (
    "2bfdd607580f474a5d5b1c1acb80468bd31906ebdc1235c798c58e12afd30fef"
)
PROMOTION_REPORT_SHA256 = (
    "adcf8ad787957e1d9fba1961218de5919bbd202d33c51120dc811b0ed1de25fe"
)
PROMOTION_EVIDENCE_MANIFEST = (
    "governance/stage3_s3g1j_v17_29_production_promotion_safety.json"
)
PRODUCTION_SCOPE = "V17_29_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION"


def _zero(value: object) -> bool:
    try:
        return Decimal(str(value)) == Decimal("0")
    except Exception:
        return False


def _validate_promotion_output(parsed: dict, digest: str, target: dict) -> None:
    aid = target["announcement_id"]
    if parsed.get("parser_version") != promotion.METHOD:
        raise ValueError(f"V17.29 runtime requires accepted promotion-safety output {aid}")
    if list(parsed.get("validation_errors") or []):
        raise ValueError(f"V17.29 promotion-safety retained validation errors {aid}")
    if parsed.get("tier1_found") != 0 or parsed.get("tier2_found") != 3:
        raise ValueError(f"V17.29 promotion-safety tier counts changed {aid}")

    observations = parsed.get("observations") or {}
    found = {
        concept
        for concept, row in observations.items()
        if isinstance(row, dict) and row.get("status") == "FOUND"
    }
    if found != set(ALLOWED_CONCEPTS):
        raise ValueError(f"V17.29 promotion-safety concept scope changed {aid}: {sorted(found)}")
    for concept in ALLOWED_CONCEPTS:
        expected = target["values"][concept][0]
        actual = str((observations.get(concept) or {}).get("normalized_cny_value") or "")
        if actual != expected:
            raise ValueError(
                f"V17.29 promotion-safety value changed {aid} {concept}: "
                f"expected={expected} actual={actual}"
            )

    block = parsed.get("balance_sheet_block") or {}
    if block.get("candidate_only") is not False:
        raise ValueError(f"V17.29 promotion-safety candidate marker changed {aid}")
    if block.get("production_promotion_experiment_only") is not True:
        raise ValueError(f"V17.29 promotion-safety experiment marker missing {aid}")
    if block.get("runtime_promotion_authorized") is not False:
        raise ValueError(f"V17.29 promotion-safety authorization boundary changed {aid}")
    if block.get("formal_runtime_generation") != "V17.28":
        raise ValueError(f"V17.29 promotion-safety prior authority changed {aid}")
    if block.get("proposed_runtime_generation") != "V17.29":
        raise ValueError(f"V17.29 proposed generation changed {aid}")
    if block.get("exact_source_sha256") != digest:
        raise ValueError(f"V17.29 exact source binding changed {aid}")
    if int(block.get("exact_source_bytes") or -1) != int(target["source_bytes"]):
        raise ValueError(f"V17.29 exact source bytes changed {aid}")
    if block.get("split_equity_pattern") != "SPLIT_LABEL_1_BEFORE_1_AFTER_AMOUNT":
        raise ValueError(f"V17.29 split-equity pattern changed {aid}")
    if block.get("column_role_gate_pass") is not True:
        raise ValueError(f"V17.29 column role gate changed {aid}")
    if block.get("explicit_equity_pdf_text") is not True:
        raise ValueError(f"V17.29 equity is not explicit PDF text {aid}")
    if block.get("equity_value_inferred_as_assets_minus_liabilities") is not False:
        raise ValueError(f"V17.29 equity inference boundary changed {aid}")
    if block.get("non_balance_values_promoted") is not False:
        raise ValueError(f"V17.29 non-balance scope changed {aid}")
    if block.get("ocr_enabled") is not False:
        raise ValueError(f"V17.29 OCR boundary changed {aid}")
    if block.get("fuzzy_alias_matching_enabled") is not False:
        raise ValueError(f"V17.29 fuzzy alias boundary changed {aid}")
    if block.get("source_policy_relaxed") is not False:
        raise ValueError(f"V17.29 source policy changed {aid}")
    if block.get("point_in_time_policy_relaxed") is not False:
        raise ValueError(f"V17.29 PIT policy changed {aid}")
    if block.get("issuer_gate_relaxed") is not False:
        raise ValueError(f"V17.29 issuer gate changed {aid}")

    identity = block.get("dual_column_identity") or {}
    if str(identity.get("tolerance")) != str(IDENTITY_TOLERANCE):
        raise ValueError(f"V17.29 accounting tolerance changed {aid}")
    columns = identity.get("columns") or []
    if len(columns) != 2:
        raise ValueError(f"V17.29 dual-column identity changed {aid}")
    if [row.get("column") for row in columns] != ["CURRENT", "PRIOR"]:
        raise ValueError(f"V17.29 identity column order changed {aid}")
    for row in columns:
        if not _zero(row.get("identity_residual_cny")):
            raise ValueError(f"V17.29 identity residual changed {aid}")
        if not _zero(row.get("identity_relative_error")):
            raise ValueError(f"V17.29 identity relative error changed {aid}")


def _promote_runtime_wrapper(parsed: dict, digest: str, target: dict) -> dict:
    _validate_promotion_output(parsed, digest, target)
    out = copy.deepcopy(parsed)
    for concept in ALLOWED_CONCEPTS:
        out["observations"][concept]["extraction_scope"] = PRODUCTION_SCOPE

    block = out["balance_sheet_block"]
    block.update(
        {
            "arbitration": "V17_29_EXACT_SOURCE_SPLIT_GROUP_EQUITY_DUAL_IDENTITY_PRODUCTION",
            "production_promotion_experiment_only": False,
            "inactive_runtime_wrapper": True,
            "runtime_promotion_authorized": False,
            "formal_runtime_generation_before_activation": "V17.28",
            "formal_runtime_generation": "V17.29",
            "production_runtime_generation": "V17.29",
            "promotion_safety_pr": PROMOTION_SAFETY_PR,
            "promotion_safety_head": PROMOTION_SAFETY_HEAD,
            "promotion_safety_run": PROMOTION_SAFETY_RUN,
            "promotion_safety_artifact_id": PROMOTION_SAFETY_ARTIFACT_ID,
            "promotion_safety_artifact": PROMOTION_SAFETY_ARTIFACT,
            "promotion_safety_artifact_digest": PROMOTION_SAFETY_ARTIFACT_DIGEST,
            "promotion_evidence_manifest": PROMOTION_EVIDENCE_MANIFEST,
        }
    )
    out["parser_version"] = METHOD
    return out


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    """Inactive V17.29 runtime-wrapper implementation.

    Every non-target, wrong-date, or wrong-byte input delegates exactly to the
    formal V17.28 object through the frozen promotion-safety dependency. Exact
    targets must first reproduce the machine-accepted promotion-safety object
    before this wrapper may emit V17.29 production metadata. Runtime authority
    is not activated by this module or its validation PR.
    """
    digest = hashlib.sha256(raw).hexdigest()
    target = TARGETS.get(digest)
    parsed = promotion.parse_pdf_bytes(raw, economic_date)
    if (
        target is None
        or economic_date != target["economic_date"]
        or len(raw) != int(target["source_bytes"])
    ):
        return parsed
    return _promote_runtime_wrapper(parsed, digest, target)
