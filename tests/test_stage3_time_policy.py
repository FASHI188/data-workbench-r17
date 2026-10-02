import unittest

from scripts.stage3_time_policy import (
    effective_session_for_date_only,
    effective_session_for_timestamp,
    validate_surprise_timing,
)


TRADING_DAYS = [
    "2026-07-24",
    "2026-07-27",
    "2026-07-28",
    "2026-07-29",
]


class Stage3TimingPolicyTests(unittest.TestCase):
    def test_before_close_timestamp_can_enter_same_session(self):
        self.assertEqual(
            effective_session_for_timestamp(
                "2026-07-27T14:59:59+08:00", TRADING_DAYS
            ),
            "2026-07-27",
        )

    def test_exact_close_timestamp_can_enter_same_session(self):
        self.assertEqual(
            effective_session_for_timestamp(
                "2026-07-27T15:00:00+08:00", TRADING_DAYS
            ),
            "2026-07-27",
        )

    def test_after_close_timestamp_is_deferred(self):
        self.assertEqual(
            effective_session_for_timestamp(
                "2026-07-27T15:00:01+08:00", TRADING_DAYS
            ),
            "2026-07-28",
        )

    def test_weekend_timestamp_is_deferred_to_next_trading_day(self):
        self.assertEqual(
            effective_session_for_timestamp(
                "2026-07-26T10:00:00+08:00", TRADING_DAYS
            ),
            "2026-07-27",
        )

    def test_date_only_source_never_uses_publication_date(self):
        self.assertEqual(
            effective_session_for_date_only("2026-07-27", TRADING_DAYS),
            "2026-07-28",
        )

    def test_timestamp_requires_timezone(self):
        with self.assertRaises(ValueError):
            effective_session_for_timestamp("2026-07-27T14:00:00", TRADING_DAYS)

    def test_surprise_requires_prior_expectation(self):
        validate_surprise_timing(
            "2026-07-27T10:00:00+08:00", "2026-07-27T14:00:00+08:00"
        )
        with self.assertRaises(ValueError):
            validate_surprise_timing(
                "2026-07-27T14:00:00+08:00", "2026-07-27T14:00:00+08:00"
            )
        with self.assertRaises(ValueError):
            validate_surprise_timing(
                "2026-07-27T15:00:00+08:00", "2026-07-27T14:00:00+08:00"
            )


if __name__ == "__main__":
    unittest.main()
