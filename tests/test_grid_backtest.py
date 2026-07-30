"""Unit tests for the GRID-B S1 backtest engine (synthetic bars, no network)."""

from __future__ import annotations

import datetime as _dt
import unittest

from qount.legacy.grid_b.backtest import _hold_above_ma
from qount.legacy.grid_b.backtest import _seed_range_ladder
from qount.legacy.grid_b.backtest import _trailing_daily_vol
from qount.legacy.grid_b.backtest import active_fraction
from qount.legacy.grid_b.backtest import daily_states_by_date
from qount.legacy.grid_b.backtest import regime_slices
from qount.legacy.grid_b.backtest import run_s1
from qount.legacy.grid_b.backtest import run_s1e
from qount.research_data.market_data import Bar


def _bar(date_ms: int, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(ts_ms=date_ms, open=o, high=h, low=l, close=c, volume=1.0)


def _daily_bar(date: _dt.date, close: float) -> Bar:
    ts = int(_dt.datetime(date.year, date.month, date.day, tzinfo=_dt.UTC).timestamp() * 1000)
    return Bar(ts_ms=ts, open=close, high=close, low=close, close=close, volume=1.0)


# Daily bars on 2021-01-01..05, rising so SMA(3,confirm1) is ACTIVE by 01-03 onward.
_DAY_MS = 86_400_000
_BASE_MS = 1_609_459_200_000  # 2021-01-01 00:00 UTC


def _daily_active() -> list[Bar]:
    closes = [100, 101, 102, 103, 104]
    return [_bar(_BASE_MS + i * _DAY_MS, c, c, c, c) for i, c in enumerate(closes)]


# All hourly bars live on 2021-01-05 (an ACTIVE day).
_ACTIVE_DAY_MS = _BASE_MS + 4 * _DAY_MS


class TestS1Backtest(unittest.TestCase):
    def test_oscillation_harvests_positive(self) -> None:
        # price sawtooths 102 <-> 98 inside a [95,105] grid: each dip buys, each pop sells.
        hourly: list[Bar] = []
        ts = _ACTIVE_DAY_MS
        for _ in range(40):
            hourly.append(_bar(ts, 100, 100.2, 98.0, 98.2))   # dip -> buys
            ts += 3_600_000
            hourly.append(_bar(ts, 98.2, 102.0, 98.0, 101.8)) # pop -> sells
            ts += 3_600_000

        res = run_s1(hourly, _daily_active(), step=0.01, lower=95.0, upper=105.0,
                     sma_window=3, confirm_bars=1)
        self.assertGreater(res.total_crossings, 0)
        self.assertGreater(res.buy_fills, 0)
        self.assertGreater(res.sell_fills, 0)
        # banked grid harvest must be strictly positive after fees in a clean oscillation
        self.assertGreater(res.grid_realized_harvest, 0.0)

    def test_straight_bull_underperforms_hold(self) -> None:
        # monotonic rise from 100 -> ~140: an unseeded grid barely buys (price keeps
        # rising, few down-crosses) => mostly cash => 踏空 => loses to buy-and-hold.
        hourly: list[Bar] = []
        ts = _ACTIVE_DAY_MS
        price = 100.0
        for _ in range(60):
            nxt = price * 1.006
            hourly.append(_bar(ts, price, nxt, price * 0.999, nxt))
            price = nxt
            ts += 3_600_000

        res = run_s1(hourly, _daily_active(), step=0.01, lower=95.0, upper=160.0,
                     sma_window=3, confirm_bars=1)
        self.assertGreater(res.hold_total_return, res.grid_total_return)
        self.assertTrue(res.lookahead_range is False)  # explicit range given

    def test_lookahead_flag_when_range_inferred(self) -> None:
        hourly = [_bar(_ACTIVE_DAY_MS + i * 3_600_000, 100, 102, 98, 100 + (i % 3))
                  for i in range(10)]
        res = run_s1(hourly, _daily_active(), step=0.01, sma_window=3, confirm_bars=1)
        self.assertTrue(res.lookahead_range)

    def test_requires_bars(self) -> None:
        with self.assertRaises(ValueError):
            run_s1([], _daily_active())

    def test_curves_are_returned_and_match_totals(self) -> None:
        hourly: list[Bar] = []
        ts = _ACTIVE_DAY_MS
        for _ in range(40):
            hourly.append(_bar(ts, 100, 100.2, 98.0, 98.2))
            ts += 3_600_000
            hourly.append(_bar(ts, 98.2, 102.0, 98.0, 101.8))
            ts += 3_600_000

        res = run_s1(hourly, _daily_active(), step=0.01, lower=95.0, upper=105.0,
                     sma_window=3, confirm_bars=1)
        self.assertEqual(len(res.grid_curve), len(hourly))
        self.assertEqual(len(res.hold_curve), len(hourly))
        self.assertAlmostEqual(res.grid_curve[-1] - 1.0, res.grid_total_return, places=9)
        self.assertAlmostEqual(res.hold_curve[-1] - 1.0, res.hold_total_return, places=9)


class TestRegimeSlices(unittest.TestCase):
    def test_length_mismatch_raises(self) -> None:
        daily = [_daily_bar(_dt.date(2021, 1, 1), 100.0)]
        hourly = [_bar(_BASE_MS, 100, 100, 100, 100)]
        with self.assertRaises(ValueError):
            regime_slices(hourly, daily, grid_curve=[1.0, 2.0], hold_curve=[1.0])

    def test_classifies_chop_and_aggregates_delta(self) -> None:
        # daily closes Jan1..Aug31 2021: alternate 100/105 (high vol, ~0 drift over any
        # 91-day window with even day-count) -> Mar/Apr/May should classify as "chop".
        start = _dt.date(2021, 1, 1)
        end = _dt.date(2021, 8, 31)
        daily: list[Bar] = []
        d = start
        i = 0
        while d <= end:
            close = 100.0 if i % 2 == 0 else 105.0
            daily.append(_daily_bar(d, close))
            d += _dt.timedelta(days=1)
            i += 1

        # one "hourly" bar per day for Mar..May (92 days): linear curves so each
        # month's Δ(grid-hold) is a known positive number.
        hourly: list[Bar] = []
        d = _dt.date(2021, 3, 1)
        h_end = _dt.date(2021, 5, 31)
        while d <= h_end:
            hourly.append(_daily_bar(d, 0.0))
            d += _dt.timedelta(days=1)
        n = len(hourly)
        self.assertEqual(n, 92)
        grid_curve = [100.0 + i for i in range(n)]
        hold_curve = [100.0 + 0.5 * i for i in range(n)]

        result = regime_slices(hourly, daily, grid_curve, hold_curve)
        months = {m.month: m for m in result.months}
        self.assertEqual(set(months), {"2021-03", "2021-04", "2021-05"})
        for m in months.values():
            self.assertEqual(m.regime, "chop")
            self.assertLess(abs(m.r91), 0.10)
            self.assertGreater(m.annualized_vol, 0.30)
            self.assertGreater(m.grid_minus_hold, 0.0)

        delta = result.annualized_delta("chop")
        self.assertIsNotNone(delta)
        self.assertGreater(delta, 0.0)
        self.assertIsNone(result.annualized_delta("trend"))

    def test_classifies_trend_month(self) -> None:
        # daily closes rise monotonically ~0.5%/day: any 91-day window has r91 >> +10%.
        start = _dt.date(2021, 1, 1)
        end = _dt.date(2021, 8, 31)
        daily = []
        price = 100.0
        d = start
        while d <= end:
            daily.append(_daily_bar(d, price))
            price *= 1.005
            d += _dt.timedelta(days=1)

        hourly = []
        d = _dt.date(2021, 4, 1)
        h_end = _dt.date(2021, 4, 30)
        while d <= h_end:
            hourly.append(_daily_bar(d, 0.0))
            d += _dt.timedelta(days=1)
        n = len(hourly)
        grid_curve = [100.0 + i for i in range(n)]
        hold_curve = [100.0 + i for i in range(n)]

        result = regime_slices(hourly, daily, grid_curve, hold_curve)
        self.assertEqual(len(result.months), 1)
        self.assertEqual(result.months[0].regime, "trend")
        self.assertGreater(result.months[0].r91, 0.10)


class TestActiveFraction(unittest.TestCase):
    def test_fraction_matches_states(self) -> None:
        # _daily_active(): SMA(3,confirm1) is ACTIVE on 01-03..01-05, PAUSED on 01-01/02.
        daily = _daily_active()
        hourly = [_bar(_BASE_MS + i * _DAY_MS, c, c, c, c)
                  for i, c in enumerate([100, 101, 102, 103, 104])]
        frac = active_fraction(hourly, daily, sma_window=3, confirm_bars=1)
        self.assertAlmostEqual(frac, 3 / 5)

    def test_empty_hourly_is_zero(self) -> None:
        self.assertEqual(active_fraction([], _daily_active()), 0.0)


class TestNumeraireInvariance(unittest.TestCase):
    def test_scaling_prices_preserves_returns(self) -> None:
        # ETHBTC-style small-magnitude prices (S1c §2): scale the oscillation fixture
        # down 1000x (BTCUSDT ~100 -> ETHBTC-ish ~0.1) and check percentage results are
        # unchanged -- the harness is ratio-based, so "BTC numeraire" falls out for free.
        def build(scale: float):
            hourly: list[Bar] = []
            ts = _ACTIVE_DAY_MS
            for _ in range(40):
                hourly.append(_bar(ts, 100 * scale, 100.2 * scale, 98.0 * scale, 98.2 * scale))
                ts += 3_600_000
                hourly.append(_bar(ts, 98.2 * scale, 102.0 * scale, 98.0 * scale, 101.8 * scale))
                ts += 3_600_000
            return run_s1(hourly, _daily_active(), step=0.01,
                           lower=95.0 * scale, upper=105.0 * scale,
                           sma_window=3, confirm_bars=1)

        full = build(1.0)
        scaled = build(0.001)  # ETHBTC order of magnitude
        self.assertAlmostEqual(full.grid_total_return, scaled.grid_total_return, places=9)
        self.assertAlmostEqual(full.hold_total_return, scaled.hold_total_return, places=9)
        self.assertAlmostEqual(full.grid_realized_harvest, scaled.grid_realized_harvest, places=9)


# closes for S1e fixtures (window=3, confirm_bars=1, r90_window=3, r90_threshold=0.15):
#   idx 0-3  BELOW   (SMA warm-up / flat)
#   idx 4-5  RANGE   (ACTIVE, r90 < 15%)
#   idx 6-10 UPTREND (ACTIVE, r90 >= 15%)
#   idx 11-12 RANGE  (ACTIVE again, r90 < 15%)
#   idx 13   BELOW   (drops back below SMA)
_S1E_CLOSES = [100, 100, 100, 100, 105, 110, 116, 124, 135, 150, 151, 152, 153, 100]
_S1E_KW = dict(sma_window=3, confirm_bars=1, r90_window=3, r90_threshold=0.15)


def _s1e_daily_bars() -> list[Bar]:
    return [_bar(_BASE_MS + i * _DAY_MS, c, c, c, c) for i, c in enumerate(_S1E_CLOSES)]


class TestS1e(unittest.TestCase):
    def test_pure_uptrend_matches_hold(self) -> None:
        # idx6..9 are all UPTREND: a few hourly bars per day, monotonically rising.
        daily = _s1e_daily_bars()
        hourly: list[Bar] = []
        price = 116.0
        for d in range(4):
            for h in range(3):
                nxt = price * 1.002
                hourly.append(_bar(_BASE_MS + (6 + d) * _DAY_MS + h * 3_600_000,
                                    price, nxt, price * 0.999, nxt))
                price = nxt

        res = run_s1e(hourly, daily, step=0.01, **_S1E_KW)
        self.assertEqual(res.switch_count, 1)  # single entry from the initial BELOW state
        self.assertAlmostEqual(res.grid_minus_hold, 0.0, places=12)
        for g, h in zip(res.grid_curve, res.hold_curve):
            self.assertAlmostEqual(g, h, places=12)

    def test_pure_below_is_zero(self) -> None:
        # idx0..3 are all BELOW: starts (and stays) flat.
        daily = _s1e_daily_bars()
        hourly = [_bar(_BASE_MS + i * _DAY_MS, c, c, c, c) for i, c in enumerate(_S1E_CLOSES[:4])]

        res = run_s1e(hourly, daily, step=0.01, **_S1E_KW)
        self.assertEqual(res.switch_count, 0)
        self.assertEqual(res.grid_total_return, 0.0)
        self.assertEqual(res.hold_total_return, 0.0)
        self.assertEqual(res.range_harvest, 0.0)
        self.assertEqual(res.switch_tax, 0.0)

    def test_switch_counting_and_tax_order_of_magnitude(self) -> None:
        # one flat hourly bar per day for idx4..13: regime sequence
        # RANGE,RANGE,UPTREND*5,RANGE,RANGE,BELOW -> 4 transitions (incl. entry from BELOW).
        daily = _s1e_daily_bars()
        hourly = [_bar(_BASE_MS + i * _DAY_MS, c, c, c, c)
                  for i, c in enumerate(_S1E_CLOSES) if i >= 4]

        taker_fee = 0.0010
        res = run_s1e(hourly, daily, step=0.01, taker_fee=taker_fee, **_S1E_KW)
        self.assertEqual(res.switch_count, 4)
        # equity stays close to 1.0 across small switches -> switch_tax ~ N * taker_fee
        self.assertGreater(res.switch_tax, 0.5 * res.switch_count * taker_fee)
        self.assertLess(res.switch_tax, 3.0 * res.switch_count * taker_fee)

    def test_range_harvest_excludes_uptrend_inventory(self) -> None:
        daily = _s1e_daily_bars()
        # RANGE days idx4-5: oscillate so the seeded grid both sells and re-buys/sells.
        hourly_range = [
            _bar(_BASE_MS + 4 * _DAY_MS + 0 * 3_600_000, 105, 108, 105, 108),
            _bar(_BASE_MS + 4 * _DAY_MS + 1 * 3_600_000, 108, 108, 100, 100),
            _bar(_BASE_MS + 4 * _DAY_MS + 2 * 3_600_000, 100, 108, 100, 108),
            _bar(_BASE_MS + 5 * _DAY_MS, 108, 110, 107, 110),
        ]
        res_range_only = run_s1e(hourly_range, daily, step=0.01, **_S1E_KW)

        # extend with UPTREND days idx6..9 with large appreciation: range_harvest must
        # not change even though the position (now in UPTREND) marks up substantially.
        hourly_extended = list(hourly_range)
        price = 116.0
        for d in range(4):
            nxt = price * 1.05
            hourly_extended.append(_bar(_BASE_MS + (6 + d) * _DAY_MS, price, nxt, price, nxt))
            price = nxt

        res_extended = run_s1e(hourly_extended, daily, step=0.01, **_S1E_KW)
        self.assertGreater(res_extended.grid_total_return, res_range_only.grid_total_return)
        self.assertAlmostEqual(res_extended.range_harvest, res_range_only.range_harvest, places=12)

    def test_hold_above_ma_parity_with_run_s1(self) -> None:
        # same fixture as TestS1Backtest.test_oscillation_harvests_positive
        hourly: list[Bar] = []
        ts = _ACTIVE_DAY_MS
        for _ in range(40):
            hourly.append(_bar(ts, 100, 100.2, 98.0, 98.2))
            ts += 3_600_000
            hourly.append(_bar(ts, 98.2, 102.0, 98.0, 101.8))
            ts += 3_600_000

        daily = _daily_active()
        res1 = run_s1(hourly, daily, step=0.01, lower=95.0, upper=105.0,
                       sma_window=3, confirm_bars=1)
        res2 = run_s1e(hourly, daily, step=0.01, sma_window=3, confirm_bars=1,
                        r90_window=3, r90_threshold=0.15)
        self.assertEqual(res1.hold_curve, res2.hold_curve)

        # also exercise _hold_above_ma directly against the same states
        states = daily_states_by_date(daily, window=3, confirm_bars=1)
        direct = _hold_above_ma(hourly, states, capital=1.0, taker_fee=0.0010)
        self.assertEqual(res1.hold_curve, direct)


class TestTrailingDailyVol(unittest.TestCase):
    def test_no_lookahead(self) -> None:
        base = [100 + (i % 5) for i in range(31)]
        bars_a = [_daily_bar(_dt.date(2021, 1, 1) + _dt.timedelta(days=i), c)
                  for i, c in enumerate(base + [200, 250, 300, 50])]
        bars_b = [_daily_bar(_dt.date(2021, 1, 1) + _dt.timedelta(days=i), c)
                  for i, c in enumerate(base + [10, 5, 1, 0.5])]

        vol_a = _trailing_daily_vol(bars_a, window=30)
        vol_b = _trailing_daily_vol(bars_b, window=30)
        date30 = bars_a[30].date
        self.assertEqual(bars_b[30].date, date30)
        self.assertIsNotNone(vol_a[date30])
        self.assertAlmostEqual(vol_a[date30], vol_b[date30], places=12)

    def test_warmup_is_none(self) -> None:
        bars = [_daily_bar(_dt.date(2021, 1, 1) + _dt.timedelta(days=i), 100.0 + i)
                for i in range(29)]
        vol = _trailing_daily_vol(bars, window=30)
        self.assertIsNone(vol[bars[-1].date])


class TestSeedRangeLadder(unittest.TestCase):
    def test_seeds_half_position_and_brackets_center(self) -> None:
        ladder, lo, hi, seed_phantom = _seed_range_ladder(
            100.0, 0.01, z=2.0, horizon_days=90, step=0.01, maker_fee=0.00075, capital=1.0)
        self.assertLess(lo, 100.0)
        self.assertGreater(hi, 100.0)
        for k in range(ladder.spec.n):
            self.assertEqual(ladder.cells[k].holding, ladder.spec.prices[k] <= 100.0)
        n_holding = sum(1 for c in ladder.cells if c.holding)
        self.assertGreater(n_holding, 0)
        self.assertLess(n_holding, ladder.spec.n)
        # every seeded (holding) cell has a non-negative phantom-gain entry, since its
        # cost basis P_k <= center
        self.assertEqual(set(seed_phantom.keys()), {k for k in range(ladder.spec.n) if ladder.cells[k].holding})
        for phantom in seed_phantom.values():
            self.assertGreaterEqual(phantom, 0.0)


if __name__ == "__main__":
    unittest.main()
