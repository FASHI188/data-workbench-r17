from __future__ import annotations

import gzip
import io
import unittest

import build_stage3_s3g1j_v17_29_cross_page_production_promotion_safety as p


class CrossPageProductionPromotionSafetyTests(unittest.TestCase):
    def test_exact_two_target_scope(self) -> None:
        self.assertEqual(p.TARGET_IDS, ("1223347318", "1223407043"))
        self.assertEqual(p.TARGET_NUMERIC_ROWS, 6)
        for aid, target in p.TARGETS.items():
            self.assertEqual(len(target["source_sha256"]), 64)
            self.assertGreater(target["source_bytes"], 0)
            self.assertTrue(target["source_url"].startswith("https://static.cninfo.com.cn/finalpage/"))
            self.assertEqual(p._norm(target["equity_prefix"]) + p._norm(target["equity_suffix"]), p._norm(p.FULL_EQUITY_ALIAS))

    def test_dual_column_target_values_are_exact_identities(self) -> None:
        for target in p.TARGETS.values():
            for i in (0, 1):
                a=p.Decimal(target["values"]["TOTAL_ASSETS"][i])
                l=p.Decimal(target["values"]["TOTAL_LIABILITIES"][i])
                e=p.Decimal(target["values"]["TOTAL_EQUITY"][i])
                self.assertEqual(a-l-e, p.Decimal("0.00"))

    def test_method_is_safety_only_not_formal_v17_29_method(self) -> None:
        self.assertIn("PROMOTION_SAFETY", p.EXTRACTION_METHOD)
        self.assertNotEqual(p.EXTRACTION_METHOD, "CNINFO_ORIGINAL_PDF_PYMUPDF_V19_V17_29_EXACT_SOURCE_SPLIT_GROUP_EQUITY_PRODUCTION")
        self.assertIn("PROMOTION-SAFETY", p.METHODOLOGY_VERSION)

    def test_fixed_stored_gzip_is_reproducible_and_readable(self) -> None:
        raw=b"a,b\n1,2\n" * 10000
        one=p.deterministic_gzip(raw)
        two=p.deterministic_gzip(raw)
        self.assertEqual(one, two)
        self.assertEqual(gzip.GzipFile(fileobj=io.BytesIO(one)).read(), raw)

    def test_no_global_policy_relaxation_constants(self) -> None:
        self.assertEqual(p.SOURCE_DOCUMENT_ROWS, 121354)
        self.assertEqual(p.SOURCE_NUMERIC_ROWS, 1051820)
        self.assertEqual(p.SOURCE_ERRORS, 1364)
        self.assertEqual(p.SOURCE_SOURCE_INCOMPLETE, 1267)
        self.assertEqual(p.SOURCE_VALUE_CONFLICT, 14)
        self.assertEqual(p.SOURCE_UNRESOLVED_TIES, 1281)


if __name__ == "__main__":
    unittest.main()
