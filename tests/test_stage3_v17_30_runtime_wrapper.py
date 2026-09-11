from __future__ import annotations

import copy
import hashlib
import unittest
from unittest.mock import patch

import stage3_financial_pdf_parser_v22 as wrapper


class V1730RuntimeWrapperTest(unittest.TestCase):
    def _target(self, raw: bytes) -> tuple[str, dict]:
        digest = hashlib.sha256(raw).hexdigest()
        target = {
            "announcement_id": "TEST_TARGET",
            "economic_date": "2025-03-31",
            "source_bytes": len(raw),
            "selected_pages": {"TOTAL_ASSETS": 7, "TOTAL_LIABILITIES": 8, "TOTAL_EQUITY": 8},
            "values": {
                "TOTAL_ASSETS": ["10", "9"],
                "TOTAL_LIABILITIES": ["4", "3"],
                "TOTAL_EQUITY": ["6", "6"],
            },
        }
        return digest, target

    def _promotion_output(self, digest: str, target: dict) -> dict:
        observations = {
            concept: {
                "concept": concept,
                "status": "FOUND",
                "normalized_cny_value": target["values"][concept][0],
                "page": target["selected_pages"][concept],
                "matched_alias": wrapper.promotion.TARGET_ALIASES[concept],
                "extraction_scope": wrapper.promotion.METHOD,
            }
            for concept in wrapper.ALLOWED_CONCEPTS
        }
        return {
            "parser_version": wrapper.promotion.METHOD,
            "validation_errors": [],
            "tier1_found": 0,
            "tier2_found": 3,
            "observations": observations,
            "balance_sheet_block": {
                "candidate_only": False,
                "production_promotion_experiment_only": True,
                "runtime_promotion_authorized": False,
                "formal_runtime_generation": "V17.29",
                "proposed_runtime_generation": "V17.30_NOT_AUTHORIZED",
                "exact_source_sha256": digest,
                "exact_source_bytes": target["source_bytes"],
                "cross_page_equity_pattern": "ONE_PAGE_EXACT_ALIAS_CONTINUATION",
                "cross_page_equity": {
                    "equity_amount_page": 8,
                    "suffix_page": 9,
                    "equity_prefix": "所有者权益（或股东权益）合",
                    "equity_suffix": "计",
                    "completed_alias": "所有者权益（或股东权益）合计",
                },
                "column_role_gate_pass": True,
                "explicit_equity_pdf_text": True,
                "equity_value_inferred_as_assets_minus_liabilities": False,
                "non_balance_values_promoted": False,
                "ocr_enabled": False,
                "fuzzy_alias_matching_enabled": False,
                "source_policy_relaxed": False,
                "point_in_time_policy_relaxed": False,
                "issuer_gate_relaxed": False,
                "accounting_tolerance_relaxed": False,
                "dual_column_identity": {
                    "tolerance": "0.005",
                    "columns": [
                        {"column": "CURRENT", "identity_residual_cny": "0", "identity_relative_error": "0"},
                        {"column": "PRIOR", "identity_residual_cny": "0", "identity_relative_error": "0"},
                    ],
                },
            },
        }

    def test_non_target_delegates_exact_object(self) -> None:
        raw = b"non-target"
        sentinel = {"parser_version": "V17.29", "payload": [1, 2, 3]}
        with patch.object(wrapper, "TARGETS", {}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=sentinel
        ):
            out = wrapper.parse_pdf_bytes(raw, "2025-03-31")
        self.assertIs(out, sentinel)

    def test_wrong_date_delegates_exact_object(self) -> None:
        raw = b"target-wrong-date"
        digest, target = self._target(raw)
        sentinel = {"parser_version": "V17.29", "payload": {"same": True}}
        with patch.object(wrapper, "TARGETS", {digest: target}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=sentinel
        ):
            out = wrapper.parse_pdf_bytes(raw, "2025-03-30")
        self.assertIs(out, sentinel)

    def test_wrong_byte_contract_delegates_exact_object(self) -> None:
        raw = b"target-wrong-bytes"
        digest, target = self._target(raw)
        target = copy.deepcopy(target)
        target["source_bytes"] += 1
        sentinel = {"parser_version": "V17.29", "payload": "unchanged"}
        with patch.object(wrapper, "TARGETS", {digest: target}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=sentinel
        ):
            out = wrapper.parse_pdf_bytes(raw, target["economic_date"])
        self.assertIs(out, sentinel)

    def test_exact_target_promotes_only_inactive_runtime_metadata(self) -> None:
        raw = b"exact-target"
        digest, target = self._target(raw)
        promotion = self._promotion_output(digest, target)
        with patch.object(wrapper, "TARGETS", {digest: target}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=promotion
        ):
            out = wrapper.parse_pdf_bytes(raw, target["economic_date"])

        self.assertEqual(out["parser_version"], wrapper.METHOD)
        self.assertEqual(promotion["parser_version"], wrapper.promotion.METHOD)
        for concept in wrapper.ALLOWED_CONCEPTS:
            self.assertEqual(out["observations"][concept]["normalized_cny_value"], target["values"][concept][0])
            self.assertEqual(out["observations"][concept]["extraction_scope"], wrapper.PRODUCTION_SCOPE)
        block = out["balance_sheet_block"]
        self.assertTrue(block["inactive_runtime_wrapper"])
        self.assertFalse(block["runtime_promotion_authorized"])
        self.assertFalse(block["v17_30_authority_activated"])
        self.assertEqual(block["formal_runtime_generation_before_activation"], "V17.29")
        self.assertEqual(block["formal_runtime_generation"], "V17.30")
        self.assertEqual(block["production_runtime_generation"], "V17.30")
        self.assertEqual(block["promotion_safety_pr"], 121)
        self.assertEqual(block["promotion_safety_run"], 31452374012)
        self.assertEqual(block["promotion_safety_artifact_id"], 9086776910)

    def test_mutated_target_value_fails_closed(self) -> None:
        raw = b"mutated-value"
        digest, target = self._target(raw)
        promotion = self._promotion_output(digest, target)
        promotion["observations"]["TOTAL_EQUITY"]["normalized_cny_value"] = "5"
        with patch.object(wrapper, "TARGETS", {digest: target}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=promotion
        ):
            with self.assertRaisesRegex(ValueError, "value changed"):
                wrapper.parse_pdf_bytes(raw, target["economic_date"])

    def test_mutated_cross_page_suffix_fails_closed(self) -> None:
        raw = b"mutated-cross-page"
        digest, target = self._target(raw)
        promotion = self._promotion_output(digest, target)
        promotion["balance_sheet_block"]["cross_page_equity"]["equity_suffix"] = "错误"
        with patch.object(wrapper, "TARGETS", {digest: target}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=promotion
        ):
            with self.assertRaisesRegex(ValueError, "alias completion changed"):
                wrapper.parse_pdf_bytes(raw, target["economic_date"])

    def test_changed_accounting_tolerance_fails_closed(self) -> None:
        raw = b"changed-tolerance"
        digest, target = self._target(raw)
        promotion = self._promotion_output(digest, target)
        promotion["balance_sheet_block"]["dual_column_identity"]["tolerance"] = "0.01"
        with patch.object(wrapper, "TARGETS", {digest: target}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=promotion
        ):
            with self.assertRaisesRegex(ValueError, "accounting tolerance changed"):
                wrapper.parse_pdf_bytes(raw, target["economic_date"])

    def test_forbidden_relaxation_fails_closed(self) -> None:
        raw = b"relaxed-source-policy"
        digest, target = self._target(raw)
        promotion = self._promotion_output(digest, target)
        promotion["balance_sheet_block"]["source_policy_relaxed"] = True
        with patch.object(wrapper, "TARGETS", {digest: target}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=promotion
        ):
            with self.assertRaisesRegex(ValueError, "forbidden relaxation changed"):
                wrapper.parse_pdf_bytes(raw, target["economic_date"])


if __name__ == "__main__":
    unittest.main()
