import unittest

from scripts.build_stage3_announcement_ledger_v2 import (
    registered_transition_alias,
    same_issuer_non_equity_instrument,
)


TRANSITIONS = [
    {"exchange":"SZSE","old_code":"000022","new_code":"001872","effective_date":"2018-12-26"},
    {"exchange":"SZSE","old_code":"000043","new_code":"001914","effective_date":"2019-12-16"},
    {"exchange":"SSE","old_code":"601313","new_code":"601360","effective_date":"2018-02-28"},
]


class AnnouncementTransitionTests(unittest.TestCase):
    def test_registered_alias_on_effective_date_is_allowed(self):
        t=registered_transition_alias("SZSE","001872","000022","2018-12-26",TRANSITIONS)
        self.assertIsNotNone(t)
        self.assertEqual(t["old_code"],"000022")

    def test_alias_before_effective_date_is_rejected(self):
        self.assertIsNone(
            registered_transition_alias("SZSE","001872","000022","2018-12-25",TRANSITIONS)
        )

    def test_reverse_direction_is_rejected(self):
        self.assertIsNone(
            registered_transition_alias("SZSE","000022","001872","2018-12-26",TRANSITIONS)
        )

    def test_unregistered_cross_company_code_is_rejected(self):
        self.assertIsNone(
            registered_transition_alias("SSE","601360","600000","2018-02-28",TRANSITIONS)
        )

    def test_exchange_mismatch_is_rejected(self):
        self.assertIsNone(
            registered_transition_alias("SSE","001914","000043","2019-12-16",TRANSITIONS)
        )

    def test_all_three_frozen_transitions_are_supported(self):
        cases=[
            ("SZSE","001872","000022","2018-12-26"),
            ("SZSE","001914","000043","2019-12-16"),
            ("SSE","601360","601313","2018-02-28"),
        ]
        for args in cases:
            with self.subTest(args=args):
                self.assertIsNotNone(registered_transition_alias(*args,TRANSITIONS))


class NonEquityInstrumentTests(unittest.TestCase):
    def setUp(self):
        self.equity_codes={"600325","601360","001872","001914","000022","000043","601313"}

    def test_same_org_bond_code_is_allowed_as_issuer_evidence(self):
        self.assertTrue(
            same_issuer_non_equity_instrument(
                "600325","122028","gssh0600325","gssh0600325",self.equity_codes
            )
        )

    def test_other_a_share_code_is_never_treated_as_instrument(self):
        self.assertFalse(
            same_issuer_non_equity_instrument(
                "600325","601360","gssh0600325","gssh0600325",self.equity_codes
            )
        )

    def test_org_mismatch_is_rejected(self):
        self.assertFalse(
            same_issuer_non_equity_instrument(
                "600325","122028","gssh0600325","gssh0000001",self.equity_codes
            )
        )

    def test_missing_returned_org_is_rejected(self):
        self.assertFalse(
            same_issuer_non_equity_instrument(
                "600325","122028","gssh0600325","",self.equity_codes
            )
        )

    def test_non_six_digit_instrument_code_is_rejected(self):
        self.assertFalse(
            same_issuer_non_equity_instrument(
                "600325","HFZQ","gssh0600325","gssh0600325",self.equity_codes
            )
        )


if __name__=="__main__":
    unittest.main()
