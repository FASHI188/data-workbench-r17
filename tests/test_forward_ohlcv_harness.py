from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

from audit_forward_ohlcv import expected_weekdays
from build_forward_ohlcv import norm_date, sse_recent_url


def test_sse_recent_url_is_bounded_delta_window() -> None:
    u = urlparse(sse_recent_url("600000", recent_rows=80))
    q = parse_qs(u.query)
    assert u.path.endswith("/600000")
    assert q["begin"] == ["-80"]
    assert q["end"] == ["-1"]
    assert "date,open,high,low,close,volume,amount" in q["select"][0]


def test_norm_date_accepts_both_exchange_formats() -> None:
    assert norm_date("20260806") == date(2026, 8, 6)
    assert norm_date("2026-08-04") == date(2026, 8, 4)


def test_forward_window_weekday_source_dates() -> None:
    days = expected_weekdays(date(2026, 7, 25), date(2026, 8, 12))
    assert days[0] == date(2026, 7, 27)
    assert days[-1] == date(2026, 8, 12)
    assert len(days) == 13
