from __future__ import annotations

import copy
import unittest

import accept_stage3_s3g1j_v17_24_production_v2 as acceptance


class V1724AcceptanceBaselineTests(unittest.TestCase):
    aid = "1225153907"

    def setUp(self) -> None:
        acceptance._BASELINE_ROWS.clear()

    @staticmethod
    def _parsed(block: dict) -> dict:
        return {
            "observations": {
                "TOTAL_ASSETS": {"status": "FOUND"},
                "TOTAL_LIABILITIES": {"status": "FOUND"},
                "TOTAL_EQUITY": {"status": "FOUND"},
            },
            "balance_sheet_block": copy.deepcopy(block),
            "validation_errors": [],
        }

    def test_legacy_accepted_block_may_omit_later_no_inference_field(self) -> None:
        block = {
            "arbitration": (
                "V17_15_GROUP_PERIOD_FROZEN_DATE_COLUMN_A_EQUALS_L_PLUS_E_"
                "STRICT_ADJACENT_ROW"
            ),
            "identity_tolerance": "0.005",
            "identity_residual_cny": "0",
            "global_row_tolerance_changed": False,
            "selected_aliases": {
                "TOTAL_ASSETS": "资产总计",
                "TOTAL_LIABILITIES": "负债合计",
                "TOTAL_EQUITY": "股东权益合计",
            },
        }
        acceptance._BASELINE_ROWS[self.aid] = {
            "balance_sheet_block": copy.deepcopy(block)
        }
        acceptance._validate_recovery(self.aid, self._parsed(block))

    def test_previous_recovery_must_equal_authoritative_v17_21_block(self) -> None:
        baseline = {
            "arbitration": "LOCKED_V17_21",
            "identity_tolerance": "0.005",
            "global_row_tolerance_changed": False,
        }
        changed = copy.deepcopy(baseline)
        changed["arbitration"] = "CHANGED"
        acceptance._BASELINE_ROWS[self.aid] = {
            "balance_sheet_block": copy.deepcopy(baseline)
        }
        with self.assertRaisesRegex(
            ValueError, "previous accepted balance-sheet block changed"
        ):
            acceptance._validate_recovery(self.aid, self._parsed(changed))

    def test_explicit_inference_true_is_rejected_even_if_baseline_contains_it(self) -> None:
        block = {
            "arbitration": "LOCKED_V17_21",
            "identity_tolerance": "0.005",
            "global_row_tolerance_changed": False,
            "e_equals_a_minus_l_inference": True,
        }
        acceptance._BASELINE_ROWS[self.aid] = {
            "balance_sheet_block": copy.deepcopy(block)
        }
        with self.assertRaisesRegex(ValueError, "E=A-L inference enabled"):
            acceptance._validate_recovery(self.aid, self._parsed(block))


if __name__ == "__main__":
    unittest.main()
