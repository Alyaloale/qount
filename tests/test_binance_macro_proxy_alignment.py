import copy
import datetime as dt
import unittest

from qount.research.binance_macro_proxy_alignment import (
    causal_proxy_snapshot, etf_closes, mean_reversion_gap_confirmations, paired_closes, pair_statistics,
)
from qount.research.small_account_breakout import Bar, NY


class TestProxyAlignment(unittest.TestCase):
    def test_pairing_uses_hour_ending_at_ny_close_and_never_fills_a_missing_endpoint(self):
        etf=[dict(date="2026-06-01",available=20000,etf_raw=100,etf_adjusted=99),
             dict(date="2026-06-02",available=106400,etf_raw=101,etf_adjusted=100)]
        data=dict(trade=[Bar(16400,1,3,1,2),Bar(20000,100,300,1,200)],
                  mark=[Bar(16400,1,3,1,2.1),Bar(20000,100,300,1,200)])
        rows=paired_closes(etf,data)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["native_trade"],2)
        self.assertEqual(rows[0]["native_mark"],2.1)

    def test_new_york_close_tracks_dst_instead_of_a_fixed_utc_hour(self):
        stamps=[int(dt.datetime(2026,m,d,9,30,tzinfo=NY).timestamp()) for m,d in ((3,6),(3,9))]
        payload=dict(chart=dict(result=[dict(timestamp=stamps,indicators=dict(
            quote=[dict(close=[100,101])],adjclose=[dict(adjclose=[99,100])]))]))
        rows=etf_closes(payload)
        self.assertEqual([dt.datetime.fromtimestamp(r['available'],dt.timezone.utc).hour for r in rows],[21,20])

    def test_different_price_units_can_have_perfect_return_alignment(self):
        rows=[dict(date=str(i),available=i,etf_raw=x,etf_adjusted=x,native_trade=x*10) for i,x in enumerate((100,102,101,105))]
        s=pair_statistics(rows)['etf_raw']
        self.assertAlmostEqual(s['correlation'],1)
        self.assertAlmostEqual(s['mean_abs_daily_log_return_difference_bps'],0)

    def test_future_pairs_cannot_change_a_causal_snapshot(self):
        rows=[dict(date=str(i),available=i*100,etf_adjusted=100+i,native_trade=200+i) for i in range(30)]
        before=causal_proxy_snapshot(rows,2100)
        changed=copy.deepcopy(rows)
        changed[-1]['native_trade']=1
        self.assertEqual(causal_proxy_snapshot(changed,2100),before)

    def test_missing_native_session_cannot_be_treated_as_a_one_day_return(self):
        rows=[dict(date=str(i),available=i*100,session_index=i,etf_raw=100+i,
                   etf_adjusted=100+i,native_trade=200+i) for i in (1,3,4)]
        s=pair_statistics(rows)
        self.assertEqual(s['omitted_nonconsecutive_transitions'],1)
        self.assertEqual(s['etf_raw']['return_pairs'],1)
        self.assertNotIn('native_return_1',causal_proxy_snapshot(rows,300))

    def fixture(self):
        now=int(dt.datetime(2026,6,1,10,tzinfo=NY).timestamp())
        signal=int(dt.datetime(2026,5,29,16,tzinfo=NY).timestamp())
        start=(signal//86400-20)*86400
        bars=[Bar(t,100,101,99,100,100) for t in range(start,now+7200,3600)]
        bars=[Bar(b.t,103,b.h+3,b.l+3,103,100) if b.t==now else b for b in bars]
        return {'A':dict(trade=bars)}, {'A':[dict(available=signal,tactical_setup='mean_reversion')]}, now,signal

    def test_gap_uses_actual_signal_friday_not_the_intervening_sunday(self):
        data,fs,now,signal=self.fixture()
        g=mean_reversion_gap_confirmations(data,fs,[('A',now)])['A',now]
        self.assertFalse(g['eligible'])
        self.assertEqual(g['signal_close'],100)
        self.assertEqual(g['signal_atr'],2)
        self.assertAlmostEqual(g['gap_atr'],1.5)
        self.assertLessEqual(g['atr_available'],signal)

    def test_entry_range_and_all_post_signal_ranges_cannot_change_gate(self):
        data,fs,now,signal=self.fixture()
        original=mean_reversion_gap_confirmations(data,fs,[('A',now)])
        data['A']['trade']=[Bar(b.t,b.o,10000,.01,9999,1e9) if b.t>=signal else b for b in data['A']['trade']]
        self.assertEqual(mean_reversion_gap_confirmations(data,fs,[('A',now)]),original)

    def test_negative_gap_is_not_expired_and_trend_bypasses_the_gate(self):
        data,fs,now,signal=self.fixture()
        data['A']['trade']=[Bar(b.t,95,96,94,95,100) if b.t==now else b for b in data['A']['trade']]
        self.assertTrue(mean_reversion_gap_confirmations(data,fs,[('A',now)])['A',now]['eligible'])
        fs['A'][0]['tactical_setup']='breakout'
        self.assertTrue(mean_reversion_gap_confirmations(data,fs,[('A',now)])['A',now]['eligible'])
