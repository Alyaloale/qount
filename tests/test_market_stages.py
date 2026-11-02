"""Time correctness and event semantics of the offline market state machine."""
import math
import random
import unittest

from qount.research.market_stages import environment_permission, market_state_machine, stage_permission, stage_rows
from qount.research_data.bars import Bar


def history(count=260):
    return [Bar(i*86400, 100+.5*math.sin(i/3), 101+.5*math.sin(i/3),
                99+.5*math.sin(i/3), 100+.5*math.sin(i/3), 1000) for i in range(count)]


class MarketStagesTest(unittest.TestCase):
    def test_future_append_never_changes_past_states_or_boundaries(self):
        rng = random.Random(30)
        bars, price = [], 100.
        for i in range(420):
            close = price*math.exp(rng.gauss(0, .012))
            bars.append(Bar(i*86400, price, max(price, close)*1.005,
                            min(price, close)*.995, close, 1000))
            price = close
        full, prefix = market_state_machine(bars), market_state_machine(bars[:360])
        self.assertEqual({k: v for k, v in full.items() if k < 360*86400}, prefix)

    def test_failed_break_is_observed_later_and_keeps_original_boundary(self):
        bars = history()
        boundary = max(b.h for b in bars[-20:])
        i = len(bars)
        bars.append(Bar(i*86400, 101, boundary+1.5, 100, boundary+1, 1000))
        bars.append(Bar((i+1)*86400, boundary+.5, boundary+1, boundary-2, boundary-1, 1000))
        rows = market_state_machine(bars)
        a, b = rows[i*86400], rows[(i+1)*86400]
        self.assertEqual(a["event"]["status"], "pending")
        self.assertEqual(b["event"]["status"], "failed")
        self.assertEqual(a["event"]["boundary"], b["event"]["boundary"])
        self.assertEqual(b["event"]["observed_at"], (i+1)*86400)
        self.assertEqual(a["event"]["started_at"], i*86400)

    def test_confirmation_requires_later_close_and_can_still_fail_within_window(self):
        bars = history()
        level, i = max(b.h for b in bars[-20:]), len(bars)
        for j, close in enumerate((level+1, level+1.1, level-.5)):
            bars.append(Bar((i+j)*86400, close, close+.5, close-.5, close, 1000))
        rows = market_state_machine(bars)
        self.assertEqual(rows[i*86400]["event"]["status"], "pending")
        self.assertEqual(rows[(i+1)*86400]["event"]["status"], "confirmed")
        self.assertEqual(rows[(i+2)*86400]["event"]["status"], "failed")

    def test_shock_overrides_event_and_routes_no_new_position(self):
        bars = history()
        bars.append(Bar(260*86400, 100, 121, 99, 120, 1000))
        row = market_state_machine(bars)[260*86400]
        self.assertTrue(row["shock"])
        self.assertEqual(row["action_state"], "shock")
        self.assertEqual(row["route_side"], 0)
        self.assertEqual(row["risk_scale"], 0)
        self.assertIsNotNone(row["event"])

    def test_warmup_is_unknown_and_invalid_data_rejected(self):
        self.assertTrue(all(r["action_state"] == "unknown" for r in market_state_machine(history(100)).values()))
        bars = history()
        with self.assertRaises(ValueError):
            stage_rows(bars+[bars[-1]])
        with self.assertRaises(ValueError):
            stage_rows(bars+[Bar(260*86400, 100, 90, 110, 100)])

    def test_commodity_does_not_inherit_equity_veto(self):
        asset = dict(direction=1, confirmed=True, shock=False, high_vol=False)
        market = dict(direction=-1, confirmed=True, shock=False, high_vol=True)
        self.assertFalse(stage_permission(asset, market, 1)[0])
        self.assertEqual(stage_permission(asset, market, 1, systematic=False), (True, 1., "stage_allowed"))
        self.assertFalse(stage_permission(None, market, 1)[0])

    def test_environment_vetoes_weak_breadth_and_countertrend_traps(self):
        local = dict(route_side=-1, action_state="down_breakout")
        bear = dict(action_state="down_trend", direction=-1, confirmed=True, er20=.5)
        bull = dict(action_state="up_trend", direction=1, confirmed=True, er20=.5)
        self.assertFalse(environment_permission(local, bear, [bear, bull, bull])[0])
        self.assertTrue(environment_permission(local, bear, [bear, bear, bull])[0])
        local["action_state"] = "failed_up_breakout"
        self.assertFalse(environment_permission(local, bull, [bull])[0])
        self.assertTrue(environment_permission(local, bull, [bull], systematic=False)[0])


if __name__ == "__main__":
    unittest.main()
