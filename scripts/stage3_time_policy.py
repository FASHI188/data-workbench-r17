#!/usr/bin/env python3
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_CUTOFF = time(15, 0, 0)


def parse_iso_timestamp(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {value}")
    return dt.astimezone(SHANGHAI)


def effective_session_for_timestamp(
    available_at: str,
    trading_days: list[str],
    cutoff: time = DEFAULT_CUTOFF,
) -> str:
    """Map a verified publication timestamp to the earliest admissible daily session.

    A publication on a trading day at or before cutoff is available to that day's
    close-based feature snapshot. Publications after cutoff, or on non-trading days,
    are deferred to the first subsequent trading session.
    """
    dt = parse_iso_timestamp(available_at)
    days = [date.fromisoformat(x) for x in trading_days]
    if days != sorted(days) or len(set(days)) != len(days):
        raise ValueError("trading_days must be unique and sorted")
    d = dt.date()
    same_day_allowed = d in days and dt.timetz().replace(tzinfo=None) <= cutoff
    for td in days:
        if td > d or (td == d and same_day_allowed):
            return td.isoformat()
    raise ValueError(f"no trading session available after {available_at}")


def effective_session_for_date_only(
    publication_date: str,
    trading_days: list[str],
) -> str:
    """Conservative mapping when official publication time is unknown.

    The publication date itself is never used, even if it is a trading day.
    """
    d = date.fromisoformat(publication_date)
    days = [date.fromisoformat(x) for x in trading_days]
    if days != sorted(days) or len(set(days)) != len(days):
        raise ValueError("trading_days must be unique and sorted")
    for td in days:
        if td > d:
            return td.isoformat()
    raise ValueError(f"no trading session after date-only publication {publication_date}")


def validate_surprise_timing(expectation_available_at: str, actual_available_at: str) -> None:
    expectation = parse_iso_timestamp(expectation_available_at)
    actual = parse_iso_timestamp(actual_available_at)
    if expectation >= actual:
        raise ValueError(
            "surprise expectation must be available strictly before actual publication"
        )
