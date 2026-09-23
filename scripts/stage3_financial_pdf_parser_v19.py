#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib

import stage3_financial_pdf_parser_v19_candidate as candidate

METHOD = "V17_27_EXACT_SOURCE_NORMAL_EQUITY_IDENTITY_PRODUCTION"
METHODOLOGY_VERSION = "V3.3.7-V17.27"
ALLOWED_CONCEPTS = candidate.ALLOWED_CONCEPTS
TARGETS = candidate.TARGETS
TARGET_PAGES = candidate.TARGET_PAGES
TARGET_ALIASES = candidate.TARGET_ALIASES
TARGET_ANCHOR_PAGE = candidate.TARGET_ANCHOR_PAGE
CANDIDATE_RUN = 30747664549
CANDIDATE_HEAD = "ae9e80d90e227772cca88cc3b7ebadd2c6cfb7ca"
CANDIDATE_ARTIFACT_ID = 8833408494
CANDIDATE_ARTIFACT = "stage3-s3g1j-v17-27-normal-equity-candidate-safety"
CANDIDATE_ARTIFACT_DIGEST = (
    "sha256:d279df39e62f4f0f4fd655267788473dd34945113f677635563ce38f3af88513"
)
EVIDENCE_MANIFEST = "governance/stage3_s3g1j_v17_27_candidate_safety.json"
PRODUCTION_SCOPE = "V17_27_EXACT_SOURCE_NORMAL_EQUITY_IDENTITY_PRODUCTION"


def _validate_candidate_output(parsed: dict, digest: str, target: dict) -> None:
    if parsed.get("parser_version") != candidate.METHOD:
        raise ValueError(
            f"V17.27 production promotion requires accepted candidate output "
            f"{target['announcement_id']}"
        )
    if parsed.get("validation_errors"):
        raise ValueError(
            f"V17.27 accepted candidate retained validation errors "
            f"{target['announcement_id']}"
        )
    if parsed.get("tier1_found") != 0 or parsed.get("tier2_found") != 3:
        raise ValueError(
            f"V17.27 accepted candidate tier counts changed "
            f"{target['announcement_id']}"
        )
    observations = parsed.get("observations") or {}
    found = {
        concept
        for concept, row in observations.items()
        if isinstance(row, dict) and row.get("status") == "FOUND"
    }
    if found != set(ALLOWED_CONCEPTS):
        raise ValueError(
            f"V17.27 accepted candidate concept scope changed "
            f"{target['announcement_id']}: {sorted(found)}"
        )
    block = parsed.get("balance_sheet_block") or {}
    if block.get("candidate_only") is not True:
        raise ValueError(
            f"V17.27 accepted candidate marker missing {target['announcement_id']}"
        )
    if block.get("exact_source_sha256") != digest:
        raise ValueError(
            f"V17.27 accepted candidate source binding changed "
            f"{target['announcement_id']}"
        )
    if block.get("column_role_gate_pass") is not True:
        raise ValueError(
            f"V17.27 accepted candidate column gate changed "
            f"{target['announcement_id']}"
        )
    if block.get("identity_relative_error") not in ("0", "0.0", "0.00"):
        raise ValueError(
            f"V17.27 accepted candidate identity changed "
            f"{target['announcement_id']}"
        )
    if block.get("identity_residual_cny") not in ("0", "0.0", "0.00"):
        raise ValueError(
            f"V17.27 accepted candidate residual changed "
            f"{target['announcement_id']}"
        )
    if block.get("normal_equity_alias") != "所有者权益合计":
        raise ValueError(
            f"V17.27 accepted candidate equity alias changed "
            f"{target['announcement_id']}"
        )
    if block.get("damaged_equity_alias_required") is not False:
        raise ValueError(
            f"V17.27 accepted candidate damaged-alias boundary changed "
            f"{target['announcement_id']}"
        )


def _promote_candidate(parsed: dict, digest: str, target: dict) -> dict:
    _validate_candidate_output(parsed, digest, target)
    out = copy.deepcopy(parsed)
    for concept in ALLOWED_CONCEPTS:
        observation = out["observations"][concept]
        observation["extraction_scope"] = PRODUCTION_SCOPE

    block = out["balance_sheet_block"]
    block.update(
        {
            "arbitration": (
                "V17_27_EXACT_SOURCE_NORMAL_EQUITY_A_EQUALS_L_PLUS_E_PRODUCTION"
            ),
            "candidate_only": False,
            "candidate_safety_promoted": True,
            "formal_runtime_generation": "V17.27",
            "production_runtime_generation": "V17.27",
            "candidate_generation": "V17.27",
            "candidate_acceptance_run": CANDIDATE_RUN,
            "candidate_acceptance_head": CANDIDATE_HEAD,
            "candidate_acceptance_artifact_id": CANDIDATE_ARTIFACT_ID,
            "candidate_acceptance_artifact": CANDIDATE_ARTIFACT,
            "candidate_acceptance_artifact_digest": CANDIDATE_ARTIFACT_DIGEST,
            "production_evidence_manifest": EVIDENCE_MANIFEST,
        }
    )
    out["parser_version"] = METHOD
    return out


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    """Promote only the five machine-accepted source/date identities.

    Every non-target input returns the accepted V17.26 object byte-for-field unchanged.
    A target must first pass the exact V17.27 candidate implementation and its frozen
    source/date, normal-equity, dual-column and accounting-identity contracts.
    """
    digest = hashlib.sha256(raw).hexdigest()
    target = TARGETS.get(digest)
    parsed = dict(candidate.parse_pdf_bytes(raw, economic_date))
    if target is None or economic_date != target["economic_date"]:
        return parsed
    return _promote_candidate(parsed, digest, target)
