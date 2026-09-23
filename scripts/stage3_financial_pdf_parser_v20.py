#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
from decimal import Decimal

import stage3_financial_pdf_parser_v20_candidate as candidate


METHOD = "V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION"
METHODOLOGY_VERSION = "V3.3.8-V17.28"
ALLOWED_CONCEPTS = candidate.ALLOWED_CONCEPTS
TARGETS = candidate.TARGETS
CANDIDATE_RUN = 30827493788
CANDIDATE_HEAD = "08ddddca5effac0f416b68ac2f4c07cdec99dfb2"
CANDIDATE_ARTIFACT_ID = 8861519922
CANDIDATE_ARTIFACT = "stage3-s3g1j-v17-28-split-equity-candidate-safety"
CANDIDATE_ARTIFACT_DIGEST = (
    "sha256:8a87dfed63160374fc04c88c3d02a93eedac6ae239ae559b64aaad93c71d22c1"
)
EVIDENCE_MANIFEST = "governance/stage3_s3g1j_v17_28_candidate_safety.json"
PRODUCTION_SCOPE = "V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION"


def _zero(value: object) -> bool:
    try:
        return Decimal(str(value)) == Decimal("0")
    except Exception:
        return False


def _validate_candidate_output(parsed: dict, digest: str, target: dict) -> None:
    aid = target["announcement_id"]
    if parsed.get("parser_version") != candidate.METHOD:
        raise ValueError(f"V17.28 production requires accepted candidate output {aid}")
    if parsed.get("validation_errors"):
        raise ValueError(f"V17.28 candidate retained validation errors {aid}")
    if parsed.get("tier1_found") != 0 or parsed.get("tier2_found") != 3:
        raise ValueError(f"V17.28 candidate tier counts changed {aid}")

    observations = parsed.get("observations") or {}
    found = {
        concept
        for concept, row in observations.items()
        if isinstance(row, dict) and row.get("status") == "FOUND"
    }
    if found != set(ALLOWED_CONCEPTS):
        raise ValueError(f"V17.28 candidate concept scope changed {aid}: {sorted(found)}")
    for concept in ALLOWED_CONCEPTS:
        expected = target["values"][concept][0]
        actual = str((observations.get(concept) or {}).get("normalized_cny_value") or "")
        if actual != expected:
            raise ValueError(
                f"V17.28 candidate value changed {aid} {concept}: "
                f"expected={expected} actual={actual}"
            )

    block = parsed.get("balance_sheet_block") or {}
    if block.get("candidate_only") is not True:
        raise ValueError(f"V17.28 candidate marker missing {aid}")
    if block.get("exact_source_sha256") != digest:
        raise ValueError(f"V17.28 source binding changed {aid}")
    if block.get("column_role_gate_pass") is not True:
        raise ValueError(f"V17.28 column role gate changed {aid}")
    if block.get("split_equity_pattern") != target["split_pattern"]:
        raise ValueError(f"V17.28 split-equity pattern changed {aid}")
    if block.get("explicit_equity_pdf_text") is not True:
        raise ValueError(f"V17.28 equity is not explicit PDF text {aid}")
    if block.get("equity_value_inferred_as_assets_minus_liabilities") is not False:
        raise ValueError(f"V17.28 equity inference boundary changed {aid}")
    if block.get("non_balance_values_promoted") is not False:
        raise ValueError(f"V17.28 non-balance scope changed {aid}")
    if block.get("ocr_enabled") is not False:
        raise ValueError(f"V17.28 OCR boundary changed {aid}")
    if block.get("fuzzy_alias_matching_enabled") is not False:
        raise ValueError(f"V17.28 fuzzy alias boundary changed {aid}")

    identity = block.get("dual_column_identity") or {}
    columns = identity.get("columns") or []
    if len(columns) != 2:
        raise ValueError(f"V17.28 dual-column identity changed {aid}")
    if [row.get("column") for row in columns] != ["CURRENT", "PRIOR"]:
        raise ValueError(f"V17.28 identity column order changed {aid}")
    for row in columns:
        if not _zero(row.get("identity_residual_cny")):
            raise ValueError(f"V17.28 identity residual changed {aid}")
        if not _zero(row.get("identity_relative_error")):
            raise ValueError(f"V17.28 identity relative error changed {aid}")


def _promote_candidate(parsed: dict, digest: str, target: dict) -> dict:
    _validate_candidate_output(parsed, digest, target)
    out = copy.deepcopy(parsed)
    for concept in ALLOWED_CONCEPTS:
        out["observations"][concept]["extraction_scope"] = PRODUCTION_SCOPE

    block = out["balance_sheet_block"]
    block.update(
        {
            "arbitration": "V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_DUAL_IDENTITY_PRODUCTION",
            "candidate_only": False,
            "candidate_safety_promoted": True,
            "formal_runtime_generation": "V17.28",
            "production_runtime_generation": "V17.28",
            "candidate_generation": "V17.28",
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
    """Promote only the two machine-accepted split-row GROUP equity identities.

    Every non-target or wrong-date input returns the formal V17.27 object exactly.
    A target must first pass the frozen V17.28 candidate implementation and all
    source/date/role/geometry/dual-column accounting contracts.
    """
    digest = hashlib.sha256(raw).hexdigest()
    target = TARGETS.get(digest)
    parsed = dict(candidate.parse_pdf_bytes(raw, economic_date))
    if target is None or economic_date != target["economic_date"]:
        return parsed
    return _promote_candidate(parsed, digest, target)
