#!/usr/bin/env python3
from __future__ import annotations

from decimal import Decimal, InvalidOperation

ALLOWED_BOARDS={"SSE_MAIN","SZSE_MAIN"}
EXCLUDED_BOARDS={"STAR","CHINEXT","BSE","NEEQ"}
PRICE_LIMIT=Decimal("70")


def decimal_price(value: object)->Decimal:
    try:return Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError) as exc:raise ValueError(f"invalid market price: {value!r}") from exc


def eligible_mainboard_under_70(board:str, price:object)->bool:
    if board not in ALLOWED_BOARDS:return False
    p=decimal_price(price)
    if p<=0:return False
    return p<PRICE_LIMIT


def assert_point_in_time_price(price_timestamp:str, signal_cutoff_timestamp:str)->None:
    # ISO-8601 timestamps compare lexically only when normalized to the same timezone;
    # callers should pass the project-normalized Asia/Shanghai form.
    if not price_timestamp or not signal_cutoff_timestamp:raise ValueError("price timestamp and signal cutoff are required")
    if price_timestamp>signal_cutoff_timestamp:raise ValueError(f"future price leakage: price={price_timestamp} cutoff={signal_cutoff_timestamp}")
