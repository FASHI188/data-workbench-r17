from __future__ import annotations

import unittest

import extract_stage3_financial_pdf_values_v10 as v15


def obs(value: str, *, raw: str | None = None, unit: str = "元", multiplier: str = "1"):
    return {
        "status": "FOUND",
        "raw_value": raw if raw is not None else value,
        "normalized_cny_value": value,
        "unit": unit,
        "unit_multiplier": multiplier,
    }


def valid_candidate(cid: str = "2", title: str = "2024年年度报告") -> dict:
    return {
        "id": cid,
        "title": title,
        "sha256": f"sha-{cid}",
        "parsed": {
            "validation_errors": [],
            "balance_sheet_block": {"arbitration": "TEST"},
            "tier1_found": 6,
            "tier2_found": 3,
            "observations": {
                "TOTAL_ASSETS": obs("100.00"),
                "TOTAL_LIABILITIES": obs("60.00"),
                "TOTAL_EQUITY": obs("40.00"),
                "REVENUE": obs("20.00"),
            },
        },
    }


def invalid_balance_candidate(cid: str = "1", title: str = "2024年年度报告") -> dict:
    return {
        "id": cid,
        "title": title,
        "sha256": f"sha-{cid}",
        "error": "NO_VALIDATED_BALANCE_SHEET_BLOCK",
        "parsed": {
            "validation_errors": ["NO_VALIDATED_BALANCE_SHEET_BLOCK"],
            "balance_sheet_block": None,
            "tier1_found": 6,
            "tier2_found": 0,
            "observations": {
                "TOTAL_ASSETS": obs("100.00"),
                "REVENUE": obs("20.00"),
            },
        },
    }


class UniqueUsableTieV15Tests(unittest.TestCase):
    def test_report_signature_ignores_issuer_prefix(self):
        self.assertEqual(
            v15._report_signature("京沪高速铁路股份有限公司2020年第三季度报告"),
            ("2020", "第三季度报告"),
        )
        self.assertEqual(
            v15._report_signature("2020年第三季度报告"),
            ("2020", "第三季度报告"),
        )

    def test_unique_valid_candidate_is_accepted_when_overlap_agrees(self):
        bad = invalid_balance_candidate("1")
        good = valid_candidate("2")
        chosen, err = v15._unique_usable_tie_candidate([bad, good])
        self.assertIsNone(err)
        self.assertEqual(chosen["id"], "2")

    def test_declared_unit_rounding_is_accepted(self):
        # Exact shape verified for 603100 2021 annual: summary reports 万元 with
        # two decimals while the full report provides yuan-level exact values.
        good = valid_candidate("2", "川仪股份2021年年度报告")
        bad = invalid_balance_candidate("1", "川仪股份2021年年度报告")
        good["parsed"]["observations"]["TOTAL_ASSETS"] = obs(
            "6638003235.79", raw="6638003235.79", unit="元", multiplier="1"
        )
        bad["parsed"]["observations"]["TOTAL_ASSETS"] = obs(
            "6638003200.00", raw="663800.32", unit="万元", multiplier="10000"
        )
        good["parsed"]["observations"]["EQUITY_ATTRIBUTABLE_TO_PARENT"] = obs(
            "3174299758.06", raw="3174299758.06", unit="元", multiplier="1"
        )
        bad["parsed"]["observations"]["EQUITY_ATTRIBUTABLE_TO_PARENT"] = obs(
            "3174299800.00", raw="317429.98", unit="万元", multiplier="10000"
        )
        chosen, err = v15._unique_usable_tie_candidate([bad, good])
        self.assertIsNone(err)
        self.assertEqual(chosen["id"], "2")

    def test_difference_beyond_display_rounding_is_rejected(self):
        bad = invalid_balance_candidate("1")
        bad["parsed"]["observations"]["REVENUE"] = obs(
            "200000100.00", raw="20000.01", unit="万元", multiplier="10000"
        )
        good = valid_candidate("2")
        good["parsed"]["observations"]["REVENUE"] = obs(
            "200000000.00", raw="200000000.00", unit="元", multiplier="1"
        )
        chosen, err = v15._unique_usable_tie_candidate([bad, good])
        self.assertIsNone(chosen)
        self.assertIn("conflict", err)

    def test_conflicting_overlap_is_rejected(self):
        bad = invalid_balance_candidate("1")
        bad["parsed"]["observations"]["REVENUE"] = obs("21.00")
        good = valid_candidate("2")
        chosen, err = v15._unique_usable_tie_candidate([bad, good])
        self.assertIsNone(chosen)
        self.assertIn("conflict", err)

    def test_network_failure_is_not_accepted(self):
        bad = invalid_balance_candidate("1")
        bad["error"] = "RuntimeError('connection timeout')"
        chosen, err = v15._unique_usable_tie_candidate([bad, valid_candidate("2")])
        self.assertIsNone(chosen)
        self.assertIn("narrow balance-parser failure", err)

    def test_different_report_signature_is_rejected(self):
        bad = invalid_balance_candidate("1", "2023年年度报告")
        good = valid_candidate("2", "2024年年度报告")
        chosen, err = v15._unique_usable_tie_candidate([bad, good])
        self.assertIsNone(chosen)
        self.assertIn("report signatures differ", err)

    def test_two_valid_candidates_do_not_use_v15_exception(self):
        chosen, err = v15._unique_usable_tie_candidate([valid_candidate("1"), valid_candidate("2")])
        self.assertIsNone(chosen)
        self.assertIn("exactly one independently usable", err)

    def test_single_candidate_does_not_use_v15_exception(self):
        chosen, err = v15._unique_usable_tie_candidate([valid_candidate("1")])
        self.assertIsNone(chosen)
        self.assertIn("exactly two", err)


if __name__ == "__main__":
    unittest.main()
