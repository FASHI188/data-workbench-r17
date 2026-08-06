from __future__ import annotations

import unittest
from decimal import Decimal

from scripts import classify_stage3_s3g1j_v17_28_p0_pdf_root_cause as root_cause


def title(role: str, page: int, context=None):
    return {
        "statement_role_v14": role,
        "page": page,
        "context": context or [],
    }


def candidate(concept: str, value1: str, value2: str):
    alias = "资产总计" if concept == "TOTAL_ASSETS" else "负债合计"
    return {
        "alias": alias,
        "statement_role": "GROUP",
        "period_evidence": {"matched": True},
        "unit_evidence": {"source": "EXPLICIT_UNIT_LABEL"},
        "row_text": f"{alias} {value1} {value2}",
    }


class P0PdfRootCauseTests(unittest.TestCase):
    def test_explicit_split_equity_is_accepted(self):
        base = {"layout": {"title_rows": [
            title("GROUP", 10),
            title("PARENT", 12, [
                {"relative_index": -6, "text": "300.00 250.00"},
                {"relative_index": -5, "text": "益）合计"},
                {"relative_index": -4, "text": "负债和所有者权益（或股东权益）总计"},
                {"relative_index": -3, "text": "1,000.00 900.00"},
            ]),
        ]}}
        proof = root_cause.explicit_split_equity_proof(base)
        self.assertEqual(proof["values"], [Decimal("300.00"), Decimal("250.00")])

    def test_arithmetic_only_equity_is_rejected(self):
        base = {"layout": {"title_rows": [title("GROUP", 10), title("PARENT", 12, [])]}}
        self.assertIsNone(root_cause.explicit_split_equity_proof(base))

    def test_total_candidate_requires_group_period_and_unit(self):
        raw = {"candidates": {"TOTAL_ASSETS": [candidate("TOTAL_ASSETS", "1,000.00", "900.00")]}}
        self.assertIsNotNone(root_cause.group_total_candidate(raw, "TOTAL_ASSETS"))
        raw["candidates"]["TOTAL_ASSETS"][0]["period_evidence"]["matched"] = False
        self.assertIsNone(root_cause.group_total_candidate(raw, "TOTAL_ASSETS"))

    def test_safe_requires_explicit_equity_not_a_minus_l(self):
        p0 = {"canonical_source_url": "u"}
        base = {
            "source_sha256": "s", "source_bytes": 1, "canonical_source_url": "u",
            "source_code": "x", "report_family": "Q", "economic_date": "2020-01-01",
            "canonical_title": "t", "layout": {"page_count": 12, "title_rows": [title("GROUP", 10), title("PARENT", 12, [])]},
        }
        raw = {
            "candidate_failure_stage": "NO_GENERIC_GROUP_WITNESS",
            "candidate_diagnostic": {"base_funnel": {"formal_group_events": 1, "formal_parent_events": 1}},
            "candidates": {
                "TOTAL_ASSETS": [candidate("TOTAL_ASSETS", "1,000.00", "900.00")],
                "TOTAL_LIABILITIES": [candidate("TOTAL_LIABILITIES", "700.00", "650.00")],
                "TOTAL_EQUITY": [],
            },
        }
        result = root_cause.classify_target("x", p0, base, raw)
        self.assertEqual(result["classification"], "DIAGNOSTIC_ONLY")
        self.assertEqual(result["group_equity_current"], "")

    def test_period_gate_has_specific_root_cause(self):
        p0 = {"canonical_source_url": "u"}
        base = {"source_sha256": "s", "source_bytes": 1, "canonical_source_url": "u", "source_code": "x", "layout": {"page_count": 1, "title_rows": []}}
        raw = {"candidate_failure_stage": "PERIOD_OR_ROLE_GATE_REMOVED_ALE_CANDIDATES", "candidate_diagnostic": {"base_funnel": {}}, "candidates": {}}
        result = root_cause.classify_target("x", p0, base, raw)
        self.assertEqual(result["root_cause"], "GENERIC_GROUP_WITNESS_PRESENT_BUT_ROLE_LOCAL_PERIOD_MISSING")

    def test_bank_specific_target_is_never_promoted(self):
        p0 = {"canonical_source_url": "u"}
        base = {"source_sha256": "s", "source_bytes": 1, "canonical_source_url": "u", "source_code": "601860", "layout": {"page_count": 1, "title_rows": []}}
        raw = {"candidate_diagnostic": {"base_funnel": {}}, "candidates": {}}
        result = root_cause.classify_target("1219834247", p0, base, raw)
        self.assertEqual(result["classification"], "DO_NOT_PROMOTE")

    def test_source_url_drift_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "source identity drift"):
            root_cause.classify_target("x", {"canonical_source_url": "u1"}, {"canonical_source_url": "u2", "source_sha256": "s", "source_bytes": 1}, {})


if __name__ == "__main__":
    unittest.main()
