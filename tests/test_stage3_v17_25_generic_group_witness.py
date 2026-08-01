from __future__ import annotations

import unittest

import fitz

import stage3_financial_statement_blocks_v17_25 as candidate


class V1725GenericGroupWitnessTests(unittest.TestCase):
    def make_pdf(
        self,
        title: str = "资产负债表",
        witness: str | None = "归属于母公司所有者权益合计 1,000,000 900,000",
        total: str | None = "所有者权益合计 1,000,000 900,000",
    ) -> fitz.Document:
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), title, fontsize=12)
        if witness is not None:
            page.insert_text((72, 120), witness, fontsize=10)
        if total is not None:
            page.insert_text((72, 150), total, fontsize=10)
        return doc

    def test_exact_group_witness_promotes_generic_title(self):
        doc = self.make_pdf()
        try:
            diagnostic = candidate.diagnose_generic_group_witness(doc)
        finally:
            doc.close()
        self.assertEqual(diagnostic["accepted_unknown_statement_count"], 1)
        self.assertEqual(diagnostic["promoted_generic_group_count"], 1)
        event = diagnostic["promoted_events"][0]
        self.assertEqual(event["role"], "GROUP")
        self.assertEqual(
            event["witness"]["witness_alias"],
            "归属于母公司所有者权益合计",
        )
        self.assertTrue(event["witness"]["amounts_equal"])

    def test_missing_group_only_witness_stays_unknown(self):
        doc = self.make_pdf(witness=None)
        try:
            diagnostic = candidate.diagnose_generic_group_witness(doc)
        finally:
            doc.close()
        self.assertEqual(diagnostic["accepted_unknown_statement_count"], 1)
        self.assertEqual(diagnostic["promoted_generic_group_count"], 0)

    def test_mismatched_witness_and_total_values_stay_unknown(self):
        doc = self.make_pdf(total="所有者权益合计 800,000 700,000")
        try:
            diagnostic = candidate.diagnose_generic_group_witness(doc)
        finally:
            doc.close()
        self.assertEqual(diagnostic["promoted_generic_group_count"], 0)

    def test_parent_title_is_never_promoted(self):
        doc = self.make_pdf(title="母公司资产负债表")
        try:
            diagnostic = candidate.diagnose_generic_group_witness(doc)
        finally:
            doc.close()
        self.assertEqual(diagnostic["accepted_unknown_statement_count"], 0)
        self.assertEqual(diagnostic["promoted_generic_group_count"], 0)

    def test_narrative_analysis_title_is_never_promoted(self):
        doc = self.make_pdf(title="九、资产负债表分析")
        try:
            diagnostic = candidate.diagnose_generic_group_witness(doc)
        finally:
            doc.close()
        self.assertEqual(diagnostic["promoted_generic_group_count"], 0)


if __name__ == "__main__":
    unittest.main()
