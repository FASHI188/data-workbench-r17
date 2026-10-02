from __future__ import annotations

import unittest

import diagnose_stage3_s3g1j_p0_v17_24 as diagnostic


class P0V1724DiagnosticTests(unittest.TestCase):
    def test_recovered_signature_has_priority(self):
        self.assertEqual(
            diagnostic.diagnostic_signature(True, {}),
            "CURRENT_V17_24_RECOVERED",
        )

    def test_column_gate_failure_is_distinct(self):
        result = diagnostic.diagnostic_signature(
            False,
            {
                "identity_recovered_before_column_gate": True,
                "column_role_gate": {"pass": False, "reason": "ambiguous"},
                "candidate_counts": {
                    "TOTAL_ASSETS": 1,
                    "TOTAL_LIABILITIES": 1,
                    "TOTAL_EQUITY": 1,
                },
            },
        )
        self.assertEqual(result, "IDENTITY_FOUND_BUT_COLUMN_ROLE_GATE_FAILED")

    def test_missing_concepts_are_explicit(self):
        result = diagnostic.diagnostic_signature(
            False,
            {
                "candidate_counts": {
                    "TOTAL_ASSETS": 1,
                    "TOTAL_LIABILITIES": 0,
                    "TOTAL_EQUITY": 0,
                },
                "column_role_gate": {"pass": False},
            },
        )
        self.assertEqual(
            result,
            "MISSING_CANDIDATES_TOTAL_LIABILITIES_TOTAL_EQUITY",
        )

    def test_source_evidence_requires_exact_single_canonical_pdf(self):
        document = {
            "announcement_id": "123",
            "canonical_source_url": "https://static.cninfo.com.cn/finalpage/2020/123.PDF",
            "candidate_evidence_json": (
                '[{"id":"123","url":"https://static.cninfo.com.cn/finalpage/2020/123.PDF",'
                '"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
                '"bytes":42}]'
            ),
        }
        result = diagnostic.source_evidence(document)
        self.assertEqual(result["sha256"], "a" * 64)
        self.assertEqual(result["bytes"], 42)

    def test_source_evidence_rejects_multiple_candidates(self):
        document = {
            "announcement_id": "123",
            "canonical_source_url": "https://static.cninfo.com.cn/finalpage/2020/123.PDF",
            "candidate_evidence_json": "[{},{}]",
        }
        with self.assertRaisesRegex(ValueError, "expected one canonical candidate"):
            diagnostic.source_evidence(document)


if __name__ == "__main__":
    unittest.main()
