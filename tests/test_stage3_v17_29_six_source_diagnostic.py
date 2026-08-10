from __future__ import annotations

import unittest

import diagnose_stage3_s3g1j_v17_29_six_sources as d


class V1729SixSourceDiagnosticTests(unittest.TestCase):
    def test_target_boundary_is_exact_and_bank_is_excluded(self) -> None:
        targets = d.load_targets(d.EVIDENCE_PATH)
        self.assertEqual(set(targets), {
            "1202799494", "1204077386", "1205543437",
            "1209806910", "1223347318", "1223407043",
        })
        self.assertNotIn(d.BANK_EXCLUDED_ID, targets)
        self.assertEqual(d.BANK_EXCLUDED_ID, "1219834247")

    def test_prior_root_cause_families_are_two_each(self) -> None:
        targets = d.load_targets(d.EVIDENCE_PATH)
        counts: dict[str, int] = {}
        for target in targets.values():
            counts[target["root_cause"]] = counts.get(target["root_cause"], 0) + 1
        self.assertEqual(counts, {
            "NO_FORMAL_GROUP_STATEMENT_ROLE_BINDING": 2,
            "GENERIC_GROUP_WITNESS_PRESENT_BUT_ROLE_LOCAL_PERIOD_MISSING": 2,
            "FORMAL_GROUP_A_L_PRESENT_BUT_EXPLICIT_GROUP_EQUITY_PAIR_NOT_PROVEN": 2,
        })

    def test_expected_date_forms_cover_chinese_and_iso(self) -> None:
        forms = d.expected_date_forms("2025-03-31")
        self.assertIn("2025年3月31日", forms)
        self.assertIn("2025年03月31日", forms)
        self.assertIn("2025-03-31", forms)
        self.assertIn("2025/03/31", forms)

    def test_compact_normalizes_whitespace_and_chinese_comma(self) -> None:
        self.assertEqual(d.compact(" 合并 资产负债表 ， 单位：元 "), "合并资产负债表,单位：元")

    def test_alias_sets_do_not_enable_fuzzy_matching(self) -> None:
        self.assertIn("资产总计", d.ALIASES["TOTAL_ASSETS"])
        self.assertIn("负债合计", d.ALIASES["TOTAL_LIABILITIES"])
        self.assertIn("所有者权益合计", d.ALIASES["TOTAL_EQUITY"])
        self.assertNotIn("权益", d.ALIASES["TOTAL_EQUITY"])

    def test_title_and_role_detection_is_explicit(self) -> None:
        rows = [
            {"text": "合并资产负债表", "compact": "合并资产负债表", "bbox": [0, 1, 2, 3], "y0": 1, "y1": 3},
            {"text": "资产负债表", "compact": "资产负债表", "bbox": [0, 4, 2, 6], "y0": 4, "y1": 6},
        ]
        hits = d.title_hits(rows)
        self.assertEqual([x["role"] for x in hits], ["GROUP", "GENERIC"])

    def test_family_evidence_never_authorizes_parser(self) -> None:
        target = {"root_cause": "NO_FORMAL_GROUP_STATEMENT_ROLE_BINDING"}
        spatial = {"pages": []}
        result = d.family_evidence(target, spatial)
        self.assertFalse(result["explicit_group_role_visible_somewhere"])
        self.assertFalse(result["role_local_period_visible_on_all_three_page"])
        self.assertFalse(result["explicit_equity_pair_visible_on_single_line"])


if __name__ == "__main__":
    unittest.main()
