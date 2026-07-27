import unittest
from scripts.stage3_trading_universe import eligible_mainboard_under_70,assert_point_in_time_price

class TradingUniverseTests(unittest.TestCase):
    def test_strict_price_boundary(self):
        self.assertTrue(eligible_mainboard_under_70('SSE_MAIN','69.99'))
        self.assertTrue(eligible_mainboard_under_70('SZSE_MAIN','0.01'))
        self.assertFalse(eligible_mainboard_under_70('SSE_MAIN','70.00'))
        self.assertFalse(eligible_mainboard_under_70('SZSE_MAIN','70.01'))
    def test_excluded_boards_never_pass_even_below_70(self):
        for board in ('STAR','CHINEXT','BSE','NEEQ'):
            self.assertFalse(eligible_mainboard_under_70(board,'1.00'))
    def test_nonpositive_price_is_not_tradable(self):
        self.assertFalse(eligible_mainboard_under_70('SSE_MAIN','0'))
        self.assertFalse(eligible_mainboard_under_70('SZSE_MAIN','-1'))
    def test_future_price_rejected(self):
        assert_point_in_time_price('2026-07-27T14:59:00+08:00','2026-07-27T15:00:00+08:00')
        with self.assertRaises(ValueError):
            assert_point_in_time_price('2026-07-27T15:00:01+08:00','2026-07-27T15:00:00+08:00')
if __name__=='__main__':unittest.main()
