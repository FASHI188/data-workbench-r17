from __future__ import annotations

import unittest

import extract_stage3_financial_pdf_values_v10 as v15


def obs(value: str):
    return {"status": "FOUND", "normalized_cny_value": value}


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
                "TOTAL_ASSETS": obs("100"),
                "TOTAL_LIABILITIES": obs("60"),
                "TOTAL_EQUITY": obs("40"),
                "REVENUE": obs("20"),
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
                "TOTAL_ASSETS": obs("100"),
                "REVENUE": obs("20"),
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

    def test_conflicting_overlap_is_rejected(self):
        bad = invalid_balance_candidate("1")
        bad["parsed"]["observations"]["REVENUE"] = obs("21")
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
