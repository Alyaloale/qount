from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from qount.research_data.market_data import Bar
from qount.mini_trend.forward import FROZEN_TOP3_FORWARD_PROTOCOL
from qount.mini_trend.forward import MINI_TREND_FORWARD_PREREG_VERSION
from qount.mini_trend.forward import MINI_TREND_FORWARD_VERSION
from qount.mini_trend.forward import TOP3
from qount.mini_trend.forward import build_forward_preregistration
from qount.mini_trend.forward import build_forward_report
from qount.mini_trend.forward import frozen_top3_config
from qount.mini_trend.forward import load_anchor_evidence


def _rules() -> dict:
    return {
        "market": "spot",
        "source_type": "runtime_exchange_info",
        "raw_exchange_info_hash": "raw",
        "rules": [
            {
                "symbol": symbol,
                "status": "TRADING",
                "step_size": "0.00001",
                "market_step_size": "0",
                "min_qty": "0.00001",
                "min_notional": "5",
            }
            for symbol in TOP3
        ],
    }


def _bars(multiplier: float) -> list[Bar]:
    start = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    rows = []
    for index in range(570):
        close = multiplier * (100.0 + index * 0.25)
        ts_ms = int((start + dt.timedelta(days=index)).timestamp() * 1000)
        rows.append(
            Bar(
                ts_ms=ts_ms,
                open=close * 0.999,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=1000.0,
            )
        )
    return rows


class MiniTrendForwardTest(unittest.TestCase):
    def _anchor(self, root: Path, bars: dict[str, list[Bar]]) -> dict:
        from qount.mini_trend.backtest import run_backtest, write_backtest_artifact

        cutoff = int(dt.datetime(2026, 7, 1, tzinfo=dt.UTC).timestamp() * 1000)
        anchor_bars = {symbol: [bar for bar in rows if bar.ts_ms < cutoff] for symbol, rows in bars.items()}
        result = run_backtest(anchor_bars, frozen_top3_config())
        write_backtest_artifact(result, root)
        return load_anchor_evidence(root)

    def test_preregistration_freezes_low_frequency_contract(self) -> None:
        bars = {"BTCUSDT": _bars(1.0), "ETHUSDT": _bars(0.5), "BNBUSDT": _bars(0.2)}
        with tempfile.TemporaryDirectory() as tmp:
            anchor = self._anchor(Path(tmp), bars)
            prereg = build_forward_preregistration(_rules(), anchor)
        self.assertEqual(prereg["schema_version"], MINI_TREND_FORWARD_PREREG_VERSION)
        self.assertFalse(prereg["meta"]["strategy_results_evaluated"])
        self.assertTrue(prereg["meta"]["low_frequency_only"])
        self.assertFalse(prereg["protocol"]["high_frequency_data_allowed"])
        self.assertEqual(
            prereg["decision_contract"]["contract_hash"],
            FROZEN_TOP3_FORWARD_PROTOCOL.contract_hash,
        )

    def test_forward_report_is_collect_only_before_horizon(self) -> None:
        bars = {"BTCUSDT": _bars(1.0), "ETHUSDT": _bars(0.5), "BNBUSDT": _bars(0.2)}
        with tempfile.TemporaryDirectory() as tmp:
            anchor = self._anchor(Path(tmp), bars)
            prereg = build_forward_preregistration(_rules(), anchor)
            report = build_forward_report(bars, _rules(), prereg, anchor)
        self.assertEqual(report["schema_version"], MINI_TREND_FORWARD_VERSION)
        self.assertEqual(report["diagnostics"]["verdict"], "collect_forward")
        self.assertFalse(report["diagnostics"]["paper_review_allowed"])
        self.assertFalse(report["diagnostics"]["high_frequency_used"])
        self.assertTrue(report["anchor"]["parity_pass"])
        self.assertGreater(report["data"]["evaluation_bar_count"], 0)
        self.assertEqual(report["data"]["evaluation_gap_count"], 0)

    def test_rules_or_anchor_mismatch_fails_closed(self) -> None:
        bars = {"BTCUSDT": _bars(1.0), "ETHUSDT": _bars(0.5), "BNBUSDT": _bars(0.2)}
        with tempfile.TemporaryDirectory() as tmp:
            anchor = self._anchor(Path(tmp), bars)
            prereg = build_forward_preregistration(_rules(), anchor)
            changed = json.loads(json.dumps(_rules()))
            changed["rules"][0]["min_notional"] = "10"
            with self.assertRaisesRegex(ValueError, "exchange-rules hash mismatch"):
                build_forward_report(bars, changed, prereg, anchor)
            changed_anchor = dict(anchor)
            changed_anchor["summary_sha256"] = "changed"
            with self.assertRaisesRegex(ValueError, "anchor summary_sha256 mismatch"):
                build_forward_report(bars, _rules(), prereg, changed_anchor)

    def test_expected_end_detects_common_tail_truncation(self) -> None:
        bars = {"BTCUSDT": _bars(1.0), "ETHUSDT": _bars(0.5), "BNBUSDT": _bars(0.2)}
        with tempfile.TemporaryDirectory() as tmp:
            anchor = self._anchor(Path(tmp), bars)
            prereg = build_forward_preregistration(_rules(), anchor)
            actual_end = dt.date.fromisoformat(bars["BTCUSDT"][-1].date)
            report = build_forward_report(
                bars,
                _rules(),
                prereg,
                anchor,
                expected_end_date=(actual_end + dt.timedelta(days=1)).isoformat(),
            )
        self.assertFalse(report["diagnostics"]["gates"]["data_complete"])
        self.assertEqual(report["data"]["evaluation_gap_count"], 1)

    def test_anchor_config_is_exact_frozen_config(self) -> None:
        self.assertEqual(asdict(frozen_top3_config())["universe"], TOP3)
        self.assertEqual(frozen_top3_config().market, "spot")
        self.assertEqual(frozen_top3_config().direction, "long_cash")


if __name__ == "__main__":
    unittest.main()
