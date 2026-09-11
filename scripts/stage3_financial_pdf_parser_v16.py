#!/usr/bin/env python3
from __future__ import annotations

import stage3_financial_pdf_parser_v15 as accepted
import stage3_financial_statement_blocks_v16_5 as blocks
import stage3_financial_statement_blocks_v17_25 as candidate_blocks

METHOD = "V17_25_GENERIC_BALANCE_SHEET_EXPLICIT_GROUP_WITNESS_CANDIDATE"


def parse_pdf_bytes(raw: bytes, economic_date: str) -> dict:
    original = blocks.formal_statement_events
    blocks.formal_statement_events = candidate_blocks.formal_statement_events
    try:
        parsed = dict(accepted.parse_pdf_bytes(raw, economic_date))
    finally:
        blocks.formal_statement_events = original
    parsed["parser_version"] = METHOD
    return parsed
