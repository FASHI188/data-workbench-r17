from __future__ import annotations

import copy
import unittest
from unittest import mock

import stage3_financial_pdf_parser_v20_candidate as candidate


class _Digest:
    def __init__(self, value: str) -> None:
        self.value = value

    def hexdigest(self) -> str:
        return self.value


class V1728SplitEquityCandidateTests(unittest.TestCase):
    def test_exact_target_population_is_frozen(self) -> None:
        self.assertEqual(
            set(candidate.TARGETS),
            {
                "b2aa4afa67e2b02010d5ba708d4e5fe02138623ff4bc48718c03029111a64568",
                "0bd1da8bdac0aff2a3e99b83adc29e7b60e959c99dd29b8ab88cbda1344b441c",
            },
        )
        self.assertEqual(
            {row["announcement_id"] for row in candidate.TARGETS.values()},
            {"1207621057", "1209825769"},
        )
        self.assertEqual(
            set(candidate.ALLOWED_CONCEPTS),
            {"TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"},
        )

    def test_non_target_delegates_formal_v17_27_output_exactly(self) -> None:
        formal = {
            "parser_version": "V17_27_FORMAL",
            "observations": {"REVENUE": {"status": "FOUND", "raw_value": "1"}},
            "validation_errors": ["retained"],
        }
        expected = copy.deepcopy(formal)
        with mock.patch.object(
            candidate.accepted, "parse_pdf_bytes", return_value=copy.deepcopy(formal)
        ):
            actual = candidate.parse_pdf_bytes(b"not-a-target", "2020-03-31")
        self.assertEqual(actual, expected)

    def test_target_sha_with_wrong_date_delegates_formal_output(self) -> None:
        digest, target = next(iter(candidate.TARGETS.items()))
        formal = {"parser_version": "V17_27_FORMAL", "validation_errors": ["x"]}
        with mock.patch.object(
            candidate.accepted, "parse_pdf_bytes", return_value=copy.deepcopy(formal)
        ), mock.patch.object(
            candidate.hashlib, "sha256", return_value=_Digest(digest)
        ):
            actual = candidate.parse_pdf_bytes(b"synthetic", "1999-01-01")
        self.assertEqual(actual, formal)
        self.assertNotEqual(target["economic_date"], "1999-01-01")

    def test_formal_runtime_unexpected_recovery_fails_closed(self) -> None:
        digest, target = next(iter(candidate.TARGETS.items()))
        formal = {
            "observations": {
                concept: {"status": "FOUND"} for concept in candidate.ALLOWED_CONCEPTS
            },
            "balance_sheet_block": {},
            "validation_errors": [],
        }
        with mock.patch.object(
            candidate.accepted, "parse_pdf_bytes", return_value=formal
        ), mock.patch.object(
            candidate.hashlib, "sha256", return_value=_Digest(digest)
        ):
            with self.assertRaisesRegex(ValueError, "unexpectedly recovered"):
                candidate.parse_pdf_bytes(b"synthetic", target["economic_date"])

    def test_promoted_scope_contains_only_three_balance_totals(self) -> None:
        digest, target = next(iter(candidate.TARGETS.items()))
        formal = {
            "observations": {
                "REVENUE": {"status": "FOUND", "raw_value": "999"},
                "NET_PROFIT": {"status": "FOUND", "raw_value": "888"},
            },
            "validation_errors": ["formal-fail-closed"],
        }
        rows = {}
        for concept in candidate.ALLOWED_CONCEPTS:
            value = target["values"][concept][0]
            rows[concept] = {
                "pair": [
                    {"raw": value, "value": value, "x0": 300},
                    {
                        "raw": target["values"][concept][1],
                        "value": target["values"][concept][1],
                        "x0": 440,
                    },
                ]
            }
        rows["TOTAL_EQUITY"]["row_gaps"] = ["8", "8"]
        evidence = {
            "rows": rows,
            "group_event": {"page": target["group_anchor_page"], "role": "GROUP"},
            "header_context": {"date_text_object_count": 2, "unit_text_object_count": 1},
            "column_alignment": {"absolute_x0_drift": ["0", "0"]},
            "identity": {
                "tolerance": "0.005",
                "columns": [
                    {"column": "CURRENT", "identity_residual_cny": "0.00"},
                    {"column": "PRIOR", "identity_residual_cny": "0.00"},
                ],
            },
        }
        promoted = candidate._promote(formal, digest, target, evidence)
        found = {
            concept
            for concept, row in promoted["observations"].items()
            if row.get("status") == "FOUND"
        }
        self.assertEqual(found, set(candidate.ALLOWED_CONCEPTS))
        self.assertEqual(
            promoted["observations"]["REVENUE"]["reason"], candidate.FILTER_REASON
        )
        self.assertEqual(promoted["tier1_found"], 0)
        self.assertEqual(promoted["tier2_found"], 3)
        block = promoted["balance_sheet_block"]
        self.assertTrue(block["candidate_only"])
        self.assertEqual(block["exact_source_sha256"], digest)
        self.assertTrue(block["explicit_equity_pdf_text"])
        self.assertFalse(block["equity_value_inferred_as_assets_minus_liabilities"])
        self.assertFalse(block["non_balance_values_promoted"])
        self.assertFalse(block["ocr_enabled"])
        self.assertFalse(block["fuzzy_alias_matching_enabled"])

    def test_identity_mismatch_fails_closed(self) -> None:
        target = copy.deepcopy(next(iter(candidate.TARGETS.values())))
        target["values"]["TOTAL_EQUITY"][0] = "1"
        with self.assertRaisesRegex(ValueError, "identity failed"):
            candidate._validate_identity(target)

    def test_single_or_missing_split_sequence_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "sequence count"):
            candidate._find_split_equity([], ["1", "2"])

    def test_source_byte_length_is_strict(self) -> None:
        target = next(iter(candidate.TARGETS.values()))
        with self.assertRaisesRegex(ValueError, "byte length changed"):
            candidate._recover_target(b"too-short", target)


if __name__ == "__main__":
    unittest.main()
