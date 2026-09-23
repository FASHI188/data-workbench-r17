from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import stage3_financial_pdf_parser_v17 as production


class _Digest:
    def __init__(self, value: str):
        self.value = value

    def hexdigest(self) -> str:
        return self.value


class V1725ProductionParserTests(unittest.TestCase):
    def accepted_failure(self) -> dict:
        return {
            "parser_version": "V17_24",
            "observations": {
                concept: {"status": "NOT_FOUND"}
                for concept in production.CONCEPTS
            },
            "balance_sheet_block": None,
            "validation_errors": ["NO_VALIDATED_BALANCE_SHEET_BLOCK"],
        }

    def candidate_success(self) -> dict:
        period = {
            concept: {
                "expected_economic_date": production.TARGET_ECONOMIC_DATE,
                "matched": True,
            }
            for concept in production.CONCEPTS
        }
        return {
            "parser_version": "CANDIDATE",
            "observations": {
                concept: {"status": "FOUND"}
                for concept in production.CONCEPTS
            },
            "balance_sheet_block": {
                "arbitration": "V16_7_GROUP_PERIOD_FROZEN_DATE_COLUMN_A_EQUALS_L_PLUS_E",
                "identity_tolerance": "0.005",
                "identity_relative_error": "0",
                "identity_residual_cny": "0.00",
                "column_role_gate_pass": True,
                "selected_pages": copy.deepcopy(production.TARGET_SELECTED_PAGES),
                "selected_aliases": copy.deepcopy(production.TARGET_SELECTED_ALIASES),
                "selected_period_evidence": period,
            },
            "validation_errors": [],
        }

    def witness(self) -> dict:
        return {
            "witness_alias": "归属于母公司所有者权益合计",
            "total_equity_alias": "所有者权益合计",
            "witness_amounts": list(production.TARGET_WITNESS_AMOUNTS),
            "total_equity_amounts": list(production.TARGET_WITNESS_AMOUNTS),
            "same_page": True,
            "amounts_equal": True,
            "amount_column_count": 2,
        }

    def test_non_target_source_returns_v17_24_result_unchanged(self):
        baseline = self.accepted_failure()
        with patch.object(
            production.accepted, "parse_pdf_bytes", return_value=baseline
        ) as accepted_parse, patch.object(
            production.candidate, "parse_pdf_bytes"
        ) as candidate_parse:
            result = production.parse_pdf_bytes(b"not-target", "2020-03-31")
        self.assertEqual(result, baseline)
        accepted_parse.assert_called_once()
        candidate_parse.assert_not_called()

    def test_exact_target_becomes_production_recovery(self):
        current = self.accepted_failure()
        proposed = self.candidate_success()
        witness = self.witness()
        with patch.object(
            production.hashlib,
            "sha256",
            return_value=_Digest(production.TARGET_SOURCE_SHA256),
        ), patch.object(
            production.accepted, "parse_pdf_bytes", return_value=current
        ), patch.object(
            production.candidate, "parse_pdf_bytes", return_value=proposed
        ), patch.object(
            production, "_exact_witness", return_value=witness
        ):
            result = production.parse_pdf_bytes(
                b"exact-target", production.TARGET_ECONOMIC_DATE
            )
        block = result["balance_sheet_block"]
        self.assertEqual(result["parser_version"], production.METHOD)
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(
            block["arbitration"],
            "V17_25_EXACT_SOURCE_GENERIC_GROUP_WITNESS_A_EQUALS_L_PLUS_E",
        )
        self.assertIs(block["candidate_only"], False)
        self.assertEqual(block["production_runtime_generation"], "V17.25")
        self.assertEqual(
            block["exact_source_sha256"], production.TARGET_SOURCE_SHA256
        )
        self.assertEqual(block["generic_group_witness"], witness)
        self.assertIs(block["global_row_tolerance_changed"], False)
        self.assertIs(block["e_equals_a_minus_l_inference"], False)

    def test_exact_target_fails_closed_when_candidate_does_not_recover(self):
        current = self.accepted_failure()
        proposed = self.accepted_failure()
        with patch.object(
            production.hashlib,
            "sha256",
            return_value=_Digest(production.TARGET_SOURCE_SHA256),
        ), patch.object(
            production.accepted, "parse_pdf_bytes", return_value=current
        ), patch.object(
            production.candidate, "parse_pdf_bytes", return_value=proposed
        ):
            with self.assertRaisesRegex(ValueError, "candidate did not recover"):
                production.parse_pdf_bytes(
                    b"exact-target", production.TARGET_ECONOMIC_DATE
                )


if __name__ == "__main__":
    unittest.main()
