"""Unit tests for RV-C basis primitives (线 C, isolated). Plan: ``docs/archive/legacy/x4-rv/rv-c-plan.md`` §2/§4.

Covers the StatArb命门: annualized basis math, point-in-time roll selection (no look-ahead),
splicing + roll flags, and expiry convergence reconciliation (the hard anchor).
"""

from __future__ import annotations

import unittest

from qount.research_data.market_data import Bar
from qount.legacy.rv_c.basis import ActiveBar
from qount.legacy.rv_c.basis import active_expiry
from qount.legacy.rv_c.basis import annualized_basis
from qount.legacy.rv_c.basis import build_active_series
from qount.legacy.rv_c.basis import raw_basis

_DAY_MS = 86_400_000
_T0 = 1_609_459_200_000  # 2021-01-01 00:00 UTC


def _bar(ts: int, close: float, *, high: float | None = None, open_: float | None = None) -> Bar:
    o = close if open_ is None else open_
    h = max(o, close) if high is None else high
    return Bar(ts_ms=ts, open=o, high=h, low=min(o, close), close=close, volume=1.0)


class TestAnnualizedBasis(unittest.TestCase):
    def test_quarter_contango(self) -> None:
        # 5% premium over 91.25 days (a quarter) annualizes to ~20%.
        ann = annualized_basis(100.0, 105.0, 91.25)
        self.assertAlmostEqual(ann, 0.05 * (365.0 / 91.25))
        self.assertAlmostEqual(ann, 0.20)

    def test_backwardation_negative(self) -> None:
        self.assertLess(annualized_basis(100.0, 98.0, 30.0), 0.0)

    def test_at_or_after_expiry_zero(self) -> None:
        # convergence is forced at expiry; un-annualizable -> 0, not a blow-up.
        self.assertEqual(annualized_basis(100.0, 100.0, 0.0), 0.0)
        self.assertEqual(annualized_basis(100.0, 101.0, -3.0), 0.0)

    def test_raw_basis_converges_at_expiry(self) -> None:
        # the anchor: at settlement F≡S so raw basis ~ 0 (杀手 1 immunity).
        self.assertAlmostEqual(raw_basis(100.0, 100.0), 0.0)

    def test_bad_spot_raises(self) -> None:
        with self.assertRaises(ValueError):
            annualized_basis(0.0, 100.0, 30.0)


class TestRollSelection(unittest.TestCase):
    def setUp(self) -> None:
        # three quarterly expiries 90 days apart
        self.expiries = [_T0 + 90 * _DAY_MS, _T0 + 180 * _DAY_MS, _T0 + 270 * _DAY_MS]

    def test_picks_nearest_beyond_buffer(self) -> None:
        # well before any expiry -> hold the nearest (first)
        self.assertEqual(active_expiry(_T0, self.expiries, 5.0), self.expiries[0])

    def test_rolls_when_within_buffer(self) -> None:
        # 3 days before the first expiry (< 5-day buffer) -> roll to the second
        ts = self.expiries[0] - 3 * _DAY_MS
        self.assertEqual(active_expiry(ts, self.expiries, 5.0), self.expiries[1])

    def test_none_past_end(self) -> None:
        ts = self.expiries[-1] - 2 * _DAY_MS  # inside buffer of the last, nothing further
        self.assertIsNone(active_expiry(ts, self.expiries, 5.0))

    def test_point_in_time_no_lookahead(self) -> None:
        # selection depends only on ts + calendar (+ optional listing), never on a future price.
        # a contract not yet listed at ts is skipped to the next listed one.
        listed = {self.expiries[1]: {_T0}}  # only the 2nd contract trades at _T0
        chosen = active_expiry(
            _T0, self.expiries, 5.0, is_listed=lambda e, ts: ts in listed.get(e, {})
        )
        self.assertEqual(chosen, self.expiries[1])


class TestBuildActiveSeries(unittest.TestCase):
    def test_splices_and_flags_roll(self) -> None:
        e1 = _T0 + 30 * _DAY_MS
        e2 = _T0 + 120 * _DAY_MS
        # spot bars daily for ~40 days; roll out of e1 ~5 days before it (buffer=5)
        spot = [_bar(_T0 + d * _DAY_MS, 100.0) for d in range(40)]
        c1 = [_bar(_T0 + d * _DAY_MS, 101.0) for d in range(40)]   # near contract
        c2 = [_bar(_T0 + d * _DAY_MS, 103.0) for d in range(40)]   # far contract
        active = build_active_series(spot, {e1: c1, e2: c2}, roll_buffer_days=5.0)
        self.assertEqual(len(active), 40)
        # first bars on e1
        self.assertEqual(active[0].expiry_ms, e1)
        self.assertFalse(active[0].is_roll)
        rolls = [i for i, ab in enumerate(active) if ab.is_roll]
        self.assertEqual(len(rolls), 1)  # exactly one contract change
        roll_i = rolls[0]
        # roll happens ~5 days before e1 (day 30 - 5 = day 25)
        self.assertEqual(active[roll_i].expiry_ms, e2)
        self.assertEqual(active[roll_i - 1].expiry_ms, e1)

    def test_drops_bars_without_tradeable_contract(self) -> None:
        e1 = _T0 + 60 * _DAY_MS
        spot = [_bar(_T0 + d * _DAY_MS, 100.0) for d in range(10)]
        # contract only has bars for days 5..9 -> days 0..4 are dropped (not yet listed)
        c1 = [_bar(_T0 + d * _DAY_MS, 101.0) for d in range(5, 10)]
        active = build_active_series(spot, {e1: c1}, roll_buffer_days=5.0)
        self.assertEqual(len(active), 5)
        self.assertEqual(active[0].spot.ts_ms, _T0 + 5 * _DAY_MS)

    def test_activebar_basis_props(self) -> None:
        e = _T0 + 100 * _DAY_MS
        ab = ActiveBar(spot=_bar(_T0, 100.0), dated=_bar(_T0, 105.0), expiry_ms=e, is_roll=False)
        self.assertAlmostEqual(ab.days_to_expiry, 100.0)
        self.assertAlmostEqual(ab.annualized_basis, 0.05 * (365.0 / 100.0))


if __name__ == "__main__":
    unittest.main()
