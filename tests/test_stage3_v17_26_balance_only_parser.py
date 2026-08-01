from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import stage3_financial_pdf_parser_v18 as production


class _Digest:
    def __init__(self, value: str):
        self.value = value

    def hexdigest(self) -> str:
        return self.value


class V1726BalanceOnlyParserTests(unittest.TestCase):
    def parsed_target(self, digest: str) -> dict:
        target = production.TARGETS[digest]
        observations = {
            concept: {
                "status": "FOUND",
                "raw_value": value,
                "normalized_cny_value": value,
                "unit": "元",
                "unit_multiplier": "1",
                "page": 1,
                "matched_alias": concept,
                "confidence": "HIGH",
            }
            for concept, value in target["values"].items()
        }
        observations.update(
            {
                "OPERATING_REVENUE": {
                    "status": "FOUND",
                    "normalized_cny_value": "747884223.85",
                },
                "OPERATING_CASH_FLOW": {
                    "status": "FOUND",
                    "normalized_cny_value": "-45.75",
                },
            }
        )
        return {
            "parser_version": "V17.25",
            "observations": observations,
            "tier1_found": 2,
            "tier2_found": 3,
            "balance_sheet_block": {
                "identity_relative_error": "0",
                "column_role_gate_pass": True,
            },
            "validation_errors": [],
        }

    def test_non_target_returns_accepted_result_unchanged(self) -> None:
        baseline = {"parser_version": "V17.25", "observations": {}}
        with patch.object(
            production.accepted, "parse_pdf_bytes", return_value=baseline
        ) as accepted_parse:
            result = production.parse_pdf_bytes(b"non-target", "2020-03-31")
        self.assertEqual(result, baseline)
        accepted_parse.assert_called_once()

    def test_exact_target_emits_only_validated_balance_concepts(self) -> None:
        digest = next(iter(production.TARGETS))
        target = production.TARGETS[digest]
        baseline = self.parsed_target(digest)
        with patch.object(
            production.hashlib, "sha256", return_value=_Digest(digest)
        ), patch.object(
            production.accepted, "parse_pdf_bytes", return_value=baseline
        ):
            result = production.parse_pdf_bytes(
                b"target", target["economic_date"]
            )
        found = {
            concept
            for concept, observation in result["observations"].items()
            if observation.get("status") == "FOUND"
        }
        self.assertEqual(found, set(production.ALLOWED_CONCEPTS))
        self.assertEqual(result["tier1_found"], 0)
        self.assertEqual(result["tier2_found"], 3)
        self.assertEqual(result["parser_version"], production.METHOD)
        self.assertFalse(
            result["balance_sheet_block"]["non_balance_values_promoted"]
        )
        self.assertEqual(
            result["observations"]["OPERATING_CASH_FLOW"],
            {"status": "NOT_FOUND", "reason": production.FILTER_REASON},
        )

    def test_exact_target_wrong_date_remains_unchanged(self) -> None:
        digest = next(iter(production.TARGETS))
        baseline = self.parsed_target(digest)
        with patch.object(
            production.hashlib, "sha256", return_value=_Digest(digest)
        ), patch.object(
            production.accepted, "parse_pdf_bytes", return_value=baseline
        ):
            result = production.parse_pdf_bytes(b"target", "2000-01-01")
        self.assertEqual(result, baseline)

    def test_exact_target_value_drift_fails_closed(self) -> None:
        digest = next(iter(production.TARGETS))
        target = production.TARGETS[digest]
        baseline = self.parsed_target(digest)
        baseline = copy.deepcopy(baseline)
        baseline["observations"]["TOTAL_ASSETS"]["normalized_cny_value"] = "1"
        with patch.object(
            production.hashlib, "sha256", return_value=_Digest(digest)
        ), patch.object(
            production.accepted, "parse_pdf_bytes", return_value=baseline
        ):
            with self.assertRaisesRegex(ValueError, "value mismatch"):
                production.parse_pdf_bytes(b"target", target["economic_date"])

    def test_exact_target_validation_error_fails_closed(self) -> None:
        digest = next(iter(production.TARGETS))
        target = production.TARGETS[digest]
        baseline = self.parsed_target(digest)
        baseline["validation_errors"] = ["BROKEN"]
        with patch.object(
            production.hashlib, "sha256", return_value=_Digest(digest)
        ), patch.object(
            production.accepted, "parse_pdf_bytes", return_value=baseline
        ):
            with self.assertRaisesRegex(ValueError, "retained validation errors"):
                production.parse_pdf_bytes(b"target", target["economic_date"])


if __name__ == "__main__":
    unittest.main()
