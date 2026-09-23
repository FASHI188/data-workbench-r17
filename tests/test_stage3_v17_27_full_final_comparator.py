from __future__ import annotations

import copy
import unittest
from collections import Counter

import compare_stage3_s3g1j_v17_27_full_final as comparator


class V1727FullFinalComparatorTests(unittest.TestCase):
    def _document(self, aid: str = "non-target") -> dict[str, str]:
        row = {field: "" for field in comparator.DOC_FIELDS}
        row.update(
            {
                "announcement_id": aid,
                "source_code": "000001",
                "economic_date": "2020-03-31",
                "candidate_evidence_json": '[{"id":"x","nested":[1,2]}]',
                "document_status": "PASS",
                "numeric_observations": "1",
            }
        )
        return row

    def _numeric(self, aid: str = "old", concept: str = "REVENUE") -> dict[str, str]:
        row = {field: "" for field in comparator.STABLE_NUMERIC_FIELDS}
        row.update(
            {
                "announcement_id": aid,
                "source_code": "000001",
                "economic_date": "2020-03-31",
                "concept": concept,
                "raw_value": "100",
                "normalized_cny_value": "100",
                "unit": "元",
                "unit_multiplier": "1",
                "source_url": "https://static.cninfo.com.cn/x.PDF",
                "source_sha256": "a" * 64,
                "source_format": "PDF",
                "page": "1",
                "matched_alias": "营业收入",
                "confidence": "HIGH",
                "extraction_method": "ignored-generation-a",
                "methodology_version": "ignored-generation-a",
            }
        )
        return row

    def test_exact_target_population_is_frozen(self) -> None:
        self.assertEqual(
            set(comparator.TARGETS),
            {
                "1200907104",
                "1201708762",
                "1202195310",
                "1202774611",
                "1203358200",
            },
        )
        self.assertEqual(
            set(comparator.EXPECTED_PAGES),
            {"TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY"},
        )
        self.assertEqual(
            comparator.EXCLUDED_GENERATION_FIELDS,
            ("extraction_method", "methodology_version"),
        )

    def test_non_target_document_field_drift_is_detected(self) -> None:
        previous = self._document()
        current = copy.deepcopy(previous)
        self.assertEqual(
            comparator._canonical_doc(previous), comparator._canonical_doc(current)
        )
        current["selected_source_sha256"] = "b" * 64
        self.assertNotEqual(
            comparator._canonical_doc(previous), comparator._canonical_doc(current)
        )

    def test_json_key_order_is_ignored_but_nested_array_order_is_not(self) -> None:
        first = self._document()
        second = copy.deepcopy(first)
        second["candidate_evidence_json"] = '[{"nested":[1,2],"id":"x"}]'
        self.assertEqual(
            comparator._canonical_doc(first), comparator._canonical_doc(second)
        )
        second["candidate_evidence_json"] = '[{"nested":[2,1],"id":"x"}]'
        self.assertNotEqual(
            comparator._canonical_doc(first), comparator._canonical_doc(second)
        )

    def test_numeric_generation_metadata_is_excluded_but_values_are_not(self) -> None:
        previous = self._numeric()
        current = copy.deepcopy(previous)
        current["extraction_method"] = "new-generation"
        current["methodology_version"] = "new-generation"
        self.assertEqual(
            comparator._numeric_tuple(previous), comparator._numeric_tuple(current)
        )
        current["normalized_cny_value"] = "101"
        self.assertNotEqual(
            comparator._numeric_tuple(previous), comparator._numeric_tuple(current)
        )

    def test_numeric_multiset_is_order_independent_and_duplicate_sensitive(self) -> None:
        first = self._numeric("a")
        second = self._numeric("b")
        a = Counter([comparator._numeric_tuple(first), comparator._numeric_tuple(second)])
        b = Counter([comparator._numeric_tuple(second), comparator._numeric_tuple(first)])
        self.assertEqual(a, b)
        self.assertEqual(
            comparator.semantic_multiset_sha(a), comparator.semantic_multiset_sha(b)
        )
        b.update([comparator._numeric_tuple(first)])
        self.assertNotEqual(a, b)
        self.assertNotEqual(
            comparator.semantic_multiset_sha(a), comparator.semantic_multiset_sha(b)
        )

    def _valid_target_rows(self, aid: str) -> list[dict[str, str]]:
        target = comparator.TARGETS[aid]
        rows: list[dict[str, str]] = []
        for concept, value in target["values"].items():
            row = self._numeric(aid, concept)
            row.update(
                {
                    "economic_date": target["economic_date"],
                    "normalized_cny_value": value,
                    "source_sha256": target["source_sha256"],
                    "source_format": "PDF",
                    "extraction_method": comparator.EXPECTED_PARSER_METHOD,
                    "methodology_version": comparator.EXPECTED_METHODOLOGY,
                    "page": comparator.EXPECTED_PAGES[concept],
                    "matched_alias": comparator.EXPECTED_ALIASES[concept],
                    "confidence": "HIGH",
                }
            )
            rows.append(row)
        return rows

    def test_target_numeric_scope_accepts_only_exact_three_balance_totals(self) -> None:
        aid = "1200907104"
        errors: list[str] = []
        summary = comparator._target_numeric_summary(
            aid, self._valid_target_rows(aid), comparator.TARGETS[aid], errors
        )
        self.assertEqual(errors, [])
        self.assertEqual(summary["numeric_row_count"], 3)
        self.assertEqual(
            summary["concepts"],
            ["TOTAL_ASSETS", "TOTAL_EQUITY", "TOTAL_LIABILITIES"],
        )

    def test_extra_non_balance_target_concept_fails_closed(self) -> None:
        aid = "1200907104"
        rows = self._valid_target_rows(aid)
        rows.append(self._numeric(aid, "NET_PROFIT"))
        errors: list[str] = []
        comparator._target_numeric_summary(
            aid, rows, comparator.TARGETS[aid], errors
        )
        self.assertTrue(any("expected 3 numeric rows" in error for error in errors))
        self.assertTrue(any("concept scope" in error for error in errors))

    def test_wrong_target_value_fails_closed(self) -> None:
        aid = "1200907104"
        rows = self._valid_target_rows(aid)
        rows[0]["normalized_cny_value"] = "1"
        errors: list[str] = []
        comparator._target_numeric_summary(
            aid, rows, comparator.TARGETS[aid], errors
        )
        self.assertTrue(any("normalized_cny_value" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
