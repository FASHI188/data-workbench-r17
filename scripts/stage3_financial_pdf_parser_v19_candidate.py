#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
from decimal import Decimal

import fitz

import stage3_financial_pdf_parser_v18 as accepted
import stage3_financial_spatial_alias_v17_27_candidate as spatial

METHOD = "V17_27_EXACT_SOURCE_NORMAL_EQUITY_IDENTITY_CANDIDATE"
METHODOLOGY_VERSION = "V3.3.7-V17.27-CANDIDATE"
ALLOWED_CONCEPTS = ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY")
FILTER_REASON = "V17_27_CANDIDATE_UNVALIDATED_NON_BALANCE_CONCEPT"
TARGET_PAGES = {
    "TOTAL_ASSETS": 9,
    "TOTAL_LIABILITIES": 10,
    "TOTAL_EQUITY": 11,
}
TARGET_ALIASES = spatial.TARGET_ALIASES
TARGET_ANCHOR_PAGE = 8

TARGETS = {
    "87a313e900dd74ec976e2c6e5c0eeb0e7c7cfd5e68c31e9ede3ae8c01c7e9d49": {
        "announcement_id": "1200907104",
        "economic_date": "2015-03-31",
        "values": {
            "TOTAL_ASSETS": "4888152213.85",
            "TOTAL_LIABILITIES": "1510781556.82",
            "TOTAL_EQUITY": "3377370657.03",
        },
    },
    "e7af0c09c31f0be1e83fdb118c603a141c094739767de01b90f57680ce9596a8": {
        "announcement_id": "1201708762",
        "economic_date": "2015-09-30",
        "values": {
            "TOTAL_ASSETS": "4874736170.10",
            "TOTAL_LIABILITIES": "1441408971.22",
            "TOTAL_EQUITY": "3433327198.88",
        },
    },
    "04b84b49ce4e36a4c9089e13cd46f717ef27c7d93c141533d7d7ff2299513925": {
        "announcement_id": "1202195310",
        "economic_date": "2016-03-31",
        "values": {
            "TOTAL_ASSETS": "5097002228.22",
            "TOTAL_LIABILITIES": "1542170536.28",
            "TOTAL_EQUITY": "3554831691.94",
        },
    },
    "eb0c9e0b559e1960316f3844ac32e7299cf31391fec1d83ee6b4fb2fe37aef14": {
        "announcement_id": "1202774611",
        "economic_date": "2016-09-30",
        "values": {
            "TOTAL_ASSETS": "5482906412.71",
            "TOTAL_LIABILITIES": "1838330886.91",
            "TOTAL_EQUITY": "3644575525.80",
        },
    },
    "3d009555c7acb24c7d9cc0cb52ec3d5e43c473379b0c02c5bc832d6a3d773c82": {
        "announcement_id": "1203358200",
        "economic_date": "2017-03-31",
        "values": {
            "TOTAL_ASSETS": "5755203586.29",
            "TOTAL_LIABILITIES": "1966640135.46",
            "TOTAL_EQUITY": "3788563450.83",
        },
    },
}


def _recovered(parsed: dict) -> bool:
    observations = parsed.get("observations") or {}
    return (
        all(
            (observations.get(concept) or {}).get("status") == "FOUND"
            for concept in ALLOWED_CONCEPTS
        )
        and isinstance(parsed.get("balance_sheet_block"), dict)
        and not list(parsed.get("validation_errors") or [])
    )


def _validate_diagnostic(diagnostic: dict, target: dict) -> None:
    if diagnostic.get("recovered") is not True:
        raise ValueError(
            f"V17.27 candidate did not recover {target['announcement_id']}"
        )
    witness = diagnostic.get("generic_group_witness") or {}
    if int(witness.get("promoted_generic_group_count", -1)) != 1:
        raise ValueError(
            f"V17.27 target witness count changed {target['announcement_id']}"
        )
    selected = diagnostic.get("selected") or {}
    if set(selected) != set(ALLOWED_CONCEPTS):
        raise ValueError(
            f"V17.27 selected concepts changed {target['announcement_id']}"
        )
    identity = diagnostic.get("identity") or {}
    if Decimal(str(identity.get("identity_relative_error"))) != Decimal("0"):
        raise ValueError(
            f"V17.27 identity relative error changed {target['announcement_id']}"
        )
    if Decimal(str(identity.get("identity_residual_cny"))) != Decimal("0"):
        raise ValueError(
            f"V17.27 identity residual changed {target['announcement_id']}"
        )
    if int(identity.get("page_span", -1)) != 2:
        raise ValueError(f"V17.27 page span changed {target['announcement_id']}")
    if int(identity.get("anchor_span", -1)) != 0:
        raise ValueError(f"V17.27 anchor span changed {target['announcement_id']}")
    column = diagnostic.get("column_role_gate") or {}
    if column.get("pass") is not True:
        raise ValueError(f"V17.27 column gate failed {target['announcement_id']}")
    evidence = column.get("concepts") or {}
    if not all((evidence.get(concept) or {}).get("pass") is True for concept in ALLOWED_CONCEPTS):
        raise ValueError(
            f"V17.27 concept column evidence failed {target['announcement_id']}"
        )

    for concept in ALLOWED_CONCEPTS:
        candidate = selected[concept]
        if str(candidate.get("alias") or "") != TARGET_ALIASES[concept]:
            raise ValueError(
                f"V17.27 alias changed {target['announcement_id']} {concept}"
            )
        if int(candidate.get("page") or 0) != TARGET_PAGES[concept]:
            raise ValueError(
                f"V17.27 page changed {target['announcement_id']} {concept}"
            )
        if int(candidate.get("statement_anchor_page") or 0) != TARGET_ANCHOR_PAGE:
            raise ValueError(
                f"V17.27 anchor changed {target['announcement_id']} {concept}"
            )
        if str(candidate.get("statement_role") or "") != "GROUP":
            raise ValueError(
                f"V17.27 role changed {target['announcement_id']} {concept}"
            )
        if concept == "TOTAL_EQUITY" and candidate.get(
            "strict_corrupted_equity_alias_v17_24"
        ):
            raise ValueError(
                f"V17.27 equity unexpectedly uses damaged alias {target['announcement_id']}"
            )
        actual = Decimal(str(candidate.get("value")))
        expected = Decimal(target["values"][concept])
        if actual != expected:
            raise ValueError(
                f"V17.27 value changed {target['announcement_id']} {concept} "
                f"expected={expected} actual={actual}"
            )
        period = candidate.get("period_evidence") or {}
        if period.get("matched") is not True:
            raise ValueError(
                f"V17.27 period evidence failed {target['announcement_id']} {concept}"
            )
        if period.get("expected_economic_date") != target["economic_date"]:
            raise ValueError(
                f"V17.27 period target changed {target['announcement_id']} {concept}"
            )


def _promote(current: dict, digest: str, target: dict, diagnostic: dict) -> dict:
    _validate_diagnostic(diagnostic, target)
    selected = diagnostic["selected"]
    out = copy.deepcopy(current)
    observations = out.get("observations") or {}
    scoped: dict[str, dict] = {}
    filtered: list[str] = []
    for concept, observation in observations.items():
        if concept in ALLOWED_CONCEPTS:
            continue
        if (observation or {}).get("status") == "FOUND":
            filtered.append(concept)
        scoped[concept] = {"status": "NOT_FOUND", "reason": FILTER_REASON}

    extraction_scope = "V17_27_EXACT_SOURCE_NORMAL_EQUITY_IDENTITY_CANDIDATE"
    for concept in ALLOWED_CONCEPTS:
        candidate = selected[concept]
        unit = str(candidate.get("unit") or "")
        scoped[concept] = {
            "concept": concept,
            "status": "FOUND",
            "raw_value": str(candidate.get("raw_value") or ""),
            "normalized_cny_value": str(candidate.get("value") or ""),
            "unit": unit,
            "unit_multiplier": str(candidate.get("unit_multiplier") or ""),
            "page": int(candidate.get("page") or 0) or None,
            "matched_alias": str(candidate.get("alias") or ""),
            "extraction_scope": extraction_scope,
            "confidence": "HIGH",
        }

    identity = diagnostic["identity"]
    column = diagnostic["column_role_gate"]
    witness = diagnostic["generic_group_witness"]
    block = {
        "start_page": TARGET_ANCHOR_PAGE,
        "unit": str(selected["TOTAL_ASSETS"].get("unit") or ""),
        "arbitration": "V17_27_EXACT_SOURCE_NORMAL_EQUITY_A_EQUALS_L_PLUS_E",
        "expected_economic_date": target["economic_date"],
        "identity_tolerance": "0.005",
        "identity_relative_error": identity.get("identity_relative_error"),
        "identity_residual_cny": identity.get("identity_residual_cny"),
        "page_span": identity.get("page_span"),
        "anchor_span": identity.get("anchor_span"),
        "column_role_gate_pass": True,
        "selected_pages": {
            concept: selected[concept].get("page") for concept in ALLOWED_CONCEPTS
        },
        "selected_aliases": {
            concept: selected[concept].get("alias") for concept in ALLOWED_CONCEPTS
        },
        "selected_period_evidence": {
            concept: selected[concept].get("period_evidence")
            for concept in ALLOWED_CONCEPTS
        },
        "column_role_evidence": column.get("concepts") or {},
        "generic_group_witness": witness,
        "normal_equity_alias": TARGET_ALIASES["TOTAL_EQUITY"],
        "normal_equity_source_constraint": True,
        "damaged_equity_alias_required": False,
        "candidate_only": True,
        "production_runtime_generation": "V17.26",
        "candidate_generation": "V17.27",
        "exact_source_sha256": digest,
        "validated_observation_scope": list(ALLOWED_CONCEPTS),
        "filtered_unvalidated_concepts": sorted(filtered),
        "non_balance_values_promoted": False,
        "global_row_tolerance_changed": False,
        "e_equals_a_minus_l_inference": False,
    }
    out["observations"] = scoped
    out["tier1_found"] = 0
    out["tier2_found"] = 3
    out["parser_version"] = METHOD
    out["balance_sheet_block"] = block
    out["validation_errors"] = []
    return out


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    """Test five exact-source normal-equity identities without changing runtime.

    Every non-target source returns the accepted V17.26 object unchanged. Target
    authority requires both the frozen source SHA and the exact economic date.
    """
    current = dict(accepted.parse_pdf_bytes(raw, economic_date))
    digest = hashlib.sha256(raw).hexdigest()
    target = TARGETS.get(digest)
    if target is None or economic_date != target["economic_date"]:
        return current
    if _recovered(current):
        raise ValueError(
            f"V17.26 unexpectedly recovered candidate target {target['announcement_id']}"
        )
    with fitz.open(stream=raw, filetype="pdf") as doc:
        diagnostic = spatial.diagnose_normal_equity_identity_candidate(
            doc, economic_date
        )
    proposed = _promote(current, digest, target, diagnostic)
    if not _recovered(proposed):
        raise ValueError(
            f"V17.27 candidate output did not recover {target['announcement_id']}"
        )
    return proposed
