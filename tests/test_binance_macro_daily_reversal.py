import copy
import datetime as dt
import unittest

from qount.research.binance_macro_proxy_alignment import mean_reversion_daily_confirmations
from qount.research.small_account_breakout import NY


class TestDailyReversal(unittest.TestCase):
    def fixture(self):
        def t(day,hour=16):
            return int(dt.datetime(2026,6,day,hour,tzinfo=NY).timestamp())
        # Juneteenth is a holiday; prior actual session is Thursday18th.
        rows=[dict(available=t(18),etf_adjusted=100,etf_raw=103),
              dict(available=t(22),etf_adjusted=101,etf_raw=102),
              dict(available=t(23),etf_adjusted=1000,etf_raw=1000)]
        features={'A':[dict(available=t(22),tactical_setup='mean_reversion')]}
        return features,{'A':rows},[('A',t(23,10))]

    def test_uses_prior_actual_session_and_adjusted_signal_price(self):
        fs,prices,clocks=self.fixture()
        r=mean_reversion_daily_confirmations(fs,prices,clocks)[clocks[0]]
        self.assertTrue(r['eligible'])
        self.assertEqual(r['prior_available'],prices['A'][0]['available'])
        self.assertAlmostEqual(r['daily_return'],.01)
        self.assertLess(r['prior_available'],r['feature_available'])
        self.assertLess(r['feature_available'],r['asof'])

    def test_negative_or_flat_close_return_is_not_a_daily_reversal(self):
        for price in (99,100):
            fs,prices,clocks=self.fixture();prices['A'][1]['etf_adjusted']=price
            self.assertFalse(mean_reversion_daily_confirmations(fs,prices,clocks)[clocks[0]]['eligible'])

    def test_future_price_cannot_override_the_exact_original_signal(self):
        fs,prices,clocks=self.fixture();prices['A'][1]['etf_adjusted']=99
        original=mean_reversion_daily_confirmations(fs,prices,clocks)
        changed=copy.deepcopy(prices);changed['A'][-1]['etf_adjusted']=.001
        self.assertEqual(mean_reversion_daily_confirmations(fs,changed,clocks),original)

    def test_missing_exact_signal_or_prior_session_fails_closed(self):
        fs,prices,clocks=self.fixture();prices['A'].pop(1)
        self.assertFalse(mean_reversion_daily_confirmations(fs,prices,clocks)[clocks[0]]['eligible'])
        fs,prices,clocks=self.fixture();prices['A'].pop(0)
        self.assertFalse(mean_reversion_daily_confirmations(fs,prices,clocks)[clocks[0]]['eligible'])

    def test_trend_entry_does_not_acquire_a_new_confirmation_requirement(self):
        fs,prices,clocks=self.fixture();fs['A'][0]['tactical_setup']='pullback'
        self.assertTrue(mean_reversion_daily_confirmations(fs,{},clocks)[clocks[0]]['eligible'])
