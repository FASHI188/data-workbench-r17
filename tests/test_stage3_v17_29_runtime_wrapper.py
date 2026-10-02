from __future__ import annotations

import copy
import hashlib
import unittest
from unittest.mock import patch

import stage3_financial_pdf_parser_v21 as wrapper


class V1729RuntimeWrapperTest(unittest.TestCase):
    def _target(self, raw: bytes) -> tuple[str, dict]:
        digest = hashlib.sha256(raw).hexdigest()
        target = {
            "announcement_id": "TEST_TARGET",
            "economic_date": "2024-06-30",
            "source_bytes": len(raw),
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
                "page": 7,
                "matched_alias": concept,
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
                "formal_runtime_generation": "V17.28",
                "proposed_runtime_generation": "V17.29",
                "exact_source_sha256": digest,
                "exact_source_bytes": target["source_bytes"],
                "split_equity_pattern": "SPLIT_LABEL_1_BEFORE_1_AFTER_AMOUNT",
                "column_role_gate_pass": True,
                "explicit_equity_pdf_text": True,
                "equity_value_inferred_as_assets_minus_liabilities": False,
                "non_balance_values_promoted": False,
                "ocr_enabled": False,
                "fuzzy_alias_matching_enabled": False,
                "source_policy_relaxed": False,
                "point_in_time_policy_relaxed": False,
                "issuer_gate_relaxed": False,
                "dual_column_identity": {
                    "tolerance": "0.005",
                    "columns": [
                        {
                            "column": "CURRENT",
                            "identity_residual_cny": "0",
                            "identity_relative_error": "0",
                        },
                        {
                            "column": "PRIOR",
                            "identity_residual_cny": "0",
                            "identity_relative_error": "0",
                        },
                    ],
                },
            },
        }

    def test_non_target_delegates_exact_object(self) -> None:
        raw = b"non-target"
        sentinel = {"parser_version": "V17.28", "payload": [1, 2, 3]}
        with patch.object(wrapper, "TARGETS", {}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=sentinel
        ):
            out = wrapper.parse_pdf_bytes(raw, "2024-06-30")
        self.assertIs(out, sentinel)

    def test_wrong_date_delegates_exact_object(self) -> None:
        raw = b"target-wrong-date"
        digest, target = self._target(raw)
        sentinel = {"parser_version": "V17.28", "payload": {"same": True}}
        with patch.object(wrapper, "TARGETS", {digest: target}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=sentinel
        ):
            out = wrapper.parse_pdf_bytes(raw, "2024-06-29")
        self.assertIs(out, sentinel)

    def test_wrong_byte_contract_delegates_exact_object(self) -> None:
        raw = b"target-wrong-bytes"
        digest, target = self._target(raw)
        target = copy.deepcopy(target)
        target["source_bytes"] += 1
        sentinel = {"parser_version": "V17.28", "payload": "unchanged"}
        with patch.object(wrapper, "TARGETS", {digest: target}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=sentinel
        ):
            out = wrapper.parse_pdf_bytes(raw, target["economic_date"])
        self.assertIs(out, sentinel)

    def test_exact_target_promotes_only_runtime_metadata(self) -> None:
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
            self.assertEqual(
                out["observations"][concept]["normalized_cny_value"],
                target["values"][concept][0],
            )
            self.assertEqual(
                out["observations"][concept]["extraction_scope"],
                wrapper.PRODUCTION_SCOPE,
            )
        block = out["balance_sheet_block"]
        self.assertTrue(block["inactive_runtime_wrapper"])
        self.assertFalse(block["runtime_promotion_authorized"])
        self.assertFalse(block["production_promotion_experiment_only"])
        self.assertEqual(block["formal_runtime_generation_before_activation"], "V17.28")
        self.assertEqual(block["formal_runtime_generation"], "V17.29")
        self.assertEqual(block["production_runtime_generation"], "V17.29")
        self.assertEqual(block["promotion_safety_pr"], 107)
        self.assertEqual(block["promotion_safety_run"], 31311296836)
        self.assertEqual(block["promotion_safety_artifact_id"], 9037500964)
        self.assertEqual(
            block["promotion_safety_artifact_digest"],
            wrapper.PROMOTION_SAFETY_ARTIFACT_DIGEST,
        )

    def test_mutated_target_value_fails_closed(self) -> None:
        raw = b"mutated-value"
        digest, target = self._target(raw)
        promotion = self._promotion_output(digest, target)
        promotion["observations"]["TOTAL_EQUITY"]["normalized_cny_value"] = "5"
        with patch.object(wrapper, "TARGETS", {digest: target}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=promotion
        ):
            with self.assertRaisesRegex(ValueError, "promotion-safety value changed"):
                wrapper.parse_pdf_bytes(raw, target["economic_date"])

    def test_missing_experiment_marker_fails_closed(self) -> None:
        raw = b"missing-marker"
        digest, target = self._target(raw)
        promotion = self._promotion_output(digest, target)
        promotion["balance_sheet_block"]["production_promotion_experiment_only"] = False
        with patch.object(wrapper, "TARGETS", {digest: target}), patch.object(
            wrapper.promotion, "parse_pdf_bytes", return_value=promotion
        ):
            with self.assertRaisesRegex(ValueError, "experiment marker missing"):
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


if __name__ == "__main__":
    unittest.main()
