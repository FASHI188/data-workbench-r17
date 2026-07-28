#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

ALLOWED_BOARDS={"SSE_MAIN_A","SZSE_MAIN_A"}
EXCLUDED_BOARDS={"SSE_STAR","SZSE_CHINEXT","BSE","NEEQ"}
PRICE_LIMIT=Decimal("70")


def decimal_price(value: object)->Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError) as exc:
        raise ValueError(f"invalid market price: {value!r}") from exc


def eligible_mainboard_under_70(board:str, price:object)->bool:
    if board not in ALLOWED_BOARDS:
        return False
    p=decimal_price(price)
    if p<=0:
        return False
    return p<PRICE_LIMIT


def _parse_iso(value:str)->datetime:
    dt=datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {value}")
    return dt


def assert_point_in_time_price(price_timestamp:str, signal_cutoff_timestamp:str)->None:
    if not price_timestamp or not signal_cutoff_timestamp:
        raise ValueError("price timestamp and signal cutoff are required")
    price_dt=_parse_iso(price_timestamp)
    cutoff_dt=_parse_iso(signal_cutoff_timestamp)
    if price_dt>cutoff_dt:
        raise ValueError(f"future price leakage: price={price_timestamp} cutoff={signal_cutoff_timestamp}")
