from __future__ import annotations

import copy
import unittest
from decimal import Decimal
from unittest import mock

import stage3_financial_pdf_parser_v19_candidate as candidate
import stage3_financial_spatial_alias_v17_27_candidate as spatial


class V1727NormalEquityCandidateTests(unittest.TestCase):
    def test_exact_source_allowlist_and_values_are_frozen(self) -> None:
        self.assertEqual(len(candidate.TARGETS), 5)
        self.assertEqual(
            {row["announcement_id"] for row in candidate.TARGETS.values()},
            {
                "1200907104",
                "1201708762",
                "1202195310",
                "1202774611",
                "1203358200",
            },
        )
        self.assertEqual(
            candidate.TARGETS[
                "87a313e900dd74ec976e2c6e5c0eeb0e7c7cfd5e68c31e9ede3ae8c01c7e9d49"
            ]["values"],
            {
                "TOTAL_ASSETS": "4888152213.85",
                "TOTAL_LIABILITIES": "1510781556.82",
                "TOTAL_EQUITY": "3377370657.03",
            },
        )
        for row in candidate.TARGETS.values():
            values = row["values"]
            self.assertEqual(
                Decimal(values["TOTAL_ASSETS"]),
                Decimal(values["TOTAL_LIABILITIES"])
                + Decimal(values["TOTAL_EQUITY"]),
            )

    def test_candidate_scope_and_layout_are_frozen(self) -> None:
        self.assertEqual(
            candidate.ALLOWED_CONCEPTS,
            ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"),
        )
        self.assertEqual(candidate.TARGET_ANCHOR_PAGE, 8)
        self.assertEqual(
            candidate.TARGET_PAGES,
            {"TOTAL_ASSETS": 9, "TOTAL_LIABILITIES": 10, "TOTAL_EQUITY": 11},
        )
        self.assertEqual(
            spatial.TARGET_ALIASES,
            {
                "TOTAL_ASSETS": "资产总计",
                "TOTAL_LIABILITIES": "负债合计",
                "TOTAL_EQUITY": "所有者权益合计",
            },
        )
        self.assertIn("CANDIDATE", candidate.METHOD)
        self.assertIn("CANDIDATE", candidate.METHODOLOGY_VERSION)

    def test_non_target_source_returns_accepted_object_unchanged(self) -> None:
        sentinel = {
            "parser_version": "ACCEPTED_SENTINEL",
            "observations": {"TOTAL_ASSETS": {"status": "NOT_FOUND"}},
            "validation_errors": ["sentinel"],
        }
        with mock.patch.object(
            candidate.accepted, "parse_pdf_bytes", return_value=copy.deepcopy(sentinel)
        ):
            actual = candidate.parse_pdf_bytes(b"not-a-target-pdf", "2015-03-31")
        self.assertEqual(actual, sentinel)

    def test_promote_rejects_damaged_equity_alias(self) -> None:
        target = next(iter(candidate.TARGETS.values()))
        selected = {}
        for concept in candidate.ALLOWED_CONCEPTS:
            selected[concept] = {
                "alias": candidate.TARGET_ALIASES[concept],
                "page": candidate.TARGET_PAGES[concept],
                "statement_anchor_page": candidate.TARGET_ANCHOR_PAGE,
                "statement_role": "GROUP",
                "value": target["values"][concept],
                "raw_value": target["values"][concept],
                "unit": "元",
                "unit_multiplier": "1",
                "period_evidence": {
                    "matched": True,
                    "expected_economic_date": target["economic_date"],
                },
            }
        selected["TOTAL_EQUITY"]["strict_corrupted_equity_alias_v17_24"] = True
        diagnostic = {
            "recovered": True,
            "generic_group_witness": {"promoted_generic_group_count": 1},
            "selected": selected,
            "identity": {
                "identity_relative_error": "0",
                "identity_residual_cny": "0.00",
                "page_span": 2,
                "anchor_span": 0,
            },
            "column_role_gate": {
                "pass": True,
                "concepts": {
                    concept: {"pass": True} for concept in candidate.ALLOWED_CONCEPTS
                },
            },
        }
        with self.assertRaisesRegex(ValueError, "damaged alias"):
            candidate._validate_diagnostic(diagnostic, target)


if __name__ == "__main__":
    unittest.main()
