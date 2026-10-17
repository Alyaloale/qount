"""Timing, maturity and gate-independent sampling for ETF direction diagnostics."""
import datetime as dt
import unittest

from qount.research.binance_macro_history import (
    account_concentration, adjusted_bars, first_episodes, forward_label,
)
from qount.research.small_account_breakout import Bar, NY


def bar(day, opening, close):
    stamp = int(dt.datetime.combine(dt.date.fromisoformat(day),dt.time(16),NY).timestamp())
    return Bar(stamp,opening,max(opening,close)+1,min(opening,close)-1,close,100)


class TestMacroHistory(unittest.TestCase):
    def test_next_actual_session_open_after_holiday_and_costs(self):
        bars = [bar("2025-01-17",90,100),bar("2025-01-21",110,121)]
        label = forward_label(bars,0,1)
        expected = int(dt.datetime(2025,1,21,9,30,tzinfo=NY).timestamp())
        self.assertEqual(label["entry_time"],expected)
        self.assertAlmostEqual(label["gross_return"],.10)
        ratio = 121*.9975/(110*1.0025)
        self.assertAlmostEqual(label["base"],ratio-1-.0005*(1+ratio))
        self.assertLess(label["double_cost"],label["base"])

    def test_missing_maturity_not_liquidated_at_last_price(self):
        bars = [bar("2025-01-17",90,100),bar("2025-01-21",110,121)]
        self.assertEqual(forward_label(bars,0,5),dict(censored=True))

    def test_entry_is_not_signal_close_or_future_entry_close(self):
        bars = [bar("2025-01-17",90,100),bar("2025-01-21",110,200),bar("2025-01-22",80,121)]
        before = forward_label(bars,0,2)
        bars[1] = bar("2025-01-21",110,500)
        after = forward_label(bars,0,2)
        self.assertEqual(before,after)

    def test_sampling_precedes_daily_gate_and_future_prices(self):
        start = dt.date(2025,1,1)
        bars = [bar((start+dt.timedelta(days=i)).isoformat(),100,100+i%3) for i in range(40)]
        fs = [dict(available=b.t,date=dt.datetime.fromtimestamp(b.t,NY).date().isoformat(),
                   entry_tactical=i in (1,2,4,18),tactical_setup="mean_reversion") for i,b in enumerate(bars)]
        before = first_episodes(fs,bars)
        self.assertEqual([e["signal_index"] for e in before],[1,4,18])
        self.assertEqual([e["nonoverlap"] for e in before],[True,False,True])
        self.assertFalse(before[-1]["daily_reversal"])
        bars[18] = bar((start+dt.timedelta(days=18)).isoformat(),100,105)
        after = first_episodes(fs,bars)
        self.assertTrue(after[-1]["daily_reversal"])
        self.assertEqual([e["nonoverlap"] for e in before],[e["nonoverlap"] for e in after])

    def test_uniform_ohlc_adjustment_and_close_availability(self):
        t = int(dt.datetime(2025,1,21,9,30,tzinfo=NY).timestamp())
        r = dict(timestamp=[t],indicators=dict(quote=[dict(open=[100],high=[120],low=[90],close=[110],volume=[50])],
                                              adjclose=[dict(adjclose=[55])]))
        b = adjusted_bars(dict(chart=dict(result=[r])))[0]
        self.assertEqual((b.o,b.h,b.l,b.c),(50,60,45,55))
        self.assertEqual(b.t,int(dt.datetime(2025,1,21,16,tzinfo=NY).timestamp()))

    def test_concentration_uses_minute_pnl_and_separates_censoring(self):
        a = dict(trades=[dict(symbol="IWM",entry_time=1,exit_time=2,exit_reason="time_exit",net_pnl=99),
                        dict(symbol="XLE",entry_time=3,exit_time=4,exit_reason="end_of_sample",net_pnl=99)],
                 minute_checks=[dict(entry_time=1,exit_time=2,net_pnl=2),dict(entry_time=3,exit_time=4,net_pnl=3)])
        c = account_concentration(a)
        self.assertEqual((c["total_pnl"],c["closed_pnl"],c["censored_pnl"],c["closed_ex_best_pnl"]),(5,2,3,0))
        a["minute_checks"][0]["exit_time"] = 9
        with self.assertRaises(ValueError):
            account_concentration(a)


if __name__=="__main__":
    unittest.main()
