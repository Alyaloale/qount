from __future__ import annotations

import datetime as dt
import unittest

from qount.grid.data import Bar
from qount.mini_trend.capitulation_rebound import CAPITULATION_REBOUND_PROTOCOL
from qount.mini_trend.capitulation_rebound import _signal_state
from qount.mini_trend.capitulation_rebound import _symbol_outcome
from qount.mini_trend.capitulation_rebound import build_capitulation_price_report
from qount.mini_trend.capitulation_rebound import build_capitulation_preregistration
from qount.mini_trend.forward import TOP3


_DAY_MS = 86_400_000
_START_MS = int(dt.datetime(2021, 1, 1, tzinfo=dt.UTC).timestamp() * 1000)


def _prices(*, rebound: float = 0.03) -> list[float]:
    values = [200.0]
    for _ in range(229):
        values.append(values[-1] * 0.999)
    for _ in range(5):
        values.append(values[-1] * 0.98)
    for _ in range(12):
        values.append(values[-1] * (1.0 + rebound))
    return values


def _series(*, rebound: float = 0.03, stop_on_entry: bool = False) -> list[Bar]:
    closes = _prices(rebound=rebound)
    rows: list[Bar] = []
    for index, close in enumerate(closes):
        open_price = closes[index - 1] if index else close
        low = min(open_price, close) * 0.995
        if stop_on_entry and index == 235:
            low = open_price * 0.70
        rows.append(
            Bar(
                ts_ms=_START_MS + index * _DAY_MS,
                open=open_price,
                high=max(open_price, close) * 1.005,
                low=low,
                close=close,
                volume=1_000.0,
                quote_volume=1_000_000.0,
            )
        )
    return rows


def _bars(**kwargs) -> dict[str, list[Bar]]:
    return {symbol: _series(**kwargs) for symbol in TOP3}


class MiniTrendCapitulationReboundTests(unittest.TestCase):
    def test_preregistration_freezes_price_only_non_promotable_trial(self) -> None:
        payload = build_capitulation_preregistration()
        signal = payload["decision_contract"]["signal"]
        self.assertEqual(signal["maximum_median_return"], -0.08)
        self.assertEqual(signal["maximum_volatility_score"], -1.5)
        self.assertFalse(signal["parameter_search_allowed"])
        self.assertFalse(payload["meta"]["strategy_results_evaluated"])
        self.assertTrue(
            payload["protocol"]["funding_complete_replay_required_before_standalone_nav"]
        )
        self.assertFalse(payload["protocol"]["paper_or_live_allowed"])

    def test_signal_uses_only_completed_data_and_enters_next_bar(self) -> None:
        preregistration = build_capitulation_preregistration()
        positive = build_capitulation_price_report(_bars(rebound=0.03), preregistration)
        negative = build_capitulation_price_report(_bars(rebound=-0.03), preregistration)
        self.assertEqual(positive["summary"]["independent_episode_count"], 1)
        self.assertGreaterEqual(negative["summary"]["independent_episode_count"], 1)
        first = positive["episodes"][0]
        other = negative["episodes"][0]
        self.assertEqual(first["signal_date"], other["signal_date"])
        self.assertEqual(first["signal"], other["signal"])
        self.assertGreater(first["entry_date"], first["signal_date"])
        self.assertGreater(first["net_return"], 0.0)
        self.assertLess(other["net_return"], 0.0)

    def test_base_gate_on_blocks_an_extreme_selloff(self) -> None:
        bars = _bars()
        index = 234
        for symbol in TOP3:
            for offset in range(200):
                row = bars[symbol][offset]
                bars[symbol][offset] = Bar(
                    row.ts_ms,
                    row.open * 0.25,
                    row.high * 0.25,
                    row.low * 0.25,
                    row.close * 0.25,
                    row.volume,
                    row.quote_volume,
                )
        state = _signal_state(bars, index, CAPITULATION_REBOUND_PROTOCOL)
        self.assertTrue(state["base_gate_on"])
        self.assertFalse(state["triggered"])

    def test_fixed_atr_stop_is_conservative_on_intraday_breach(self) -> None:
        bars = _series(stop_on_entry=True)
        outcome = _symbol_outcome(bars, 234, CAPITULATION_REBOUND_PROTOCOL)
        self.assertTrue(outcome["stopped"])
        self.assertEqual(outcome["exit_index"], 235)
        self.assertLess(outcome["net_return"], 0.0)


if __name__ == "__main__":
    unittest.main()
