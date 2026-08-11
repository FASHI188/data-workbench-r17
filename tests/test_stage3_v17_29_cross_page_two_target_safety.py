from __future__ import annotations

import unittest

import audit_stage3_s3g1j_cross_page_two_target_safety as s


class V1729CrossPageTwoTargetSafetyTests(unittest.TestCase):
    def test_exact_two_target_boundary(self) -> None:
        self.assertEqual(sorted(s.TARGETS), ["1223347318", "1223407043"])
        for aid, target in s.TARGETS.items():
            self.assertTrue(s.is_exact_target(aid, target["economic_date"], target["source_sha256"], target["source_bytes"]))

    def test_mutated_identity_always_delegates(self) -> None:
        for aid, target in s.TARGETS.items():
            self.assertFalse(s.is_exact_target(aid, "1900-01-01", target["source_sha256"], target["source_bytes"]))
            self.assertFalse(s.is_exact_target(aid, target["economic_date"], "0" * 64, target["source_bytes"]))
            self.assertFalse(s.is_exact_target(aid, target["economic_date"], target["source_sha256"], target["source_bytes"] + 1))
            self.assertFalse(s.is_exact_target("9999999999", target["economic_date"], target["source_sha256"], target["source_bytes"]))

    def test_cross_page_fragments_complete_only_exact_alias(self) -> None:
        for target in s.TARGETS.values():
            self.assertEqual(
                s._norm(target["equity_label_prefix"]) + s._norm(target["next_page_suffix"]),
                s._norm(s.FULL_EQUITY_ALIAS),
            )
            self.assertNotEqual(s._norm(target["equity_label_prefix"]), s._norm(s.FULL_EQUITY_ALIAS))

    def test_no_relaxation_flags_are_structurally_required(self) -> None:
        self.assertEqual(s.IDENTITY_TOLERANCE, s.Decimal("0.005"))
        self.assertEqual(s.FULL_EQUITY_ALIAS, "所有者权益（或股东权益）合计")
        for target in s.TARGETS.values():
            self.assertTrue(target["source_url"].startswith("https://static.cninfo.com.cn/finalpage/"))
            self.assertEqual(len(target["source_sha256"]), 64)
            self.assertGreater(target["source_bytes"], 0)
            self.assertEqual(len(target["values"]["TOTAL_ASSETS"]), 2)
            self.assertEqual(len(target["values"]["TOTAL_LIABILITIES"]), 2)
            self.assertEqual(len(target["values"]["TOTAL_EQUITY"]), 2)

    def test_configured_dual_column_identities_are_exact(self) -> None:
        for target in s.TARGETS.values():
            for idx in (0, 1):
                a=s.Decimal(target["values"]["TOTAL_ASSETS"][idx])
                l=s.Decimal(target["values"]["TOTAL_LIABILITIES"][idx])
                e=s.Decimal(target["values"]["TOTAL_EQUITY"][idx])
                self.assertEqual(a-l-e, s.Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
