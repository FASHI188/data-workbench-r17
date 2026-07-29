#!/usr/bin/env python3
from __future__ import annotations

import fitz

import stage3_financial_pdf_parser_v2 as v2
import stage3_financial_pdf_parser_v8 as v13
from stage3_financial_coordinate_fallback_v14 import validated_coordinate_balance_sheet

METHOD = "V14_COORDINATE_ROLE_GATED_FALLBACK"


def _validated_balance_sheet_v14(doc: fitz.Document):
    # Preserve the audited V13 path exactly. Coordinate parsing is a strict
    # fallback only when V13 cannot construct an accounting-identity-valid block.
    block, meta = v13._validated_balance_sheet_v13(doc)
    if block is not None:
        return block, meta

    fallback, fallback_meta = validated_coordinate_balance_sheet(doc)
    if fallback is None:
        return None, None
    return fallback, fallback_meta


# V11/V13 resolve the v2 module global at runtime, so replacing only this hook
# preserves all existing statement aliases, units, issuer checks and validation.
v2._validated_balance_sheet = _validated_balance_sheet_v14


def parse_pdf_bytes(raw: bytes) -> dict:
    return v13.parse_pdf_bytes(raw)
