from __future__ import annotations

import unittest
from unittest import mock

import diagnose_stage3_s3g1j_v17_28_split_equity_v2 as diagnostic


class V1728SplitEquityDiagnosticV2Tests(unittest.TestCase):
    def test_duplicate_exact_date_objects_bind_to_nearest_witness(self) -> None:
        rows = [
            {"y": 110.0, "text": "2020 年 3 月 31 日", "words": []},
            {"y": 120.0, "text": "2020年3月31日 2019年12月31日", "words": []},
            {"y": 130.0, "text": "单位：元 币种：人民币", "words": []},
        ]
        with mock.patch.object(
            diagnostic.base.rows_v14, "_rows_from_words", return_value=rows
        ):
            result = diagnostic.validate_header_context(
                [object()], {"page": 1, "y": 100.0}, "2020年3月31日"
            )
        self.assertEqual(result["date_text_object_count"], 2)
        self.assertEqual(result["date_row"], "2020 年 3 月 31 日")
        self.assertEqual(result["date_distance_from_group_title"], "10.0")
        self.assertTrue(result["duplicate_exact_date_objects_allowed"])

    def test_missing_expected_date_is_rejected(self) -> None:
        rows = [
            {"y": 110.0, "text": "2019年12月31日", "words": []},
            {"y": 130.0, "text": "单位：元 币种：人民币", "words": []},
        ]
        with mock.patch.object(
            diagnostic.base.rows_v14, "_rows_from_words", return_value=rows
        ):
            with self.assertRaisesRegex(ValueError, "expected-date evidence is missing"):
                diagnostic.validate_header_context(
                    [object()], {"page": 1, "y": 100.0}, "2020年3月31日"
                )

    def test_nearest_expected_date_must_be_role_local(self) -> None:
        rows = [
            {"y": 145.0, "text": "2020年3月31日", "words": []},
            {"y": 150.0, "text": "单位：元 币种：人民币", "words": []},
        ]
        with mock.patch.object(
            diagnostic.base.rows_v14, "_rows_from_words", return_value=rows
        ):
            with self.assertRaisesRegex(ValueError, "expected-date distance"):
                diagnostic.validate_header_context(
                    [object()], {"page": 1, "y": 100.0}, "2020年3月31日"
                )

    def test_cny_unit_witness_is_required(self) -> None:
        rows = [{"y": 110.0, "text": "2020年3月31日", "words": []}]
        with mock.patch.object(
            diagnostic.base.rows_v14, "_rows_from_words", return_value=rows
        ):
            with self.assertRaisesRegex(ValueError, "CNY unit evidence is missing"):
                diagnostic.validate_header_context(
                    [object()], {"page": 1, "y": 100.0}, "2020年3月31日"
                )


if __name__ == "__main__":
    unittest.main()
