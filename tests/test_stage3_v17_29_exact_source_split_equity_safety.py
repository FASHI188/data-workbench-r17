from __future__ import annotations

import copy
import unittest

import diagnose_stage3_s3g1j_v17_29_exact_source_split_equity_safety as safety


def root_row(aid: str = "A", sha: str = "a" * 64) -> dict[str, str]:
    return {
        "announcement_id": aid,
        "source_code": "600000",
        "report_family": "ANNUAL",
        "economic_date": "2025-12-31",
        "canonical_source_url": "https://example.test/a.pdf",
        "source_sha256": sha,
        "source_bytes": "100",
        "page_count": "10",
        "source_identity_locked": "True",
        "group_asset_current": "100.00",
        "group_asset_prior": "90.00",
        "group_liability_current": "60.00",
        "group_liability_prior": "50.00",
        "group_equity_current": "40.00",
        "group_equity_prior": "40.00",
        "current_identity_residual": "0.00",
        "prior_identity_residual": "0.00",
    }


class V1729ExactSourceSafetyTests(unittest.TestCase):
    def test_exact_identity_routes_only_diagnostic(self) -> None:
        target = {"source_bytes": 100, "economic_date": "2025-12-31"}
        targets = {"a" * 64: target}
        self.assertEqual(
            safety.route_source("a" * 64, 100, "2025-12-31", targets),
            "V17_29_PRE_CANDIDATE_EXACT_SOURCE_DIAGNOSTIC",
        )

    def test_wrong_sha_bytes_or_date_delegate(self) -> None:
        target = {"source_bytes": 100, "economic_date": "2025-12-31"}
        targets = {"a" * 64: target}
        self.assertEqual(
            safety.route_source("b" * 64, 100, "2025-12-31", targets),
            "DELEGATE_FORMAL_V17_28_UNCHANGED",
        )
        self.assertEqual(
            safety.route_source("a" * 64, 101, "2025-12-31", targets),
            "DELEGATE_FORMAL_V17_28_UNCHANGED",
        )
        self.assertEqual(
            safety.route_source("a" * 64, 100, "2025-12-30", targets),
            "DELEGATE_FORMAL_V17_28_UNCHANGED",
        )

    def test_non_target_returns_same_formal_object(self) -> None:
        formal = {"parser_version": "V17.28", "nested": {"x": 1}}
        targets = {"a" * 64: {"source_bytes": 100, "economic_date": "2025-12-31"}}
        result = safety.dispatch_contract(formal, "b" * 64, 100, "2025-12-31", targets)
        self.assertIs(result, formal)

    def test_target_dispatch_is_diagnostic_not_parser_output(self) -> None:
        formal = {"parser_version": "V17.28"}
        targets = {"a" * 64: {"source_bytes": 100, "economic_date": "2025-12-31"}}
        result = safety.dispatch_contract(formal, "a" * 64, 100, "2025-12-31", targets)
        self.assertEqual(result["route"], "V17_29_PRE_CANDIDATE_EXACT_SOURCE_DIAGNOSTIC")
        self.assertIs(result["candidate_parser_implementation_authorized"], False)
        self.assertIs(result["formal_result"], formal)

    def test_target_map_rejects_nonzero_identity(self) -> None:
        row = root_row()
        row["current_identity_residual"] = "1.00"
        rows = {aid: copy.deepcopy(row) for aid in safety.SAFE_IDS}
        for index, aid in enumerate(safety.SAFE_IDS):
            rows[aid]["announcement_id"] = aid
            rows[aid]["source_sha256"] = f"{index + 1:064x}"
        with self.assertRaisesRegex(ValueError, "identity residual changed"):
            safety.target_map(rows)

    def test_target_map_rejects_source_unlock(self) -> None:
        rows = {
            aid: root_row(aid, f"{index + 1:064x}")
            for index, aid in enumerate(safety.SAFE_IDS)
        }
        rows[safety.SAFE_IDS[0]]["source_identity_locked"] = "False"
        with self.assertRaisesRegex(ValueError, "source identity not locked"):
            safety.target_map(rows)

    def test_candidate_evidence_must_be_list(self) -> None:
        with self.assertRaisesRegex(ValueError, "candidate evidence is not list"):
            safety.candidate_identities(
                {"announcement_id": "A", "candidate_evidence_json": "{}"}
            )


if __name__ == "__main__":
    unittest.main()
