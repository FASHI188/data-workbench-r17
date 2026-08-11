#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
from decimal import Decimal

import stage3_financial_pdf_parser_v22_promotion_safety as promotion

METHOD = "V17_30_EXACT_SOURCE_CROSS_PAGE_GROUP_EQUITY_PRODUCTION"
METHODOLOGY_VERSION = "V3.3.14-V17.30"
ALLOWED_CONCEPTS = promotion.ALLOWED_CONCEPTS
TARGETS = promotion.TARGETS
IDENTITY_TOLERANCE = promotion.IDENTITY_TOLERANCE
PRODUCTION_SCOPE = "V17_30_EXACT_SOURCE_CROSS_PAGE_GROUP_EQUITY_PRODUCTION"

PROMOTION_SAFETY_PR = 121
PROMOTION_SAFETY_HEAD = "2cd84a81b3d4f291aae2ae2cb5b6daf8629ad030"
PROMOTION_SAFETY_RUN = 31452374012
PROMOTION_SAFETY_ARTIFACT_ID = 9086776910
PROMOTION_SAFETY_ARTIFACT = "stage3-s3g1j-v17-29-cross-page-production-promotion-safety-v1"
PROMOTION_SAFETY_ARTIFACT_DIGEST = (
    "sha256:d3bb089c7e0524a39b62016f6b6b41539aec99894b874c2940678bee24edebc4"
)
PROMOTION_REPORT_SHA256 = "854d79ff1a826b13579ef5014d666994f7b5520f5a0c35dfc7f3d93f5eb41a16"
PROMOTION_EVIDENCE_MANIFEST = (
    "governance/stage3_s3g1j_v17_29_cross_page_production_promotion_safety.json"
)


def _zero(value: object) -> bool:
    try:
        return Decimal(str(value)) == Decimal("0")
    except Exception:
        return False


def _validate_promotion_output(parsed: dict, digest: str, target: dict) -> None:
    aid = target["announcement_id"]
    if parsed.get("parser_version") != promotion.METHOD:
        raise ValueError(f"V17.30 wrapper requires accepted promotion-safety output {aid}")
    if list(parsed.get("validation_errors") or []):
        raise ValueError(f"V17.30 promotion-safety retained validation errors {aid}")
    if parsed.get("tier1_found") != 0 or parsed.get("tier2_found") != 3:
        raise ValueError(f"V17.30 promotion-safety tier counts changed {aid}")

    observations = parsed.get("observations") or {}
    found = {
        concept
        for concept, row in observations.items()
        if isinstance(row, dict) and row.get("status") == "FOUND"
    }
    if found != set(ALLOWED_CONCEPTS):
        raise ValueError(f"V17.30 promotion-safety concept scope changed {aid}: {sorted(found)}")
    for concept in ALLOWED_CONCEPTS:
        row = observations.get(concept) or {}
        if str(row.get("normalized_cny_value") or "") != target["values"][concept][0]:
            raise ValueError(f"V17.30 promotion-safety value changed {aid} {concept}")
        if int(row.get("page") or -1) != int(target["selected_pages"][concept]):
            raise ValueError(f"V17.30 promotion-safety page changed {aid} {concept}")
        if str(row.get("matched_alias") or "") != promotion.TARGET_ALIASES[concept]:
            raise ValueError(f"V17.30 promotion-safety alias changed {aid} {concept}")

    block = parsed.get("balance_sheet_block") or {}
    if block.get("candidate_only") is not False:
        raise ValueError(f"V17.30 promotion-safety candidate marker changed {aid}")
    if block.get("production_promotion_experiment_only") is not True:
        raise ValueError(f"V17.30 promotion-safety experiment marker missing {aid}")
    if block.get("runtime_promotion_authorized") is not False:
        raise ValueError(f"V17.30 promotion-safety authorization boundary changed {aid}")
    if block.get("formal_runtime_generation") != "V17.29":
        raise ValueError(f"V17.30 prior authority changed {aid}")
    if block.get("proposed_runtime_generation") != "V17.30_NOT_AUTHORIZED":
        raise ValueError(f"V17.30 proposed generation boundary changed {aid}")
    if block.get("exact_source_sha256") != digest:
        raise ValueError(f"V17.30 exact source SHA binding changed {aid}")
    if int(block.get("exact_source_bytes") or -1) != int(target["source_bytes"]):
        raise ValueError(f"V17.30 exact source byte binding changed {aid}")
    if block.get("cross_page_equity_pattern") != "ONE_PAGE_EXACT_ALIAS_CONTINUATION":
        raise ValueError(f"V17.30 cross-page pattern changed {aid}")
    cross = block.get("cross_page_equity") or {}
    if int(cross.get("equity_amount_page") or -1) + 1 != int(cross.get("suffix_page") or -1):
        raise ValueError(f"V17.30 cross-page adjacency changed {aid}")
    if str(cross.get("equity_prefix") or "") + str(cross.get("equity_suffix") or "") != promotion.FULL_EQUITY_ALIAS:
        raise ValueError(f"V17.30 cross-page alias completion changed {aid}")
    if block.get("column_role_gate_pass") is not True:
        raise ValueError(f"V17.30 column role gate changed {aid}")
    if block.get("explicit_equity_pdf_text") is not True:
        raise ValueError(f"V17.30 equity is not explicit PDF text {aid}")
    if block.get("equity_value_inferred_as_assets_minus_liabilities") is not False:
        raise ValueError(f"V17.30 equity inference boundary changed {aid}")
    if block.get("non_balance_values_promoted") is not False:
        raise ValueError(f"V17.30 non-balance scope changed {aid}")
    for key in (
        "ocr_enabled",
        "fuzzy_alias_matching_enabled",
        "source_policy_relaxed",
        "point_in_time_policy_relaxed",
        "issuer_gate_relaxed",
        "accounting_tolerance_relaxed",
    ):
        if block.get(key) is not False:
            raise ValueError(f"V17.30 forbidden relaxation changed {aid} {key}")

    identity = block.get("dual_column_identity") or {}
    if str(identity.get("tolerance")) != str(IDENTITY_TOLERANCE):
        raise ValueError(f"V17.30 accounting tolerance changed {aid}")
    columns = identity.get("columns") or []
    if [row.get("column") for row in columns] != ["CURRENT", "PRIOR"]:
        raise ValueError(f"V17.30 identity column order changed {aid}")
    for row in columns:
        if not _zero(row.get("identity_residual_cny")) or not _zero(row.get("identity_relative_error")):
            raise ValueError(f"V17.30 identity residual changed {aid}")


def _promote_runtime_wrapper(parsed: dict, digest: str, target: dict) -> dict:
    _validate_promotion_output(parsed, digest, target)
    out = copy.deepcopy(parsed)
    for concept in ALLOWED_CONCEPTS:
        out["observations"][concept]["extraction_scope"] = PRODUCTION_SCOPE

    block = out["balance_sheet_block"]
    block.update(
        {
            "arbitration": "V17_30_EXACT_SOURCE_CROSS_PAGE_GROUP_EQUITY_DUAL_IDENTITY_PRODUCTION",
            "production_promotion_experiment_only": False,
            "inactive_runtime_wrapper": True,
            "runtime_promotion_authorized": False,
            "formal_runtime_generation_before_activation": "V17.29",
            "formal_runtime_generation": "V17.30",
            "production_runtime_generation": "V17.30",
            "v17_30_authority_activated": False,
            "promotion_safety_pr": PROMOTION_SAFETY_PR,
            "promotion_safety_head": PROMOTION_SAFETY_HEAD,
            "promotion_safety_run": PROMOTION_SAFETY_RUN,
            "promotion_safety_artifact_id": PROMOTION_SAFETY_ARTIFACT_ID,
            "promotion_safety_artifact": PROMOTION_SAFETY_ARTIFACT,
            "promotion_safety_artifact_digest": PROMOTION_SAFETY_ARTIFACT_DIGEST,
            "promotion_report_sha256": PROMOTION_REPORT_SHA256,
            "promotion_evidence_manifest": PROMOTION_EVIDENCE_MANIFEST,
        }
    )
    out["parser_version"] = METHOD
    return out


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    """Inactive V17.30 wrapper around formal V17.29.

    Every non-target, wrong-date or wrong-byte input delegates through the frozen
    promotion layer to the exact formal V17.29 object. Exact two-target inputs
    must reproduce accepted cross-page promotion-safety semantics before only
    inactive V17.30 runtime metadata is emitted. This module does not activate
    V17.30 authority.
    """
    digest = hashlib.sha256(raw).hexdigest()
    target = TARGETS.get(digest)
    parsed = promotion.parse_pdf_bytes(raw, economic_date)
    if target is None or economic_date != target["economic_date"] or len(raw) != int(target["source_bytes"]):
        return parsed
    return _promote_runtime_wrapper(parsed, digest, target)
