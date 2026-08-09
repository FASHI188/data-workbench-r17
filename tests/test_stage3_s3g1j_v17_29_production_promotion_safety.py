from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

import stage3_financial_pdf_parser_v21_production_candidate as production


class V1729ProductionPromotionSafetyTests(unittest.TestCase):
    def test_accepted_candidate_identity_is_hard_bound(self) -> None:
        self.assertEqual(production.ACCEPTED_CANDIDATE_PR, 105)
        self.assertEqual(
            production.ACCEPTED_CANDIDATE_HEAD,
            "51bd3ccc0013c2c9a6a55bbb54a1d82dcbd2974e",
        )
        self.assertEqual(production.ACCEPTED_CANDIDATE_RUN, 31310230656)
        self.assertEqual(production.ACCEPTED_CANDIDATE_ARTIFACT_ID, 9037206225)
        self.assertEqual(
            production.ACCEPTED_CANDIDATE_ARTIFACT_DIGEST,
            "sha256:fc8ff09522b67df8e8209f7e5d88a0d768ef68987201dbb8087df2b6424bb99c",
        )

    def test_exact_seven_target_population_and_tolerance(self) -> None:
        self.assertEqual(len(production.TARGETS), 7)
        self.assertEqual(
            sorted(target["announcement_id"] for target in production.TARGETS.values()),
            [
                "1215186538",
                "1219426855",
                "1219792633",
                "1219840508",
                "1219879687",
                "1220087244",
                "1221006100",
            ],
        )
        self.assertEqual(production.IDENTITY_TOLERANCE, Decimal("0.005"))
        self.assertEqual(production.MAX_ROW_GAP, Decimal("24"))
        self.assertEqual(production.MAX_COLUMN_X0_DRIFT, Decimal("18"))

    def test_all_frozen_dual_identities_close_exactly(self) -> None:
        for target in production.TARGETS.values():
            identity = production._validate_identity(target)
            self.assertEqual(identity["tolerance"], "0.005")
            self.assertEqual([row["column"] for row in identity["columns"]], ["CURRENT", "PRIOR"])
            self.assertTrue(
                all(Decimal(row["identity_residual_cny"]) == 0 for row in identity["columns"])
            )

    def test_non_target_returns_formal_v1728_object_identity(self) -> None:
        sentinel = {"parser_version": "FORMAL_V17_28", "observations": {}}
        with patch.object(production.accepted, "parse_pdf_bytes", return_value=sentinel):
            actual = production.parse_pdf_bytes(b"not-a-target", "2024-06-30")
        self.assertIs(actual, sentinel)

    def test_wrong_date_returns_formal_v1728_object_identity(self) -> None:
        digest, target = next(iter(production.TARGETS.items()))
        sentinel = {"parser_version": "FORMAL_V17_28"}
        fake_raw = b"x" * target["source_bytes"]

        class FakeHash:
            def hexdigest(self) -> str:
                return digest

        with patch.object(production.accepted, "parse_pdf_bytes", return_value=sentinel), patch.object(
            production.hashlib, "sha256", return_value=FakeHash()
        ):
            actual = production.parse_pdf_bytes(fake_raw, "1900-01-01")
        self.assertIs(actual, sentinel)

    def test_exact_label_around_amount_pattern_is_narrow(self) -> None:
        target = next(
            row for row in production.TARGETS.values()
            if row["announcement_id"] == "1215186538"
        )
        rows = [
            {"text": "所有者权益（或股东权", "y": 100.0, "words": []},
            {"text": "1,080,008,925.97 1,088,521,670.81", "y": 107.0, "words": []},
            {"text": "益）合计", "y": 114.0, "words": []},
        ]
        pair = [
            {"value": target["values"]["TOTAL_EQUITY"][0], "raw": "x", "x0": 320.0},
            {"value": target["values"]["TOTAL_EQUITY"][1], "raw": "y", "x0": 430.0},
        ]
        event = {"page": 1, "role": "GROUP", "line": "合并资产负债表", "y": 20.0}
        with patch.object(
            production,
            "_amount_pair",
            side_effect=lambda row, expected: pair if row is rows[1] else None,
        ), patch.object(production, "_amounts", return_value=[]), patch.object(
            production, "_bind", return_value=event
        ), patch.object(production, "_validate_header", return_value={"ok": True}):
            result = production._find_split_equity({1: rows}, [event], target)
        self.assertEqual(result["pattern"], "SPLIT_LABEL_1_BEFORE_1_AFTER_AMOUNT")
        self.assertEqual(result["row_gaps"], ["7.0", "7.0"])

    def test_promotion_marker_never_authorizes_runtime(self) -> None:
        target = next(iter(production.TARGETS.values()))
        evidence = {
            "statement_event": {"page": 1, "role": "GROUP", "line": "合并资产负债表"},
            "header_context": {"ok": True},
            "column_alignment": {"ok": True},
            "identity": production._validate_identity(target),
            "rows": {
                concept: {
                    "page": index + 2,
                    "pair": [
                        {"raw": target["values"][concept][0], "value": target["values"][concept][0], "x0": 300.0},
                        {"raw": target["values"][concept][1], "value": target["values"][concept][1], "x0": 400.0},
                    ],
                    "pattern": "SPLIT_LABEL_1_BEFORE_1_AFTER_AMOUNT" if concept == "TOTAL_EQUITY" else None,
                    "row_gaps": ["7.0", "7.0"] if concept == "TOTAL_EQUITY" else [],
                }
                for index, concept in enumerate(production.ALLOWED_CONCEPTS)
            },
        }
        current = {"observations": {}, "validation_errors": ["old"]}
        out = production._promote_experiment(current, "a" * 64, target, evidence)
        block = out["balance_sheet_block"]
        self.assertIs(block["production_promotion_experiment_only"], True)
        self.assertIs(block["runtime_promotion_authorized"], False)
        self.assertIs(block["candidate_only"], False)
        self.assertEqual(block["formal_runtime_generation"], "V17.28")
        self.assertEqual(block["proposed_runtime_generation"], "V17.29")
        self.assertIs(block["ocr_enabled"], False)
        self.assertIs(block["fuzzy_alias_matching_enabled"], False)
        self.assertIs(block["equity_value_inferred_as_assets_minus_liabilities"], False)


if __name__ == "__main__":
    unittest.main()
