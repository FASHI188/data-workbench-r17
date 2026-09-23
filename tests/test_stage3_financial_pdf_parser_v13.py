import unittest
from decimal import Decimal

import scripts.stage3_financial_pdf_parser as base
import scripts.stage3_financial_pdf_parser_v8 as v13


def cand(concept, value, alias, page=1, penalty=0, strength=3, width=1):
    obs = base.Observation(
        concept=concept,
        status="FOUND",
        raw_value=str(value),
        normalized_cny_value=str(value),
        unit="元",
        unit_multiplier="1",
        page=page,
        matched_alias=alias,
        extraction_scope="TEST",
        confidence="HIGH",
    )
    return {
        "observation": obs,
        "value": Decimal(str(value)),
        "page": page,
        "line_index": 0,
        "width": width,
        "alias": alias,
        "alias_strength": strength,
        "parent_context_penalty": penalty,
        "raw_token": str(value),
    }


class FinancialPdfParserV13Tests(unittest.TestCase):
    def test_huaneng_2014_identity_selects_group_equity_not_parent_subtotal(self):
        candidates = {
            "TOTAL_ASSETS": [cand("TOTAL_ASSETS", "272164949588", "资产总计", page=57)],
            "TOTAL_LIABILITIES": [cand("TOTAL_LIABILITIES", "188745048295", "负债合计", page=58)],
            "TOTAL_EQUITY": [
                cand("TOTAL_EQUITY", "69198218504", "权益合计", page=58, penalty=1, strength=1),
                cand("TOTAL_EQUITY", "83419901293", "股东权益合计", page=58, penalty=0, strength=3),
            ],
        }
        chosen, meta = v13._choose_identity_triplet(candidates)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["TOTAL_EQUITY"]["value"], Decimal("83419901293"))
        self.assertEqual(meta["identity_relative_error"], "0")

    def test_identity_residual_beats_alias_preference(self):
        candidates = {
            "TOTAL_ASSETS": [cand("TOTAL_ASSETS", "1000", "资产总计")],
            "TOTAL_LIABILITIES": [cand("TOTAL_LIABILITIES", "600", "负债合计")],
            "TOTAL_EQUITY": [
                cand("TOTAL_EQUITY", "399", "股东权益合计", strength=3),
                cand("TOTAL_EQUITY", "400", "权益合计", penalty=1, strength=1),
            ],
        }
        chosen, meta = v13._choose_identity_triplet(candidates)
        self.assertEqual(chosen["TOTAL_EQUITY"]["value"], Decimal("400"))
        self.assertEqual(meta["identity_relative_error"], "0")

    def test_no_triplet_outside_unchanged_tolerance(self):
        candidates = {
            "TOTAL_ASSETS": [cand("TOTAL_ASSETS", "1000", "资产总计")],
            "TOTAL_LIABILITIES": [cand("TOTAL_LIABILITIES", "600", "负债合计")],
            "TOTAL_EQUITY": [cand("TOTAL_EQUITY", "350", "股东权益合计")],
        }
        chosen, meta = v13._choose_identity_triplet(candidates)
        self.assertIsNone(chosen)
        self.assertIsNone(meta)

    def test_explicit_group_equity_ignores_prior_parent_context(self):
        lines = [
            "归属于本公司股东",
            "权益合计 69,198,218,504 61,747,779,816",
            "少数股东权益 14,221,682,789 12,296,838,754",
            "股东权益合计 83,419,901,293 74,044,618,570",
        ]
        penalty = v13._parent_context_penalty(lines, 3, 1, "股东权益合计", "TOTAL_EQUITY")
        self.assertEqual(penalty, 0)

    def test_generic_parent_equity_gets_penalty_not_exclusion(self):
        lines = ["归属于本公司股东", "权益合计 69,198,218,504 61,747,779,816"]
        penalty = v13._parent_context_penalty(lines, 1, 1, "权益合计", "TOTAL_EQUITY")
        self.assertEqual(penalty, 1)

    def test_minority_equity_is_context_barrier(self):
        lines = [
            "归属于本公司股东",
            "权益合计 69,198,218,504",
            "少数股东权益 14,221,682,789",
            "权益合计 83,419,901,293",
        ]
        penalty = v13._parent_context_penalty(lines, 3, 1, "权益合计", "TOTAL_EQUITY")
        self.assertEqual(penalty, 0)


if __name__ == "__main__":
    unittest.main()
