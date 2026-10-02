import unittest
from datetime import date

from scripts.build_stage3_filing_ledger import classify_title
from scripts.finalize_stage3_filing_ledger import next_session, remap_effective_code


class FilingTitleTests(unittest.TestCase):
    def test_full_and_revised_reports(self):
        econ, kind, full = classify_title("2024年年度报告", "ANNUAL")
        self.assertEqual(econ, "2024-12-31")
        self.assertEqual(kind, "ORIGINAL_FULL_REPORT")
        self.assertTrue(full)

        econ, kind, full = classify_title("2024年年度报告（修订版）", "ANNUAL")
        self.assertEqual(econ, "2024-12-31")
        self.assertEqual(kind, "REVISED_FULL_REPORT")
        self.assertTrue(full)

    def test_summary_and_notice_never_become_full_report(self):
        _, kind, full = classify_title("2024年年度报告摘要", "ANNUAL")
        self.assertEqual(kind, "SUMMARY")
        self.assertFalse(full)

        _, kind, full = classify_title("关于2024年年度报告的更正公告", "ANNUAL")
        self.assertEqual(kind, "CORRECTION_OR_SUPPLEMENT_NOTICE")
        self.assertFalse(full)

    def test_quarter_period_mapping(self):
        self.assertEqual(classify_title("2025年第一季度报告", "Q1")[0], "2025-03-31")
        self.assertEqual(classify_title("2025年半年度报告", "SEMI")[0], "2025-06-30")
        self.assertEqual(classify_title("2025年第三季度报告", "Q3")[0], "2025-09-30")


class AvailabilityTests(unittest.TestCase):
    def test_date_only_is_strictly_next_trading_session(self):
        days = [date(2026, 7, 24), date(2026, 7, 27), date(2026, 7, 28)]
        self.assertEqual(next_session(date(2026, 7, 24), days), date(2026, 7, 27))
        self.assertEqual(next_session(date(2026, 7, 26), days), date(2026, 7, 27))
        self.assertEqual(next_session(date(2026, 7, 27), days), date(2026, 7, 28))

    def test_code_transition_between_publication_and_effective_session(self):
        intervals = {
            ("SZSE", "000022"): (date(1993, 5, 5), date(2018, 12, 26)),
            ("SZSE", "001872"): (date(2018, 12, 26), None),
        }
        transitions = [
            {
                "exchange": "SZSE",
                "old_code": "000022",
                "new_code": "001872",
                "effective_date": "2018-12-26",
            }
        ]
        self.assertEqual(
            remap_effective_code("SZSE", "000022", date(2018, 12, 26), intervals, transitions),
            "001872",
        )
        self.assertEqual(
            remap_effective_code("SZSE", "000022", date(2018, 12, 25), intervals, transitions),
            "000022",
        )

    def test_sse_601313_to_601360_filing_identity_transition(self):
        intervals = {
            ("SSE", "601313"): (date(2012, 1, 16), date(2018, 2, 28)),
            ("SSE", "601360"): (date(2018, 2, 28), None),
        }
        transitions = [
            {
                "exchange": "SSE",
                "old_code": "601313",
                "new_code": "601360",
                "effective_date": "2018-02-28",
            }
        ]
        self.assertEqual(
            remap_effective_code("SSE", "601313", date(2018, 2, 14), intervals, transitions),
            "601313",
        )
        self.assertEqual(
            remap_effective_code("SSE", "601313", date(2018, 2, 28), intervals, transitions),
            "601360",
        )


if __name__ == "__main__":
    unittest.main()
