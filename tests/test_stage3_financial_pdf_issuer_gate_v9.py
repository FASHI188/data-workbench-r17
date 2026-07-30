import unittest

import scripts.extract_stage3_financial_pdf_values_v6 as v9


class PdfIssuerGateV9Tests(unittest.TestCase):
    def setUp(self):
        v9.EXPECTED_BY_CANONICAL_ID.clear()

    @staticmethod
    def candidate(cid, code, sha="sha"):
        return {
            "id": cid,
            "title": cid,
            "sha256": sha,
            "parsed": {
                "declared_a_share_codes": [code] if code else [],
                "observations": {},
                "tier1_found": 0,
                "tier2_found": 0,
            },
        }

    def test_registered_transition_endpoints_are_recognized_identity_codes(self):
        for code in ("000022", "001872", "000043", "001914", "601313", "601360"):
            self.assertIn(code, v9.KNOWN_A_SHARE_CODES)

    def test_code_label_regex_requires_exactly_six_digits(self):
        for label in ("证券代码", "股票代码", "公司代码"):
            match = v9.CODE_LABEL_RE.search(f"{label}：601992")
            self.assertIsNotNone(match)
            self.assertEqual(match.group(1), "601992")
            self.assertIsNone(v9.CODE_LABEL_RE.search(f"{label}：6019920"))
            self.assertIsNone(v9.CODE_LABEL_RE.search(f"{label}：601992123"))

    def test_noncanonical_other_issuer_is_excluded_before_value_compare(self):
        v9.EXPECTED_BY_CANONICAL_ID["1221576101"] = {"601992"}
        wrong = self.candidate("1221576098", "000401", sha="jidong")
        right = self.candidate("1221576101", "601992", sha="jinyu")
        chosen, resolution, err = v9.resolve_candidates([wrong, right], "1221576101")
        self.assertIsNone(err)
        self.assertEqual(chosen["id"], "1221576101")
        self.assertEqual(resolution, "SINGLE_CANONICAL_AFTER_PDF_ISSUER_GATE")
        self.assertIn("PDF_DECLARES_OTHER_A_SHARE_ISSUER", wrong["excluded_reason"])

    def test_canonical_other_issuer_fails_closed(self):
        v9.EXPECTED_BY_CANONICAL_ID["canonical"] = {"601992"}
        bad = self.candidate("canonical", "000401")
        chosen, resolution, err = v9.resolve_candidates([bad], "canonical")
        self.assertIsNone(chosen)
        self.assertEqual(resolution, "CANONICAL_PDF_ISSUER_MISMATCH")
        self.assertIn("000401", err)

    def test_related_transition_code_is_allowed(self):
        v9.EXPECTED_BY_CANONICAL_ID["new"] = {"601313", "601360"}
        old = self.candidate("old", "601313", sha="same")
        new = self.candidate("new", "601360", sha="same")
        chosen, resolution, err = v9.resolve_candidates([old, new], "new")
        self.assertIsNone(err)
        self.assertEqual(chosen["id"], "new")
        self.assertEqual(resolution, "TIE_IDENTICAL_PDF_SHA")

    def test_no_explicit_code_does_not_trigger_exclusion(self):
        v9.EXPECTED_BY_CANONICAL_ID["canonical"] = {"601992"}
        a = self.candidate("a", "", sha="same")
        b = self.candidate("canonical", "601992", sha="same")
        chosen, resolution, err = v9.resolve_candidates([a, b], "canonical")
        self.assertIsNone(err)
        self.assertEqual(chosen["id"], "canonical")
        self.assertEqual(resolution, "TIE_IDENTICAL_PDF_SHA")


if __name__ == "__main__":
    unittest.main()
