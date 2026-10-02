from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

import extract_stage3_financial_pdf_values_v18 as extractor
import stage3_financial_pdf_parser_v20 as parser


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "governance/stage3_s3g1j_v17_28_candidate_safety.json"


class _Digest:
    def __init__(self, value: str) -> None:
        self.value = value

    def hexdigest(self) -> str:
        return self.value


def accepted_candidate(digest: str, target: dict) -> dict:
    observations = {
        concept: {
            "concept": concept,
            "status": "FOUND",
            "normalized_cny_value": target["values"][concept][0],
            "extraction_scope": candidate_scope,
        }
        for concept in parser.ALLOWED_CONCEPTS
    }
    observations["NET_PROFIT"] = {
        "status": "NOT_FOUND",
        "reason": "V17_28_CANDIDATE_UNVALIDATED_NON_BALANCE_CONCEPT",
    }
    return {
        "parser_version": parser.candidate.METHOD,
        "tier1_found": 0,
        "tier2_found": 3,
        "validation_errors": [],
        "observations": observations,
        "balance_sheet_block": {
            "candidate_only": True,
            "exact_source_sha256": digest,
            "column_role_gate_pass": True,
            "split_equity_pattern": target["split_pattern"],
            "explicit_equity_pdf_text": True,
            "equity_value_inferred_as_assets_minus_liabilities": False,
            "non_balance_values_promoted": False,
            "ocr_enabled": False,
            "fuzzy_alias_matching_enabled": False,
            "dual_column_identity": {
                "tolerance": "0.005",
                "columns": [
                    {
                        "column": "CURRENT",
                        "identity_residual_cny": "0.00",
                        "identity_relative_error": "0",
                    },
                    {
                        "column": "PRIOR",
                        "identity_residual_cny": "0.00",
                        "identity_relative_error": "0",
                    },
                ],
            },
        },
    }


candidate_scope = "V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_CANDIDATE"


class V1728RuntimeWrapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_candidate_evidence_identity_is_frozen(self) -> None:
        accepted = self.evidence["accepted_run"]
        self.assertEqual(accepted["run_id"], parser.CANDIDATE_RUN)
        self.assertEqual(accepted["head_sha"], parser.CANDIDATE_HEAD)
        self.assertEqual(accepted["artifact_id"], parser.CANDIDATE_ARTIFACT_ID)
        self.assertEqual(accepted["artifact_name"], parser.CANDIDATE_ARTIFACT)
        self.assertEqual(accepted["artifact_digest"], parser.CANDIDATE_ARTIFACT_DIGEST)
        self.assertEqual(
            set(self.evidence["candidate_identity"]["target_source_sha256"]),
            set(parser.TARGETS),
        )
        self.assertIs(
            self.evidence["candidate_identity"]["candidate_promotion_authorized"],
            False,
        )

    def test_extractor_identity_is_v17_28_and_does_not_activate_itself(self) -> None:
        self.assertEqual(extractor.RUNTIME_GENERATION, "V17.28")
        self.assertEqual(
            extractor.SHARD_GATE,
            "S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_28",
        )
        self.assertEqual(extractor.METHODOLOGY_VERSION, parser.METHODOLOGY_VERSION)
        self.assertEqual(
            extractor.METHOD,
            "CNINFO_ORIGINAL_PDF_PYMUPDF_V18_V17_28_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION",
        )
        self.assertTrue(callable(extractor.parse_pdf_bytes))

    def test_non_target_output_is_exact_v17_27_delegation(self) -> None:
        inherited = {
            "parser_version": "V17_27_EXACT_SOURCE_NORMAL_EQUITY_IDENTITY_PRODUCTION",
            "observations": {"TOTAL_ASSETS": {"status": "NOT_FOUND"}},
            "validation_errors": ["retained-fail-closed"],
        }
        expected = copy.deepcopy(inherited)
        with mock.patch.object(
            parser.candidate,
            "parse_pdf_bytes",
            return_value=copy.deepcopy(inherited),
        ):
            actual = parser.parse_pdf_bytes(b"non-target", "2020-03-31")
        self.assertEqual(actual, expected)

    def test_wrong_date_target_is_not_promoted(self) -> None:
        digest, target = next(iter(parser.TARGETS.items()))
        inherited = {"parser_version": parser.candidate.METHOD, "validation_errors": []}
        with mock.patch.object(parser.hashlib, "sha256", return_value=_Digest(digest)), mock.patch.object(
            parser.candidate,
            "parse_pdf_bytes",
            return_value=copy.deepcopy(inherited),
        ):
            actual = parser.parse_pdf_bytes(b"target", "1999-12-31")
        self.assertEqual(actual, inherited)
        self.assertNotEqual("1999-12-31", target["economic_date"])

    def test_exact_target_promotes_only_a_l_e(self) -> None:
        digest, target = next(iter(parser.TARGETS.items()))
        accepted = accepted_candidate(digest, target)
        with mock.patch.object(parser.hashlib, "sha256", return_value=_Digest(digest)), mock.patch.object(
            parser.candidate,
            "parse_pdf_bytes",
            return_value=copy.deepcopy(accepted),
        ):
            actual = parser.parse_pdf_bytes(b"target", target["economic_date"])
        self.assertEqual(actual["parser_version"], parser.METHOD)
        found = {
            concept
            for concept, row in actual["observations"].items()
            if row.get("status") == "FOUND"
        }
        self.assertEqual(found, set(parser.ALLOWED_CONCEPTS))
        for concept in parser.ALLOWED_CONCEPTS:
            self.assertEqual(
                actual["observations"][concept]["normalized_cny_value"],
                target["values"][concept][0],
            )
            self.assertEqual(
                actual["observations"][concept]["extraction_scope"],
                parser.PRODUCTION_SCOPE,
            )
        block = actual["balance_sheet_block"]
        self.assertIs(block["candidate_only"], False)
        self.assertIs(block["candidate_safety_promoted"], True)
        self.assertEqual(block["formal_runtime_generation"], "V17.28")
        self.assertEqual(block["production_runtime_generation"], "V17.28")
        self.assertEqual(block["candidate_acceptance_run"], parser.CANDIDATE_RUN)
        self.assertEqual(
            block["candidate_acceptance_artifact_digest"],
            parser.CANDIDATE_ARTIFACT_DIGEST,
        )
        self.assertEqual(block["production_evidence_manifest"], parser.EVIDENCE_MANIFEST)

    def test_candidate_boundary_mutations_fail_closed(self) -> None:
        digest, target = next(iter(parser.TARGETS.items()))
        mutations = [
            ("candidate_only", False),
            ("explicit_equity_pdf_text", False),
            ("equity_value_inferred_as_assets_minus_liabilities", True),
            ("non_balance_values_promoted", True),
            ("ocr_enabled", True),
            ("fuzzy_alias_matching_enabled", True),
        ]
        for key, value in mutations:
            accepted = accepted_candidate(digest, target)
            accepted["balance_sheet_block"][key] = value
            with self.subTest(key=key), mock.patch.object(
                parser.hashlib, "sha256", return_value=_Digest(digest)
            ), mock.patch.object(
                parser.candidate,
                "parse_pdf_bytes",
                return_value=accepted,
            ):
                with self.assertRaises(ValueError):
                    parser.parse_pdf_bytes(b"target", target["economic_date"])

    def test_dual_column_identity_must_remain_exact(self) -> None:
        digest, target = next(iter(parser.TARGETS.items()))
        accepted = accepted_candidate(digest, target)
        accepted["balance_sheet_block"]["dual_column_identity"]["columns"][1][
            "identity_residual_cny"
        ] = "0.01"
        with mock.patch.object(parser.hashlib, "sha256", return_value=_Digest(digest)), mock.patch.object(
            parser.candidate,
            "parse_pdf_bytes",
            return_value=accepted,
        ):
            with self.assertRaises(ValueError):
                parser.parse_pdf_bytes(b"target", target["economic_date"])


if __name__ == "__main__":
    unittest.main()
