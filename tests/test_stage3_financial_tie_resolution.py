import copy
import unittest

import scripts.extract_stage3_financial_pdf_values as ext
import scripts.extract_stage3_financial_pdf_values_v2 as extv2
from scripts.stage3_financial_pdf_parser import Observation
from scripts.stage3_financial_pdf_parser_v2 import _balance_sheet_identity_error


def candidate(aid, title, pages, t1, t2, values):
    return {
        "id": aid,
        "title": title,
        "url": f"https://example.invalid/{aid}.pdf",
        "sha256": aid.zfill(64)[-64:],
        "bytes": pages * 1000,
        "parsed": {
            "page_count": pages,
            "tier1_found": t1,
            "tier2_found": t2,
            "validation_errors": [],
            "observations": {
                k: {"status": "FOUND", "normalized_cny_value": str(v)}
                for k, v in values.items()
            },
        },
    }


class IssuerCandidateTests(unittest.TestCase):
    def test_explicit_other_a_share_issuer_is_excluded(self):
        old_tokens = copy.deepcopy(ext.ISSUER_TOKEN_CODES)
        old_related = copy.deepcopy(ext.RELATED_CODES)
        try:
            ext.ISSUER_TOKEN_CODES.clear()
            ext.ISSUER_TOKEN_CODES.update({"金隅集团": {"601992"}, "冀东水泥": {"000401"}})
            ext.RELATED_CODES.clear()
            ext.RELATED_CODES.update({"601992": {"601992"}, "000401": {"000401"}})
            cands = [
                {"id": "1221576098", "title": "唐山冀东水泥股份有限公司2024年第三季度报告", "url": "u1"},
                {"id": "1221576101", "title": "北京金隅集团股份有限公司2024年第三季度报告", "url": "u2"},
            ]
            keep, excluded = ext.filter_candidates_by_issuer(cands, "601992", "1221576101")
            self.assertEqual([x["id"] for x in keep], ["1221576101"])
            self.assertEqual([x["id"] for x in excluded], ["1221576098"])
            self.assertIn("OTHER_A_SHARE_ISSUER", excluded[0]["excluded_reason"])
        finally:
            ext.ISSUER_TOKEN_CODES.clear(); ext.ISSUER_TOKEN_CODES.update(old_tokens)
            ext.RELATED_CODES.clear(); ext.RELATED_CODES.update(old_related)

    def test_registered_code_transition_is_same_lineage(self):
        old_tokens = copy.deepcopy(ext.ISSUER_TOKEN_CODES)
        old_related = copy.deepcopy(ext.RELATED_CODES)
        try:
            ext.ISSUER_TOKEN_CODES.clear()
            ext.ISSUER_TOKEN_CODES.update({"深赤湾": {"000022"}, "招商港口": {"001872"}})
            ext.RELATED_CODES.clear()
            ext.RELATED_CODES.update({"000022": {"000022", "001872"}, "001872": {"000022", "001872"}})
            cands = [
                {"id": "1", "title": "招商港口2018年年度报告", "url": "u1"},
                {"id": "2", "title": "深赤湾2018年年度报告", "url": "u2"},
            ]
            keep, excluded = ext.filter_candidates_by_issuer(cands, "000022", "2")
            self.assertEqual(len(keep), 2)
            self.assertEqual(excluded, [])
        finally:
            ext.ISSUER_TOKEN_CODES.clear(); ext.ISSUER_TOKEN_CODES.update(old_tokens)
            ext.RELATED_CODES.clear(); ext.RELATED_CODES.update(old_related)


class TieResolutionTests(unittest.TestCase):
    def test_same_title_structural_full_report_wins_only_when_canonical(self):
        title = "正平股份2025年年度报告"
        short = candidate("1", title, 10, 4, 0, {"OPERATING_REVENUE": 100})
        full = candidate("2", title, 309, 6, 3, {"OPERATING_REVENUE": 200})
        chosen, resolution, error = ext.resolve_candidates([short, full], "2")
        self.assertEqual(chosen["id"], "2")
        self.assertEqual(resolution, "TIE_SAME_TITLE_STRUCTURAL_FULL_REPORT")
        self.assertIsNone(error)

    def test_same_title_conflict_still_fails_when_structure_is_not_decisive(self):
        title = "某公司2025年年度报告"
        a = candidate("1", title, 100, 6, 3, {"OPERATING_REVENUE": 100})
        b = candidate("2", title, 120, 6, 3, {"OPERATING_REVENUE": 200})
        chosen, resolution, error = ext.resolve_candidates([a, b], "2")
        self.assertIsNone(chosen)
        self.assertEqual(resolution, "TIE_VALUE_CONFLICT")
        self.assertIn("OPERATING_REVENUE", error)

    def test_structural_rule_never_overrides_noncanonical_long_document(self):
        title = "某公司2025年年度报告"
        full = candidate("1", title, 300, 6, 3, {"OPERATING_REVENUE": 100})
        short_canonical = candidate("2", title, 10, 4, 0, {"OPERATING_REVENUE": 200})
        chosen, resolution, _ = ext.resolve_candidates([full, short_canonical], "2")
        self.assertIsNone(chosen)
        self.assertEqual(resolution, "TIE_VALUE_CONFLICT")

    def test_older_same_title_noncanonical_404_can_yield_to_valid_canonical(self):
        title = "上海康德莱企业发展集团股份有限公司2024年半年度报告"
        ghost = {
            "id": "1221022903",
            "title": title,
            "url": "https://example.invalid/1221022903.pdf",
            "error": "RuntimeError(\"HTTPError('404 Client Error: Not Found')\")",
        }
        canonical = candidate("1221358739", title, 205, 6, 3, {"OPERATING_REVENUE": 1122956330.44})
        chosen, resolution, error = extv2.resolve_candidates([ghost, canonical], "1221358739")
        self.assertEqual(chosen["id"], "1221358739")
        self.assertIn("AFTER_STALE_NONCANONICAL_404", resolution)
        self.assertIsNone(error)

    def test_transient_failure_never_uses_stale_source_exception(self):
        title = "某公司2024年半年度报告"
        bad = {"id": "100", "title": title, "url": "u", "error": "TimeoutError('timed out')"}
        canonical = candidate("101", title, 200, 6, 3, {"OPERATING_REVENUE": 1})
        chosen, resolution, _ = extv2.resolve_candidates([bad, canonical], "101")
        self.assertIsNone(chosen)
        self.assertEqual(resolution, "TIE_SOURCE_INCOMPLETE")

    def test_newer_missing_candidate_never_yields_to_older_canonical(self):
        title = "某公司2024年半年度报告"
        canonical = candidate("100", title, 200, 6, 3, {"OPERATING_REVENUE": 1})
        bad = {"id": "101", "title": title, "url": "u", "error": "HTTPError('404 Client Error: Not Found')"}
        chosen, resolution, _ = extv2.resolve_candidates([canonical, bad], "100")
        self.assertIsNone(chosen)
        self.assertEqual(resolution, "TIE_SOURCE_INCOMPLETE")


class AccountingIdentityTests(unittest.TestCase):
    def _obs(self, value):
        return Observation(concept="X", status="FOUND", normalized_cny_value=str(value))

    def test_balance_sheet_identity_passes_with_rounding(self):
        obs = {
            "TOTAL_ASSETS": self._obs("1000"),
            "TOTAL_LIABILITIES": self._obs("700"),
            "TOTAL_EQUITY": self._obs("300.5"),
        }
        self.assertIsNone(_balance_sheet_identity_error(obs))

    def test_balance_sheet_unit_mismatch_is_rejected(self):
        obs = {
            "TOTAL_ASSETS": self._obs("731246"),
            "TOTAL_LIABILITIES": self._obs("6991148367.90"),
            "TOTAL_EQUITY": self._obs("321320044.53"),
        }
        err = _balance_sheet_identity_error(obs)
        self.assertIsNotNone(err)
        self.assertIn("BALANCE_SHEET_IDENTITY_MISMATCH", err)


if __name__ == "__main__":
    unittest.main()
