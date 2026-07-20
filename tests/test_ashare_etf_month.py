from __future__ import annotations

import datetime as dt
import tempfile
import unittest

from qount.ashare_etf_month import AI_APPLICATION
from qount.ashare_etf_month import AI_CORE
from qount.ashare_etf_month import AI_HARDWARE
from qount.ashare_etf_month import BENCHMARK
from qount.ashare_etf_month import DailyBar
from qount.ashare_etf_month import ETF_META
from qount.ashare_etf_month import _episode_result
from qount.ashare_etf_month import align_bars
from qount.ashare_etf_month import build_month_report
from qount.ashare_etf_month import build_execution_plan
from qount.ashare_etf_month import classify_ai_regime
from qount.ashare_etf_month import compute_snapshot
from qount.ashare_etf_month import fetch_tushare_bars
from qount.ashare_etf_month import load_universe_bars
from qount.ashare_etf_month import parse_eastmoney_bars
from qount.ashare_etf_month import parse_tencent_bars
from qount.ashare_etf_month import write_bars_cache


def _dates(count: int) -> list[str]:
    start = dt.date(2024, 1, 1)
    return [(start + dt.timedelta(days=index)).isoformat() for index in range(count)]


def _bars(values: list[float]) -> list[DailyBar]:
    return [
        DailyBar(
            date=date,
            open=value * 0.999,
            high=value * 1.01,
            low=value * 0.99,
            close=value,
            volume=1_000_000.0,
            amount=10_000_000.0,
        )
        for date, value in zip(_dates(len(values)), values, strict=True)
    ]


def _trend(count: int, start: float, daily: float) -> list[float]:
    return [start * ((1.0 + daily) ** index) for index in range(count)]


class TushareAdapterTest(unittest.TestCase):
    def test_adjusts_ohlc_and_never_returns_token(self) -> None:
        requests = []

        def poster(_url, payload):
            requests.append(payload)
            if payload["api_name"] == "fund_daily":
                return {
                    "code": 0,
                    "data": {
                        "fields": ["trade_date", "open", "high", "low", "close", "vol", "amount"],
                        "items": [
                            ["20240103", 20.0, 22.0, 19.0, 21.0, 100.0, 200.0],
                            ["20240102", 10.0, 11.0, 9.0, 10.5, 90.0, 180.0],
                        ],
                    },
                }
            return {
                "code": 0,
                "data": {
                    "fields": ["trade_date", "adj_factor"],
                    "items": [["20240103", 2.0], ["20240102", 1.0]],
                },
            }

        bars = fetch_tushare_bars(
            "510300.SH",
            token="secret-token",
            start_date="2024-01-01",
            end_date="2024-01-03",
            poster=poster,
        )
        self.assertEqual([bar.date for bar in bars], ["2024-01-02", "2024-01-03"])
        self.assertAlmostEqual(bars[0].close, 5.25)
        self.assertAlmostEqual(bars[1].close, 21.0)
        self.assertEqual({request["token"] for request in requests}, {"secret-token"})
        self.assertNotIn("secret-token", repr(bars))

    def test_parses_eastmoney_qfq_fields(self) -> None:
        payload = {
            "data": {
                "klines": [
                    "2026-07-15,1.325,1.232,1.327,1.226,176,222,7.72,-5.81,-0.076,9.53",
                    "2026-07-16,1.191,1.159,1.235,1.150,152,180,6.90,-5.93,-0.073,8.23",
                ]
            }
        }
        bars = parse_eastmoney_bars(payload, "512480.SH")
        self.assertEqual(bars[-1].date, "2026-07-16")
        self.assertAlmostEqual(bars[-1].open, 1.191)
        self.assertAlmostEqual(bars[-1].close, 1.159)

    def test_parses_tencent_qfq_fields(self) -> None:
        payload = {
            "data": {
                "sh512480": {
                    "qfqday": [
                        ["2026-07-15", "1.325", "1.232", "1.327", "1.226", "176"],
                        ["2026-07-16", "1.191", "1.159", "1.235", "1.150", "152"],
                    ]
                }
            }
        }
        bars = parse_tencent_bars(payload, "512480.SH")
        self.assertEqual(bars[-1].date, "2026-07-16")
        self.assertAlmostEqual(bars[-1].open, 1.191)
        self.assertAlmostEqual(bars[-1].close, 1.159)
        self.assertEqual(bars[-1].amount, bars[-1].volume)

    def test_stale_cache_refreshes_but_current_cache_is_reused(self) -> None:
        values = _trend(160, 1.0, 0.001)
        bars = _bars(values)
        rows = [
            [bar.date, str(bar.open), str(bar.close), str(bar.high), str(bar.low), str(bar.volume)]
            for bar in bars
        ]
        calls = []

        def getter(url):
            calls.append(url)
            return {"data": {"sh510300": {"qfqday": rows}}}

        with tempfile.TemporaryDirectory() as tmp:
            write_bars_cache(tmp, "tencent", "510300.SH", bars[:-1])
            loaded = load_universe_bars(
                source="tencent",
                start_date=bars[0].date,
                end_date=bars[-1].date,
                cache_dir=tmp,
                symbols=["510300.SH"],
                eastmoney_getter=getter,
            )
            self.assertEqual(len(loaded["510300.SH"]), 160)
            self.assertEqual(len(calls), 1)

            loaded_again = load_universe_bars(
                source="tencent",
                start_date=bars[0].date,
                end_date=bars[-1].date,
                cache_dir=tmp,
                symbols=["510300.SH"],
                eastmoney_getter=getter,
            )
            self.assertEqual(len(loaded_again["510300.SH"]), 160)
            self.assertEqual(len(calls), 1)


class RegimeTest(unittest.TestCase):
    def test_distinguishes_hardware_pullback_from_ai_breakdown(self) -> None:
        count = 180
        market = _trend(count, 1.0, 0.0004)
        panel = {symbol: _bars(_trend(count, 1.0, 0.0005)) for symbol in ETF_META}
        panel[BENCHMARK] = _bars(market)
        panel[AI_CORE] = _bars(_trend(count, 1.0, 0.0010))
        # The application proxy stays decisively strong versus the market while hardware
        # suffers a sharp ten-session selloff.
        panel[AI_APPLICATION] = _bars(_trend(count, 1.0, 0.0040))
        for symbol in AI_HARDWARE:
            values = _trend(count, 1.0, 0.0010)
            peak = values[-11]
            for offset in range(10):
                values[-10 + offset] = peak * (0.985 ** (offset + 1))
            panel[symbol] = _bars(values)
        dates, aligned = align_bars(panel)
        snapshot = compute_snapshot(dates, aligned, len(dates) - 1)
        regime = classify_ai_regime(snapshot)
        self.assertEqual(regime["label"], "hardware_pullback_application_rotation")
        self.assertTrue(regime["tests"]["secular_ai_intact"])
        self.assertFalse(regime["tests"]["broad_ai_weak"])

    def test_labels_broad_long_and_short_term_breakdown(self) -> None:
        count = 220
        flat = _trend(count, 1.0, 0.0001)
        panel = {symbol: _bars(flat) for symbol in ETF_META}
        panel[BENCHMARK] = _bars(flat)
        for symbol in (*AI_HARDWARE, AI_CORE, AI_APPLICATION):
            values = _trend(count, 1.0, 0.0008)
            peak = values[-91]
            for offset in range(90):
                values[-90 + offset] = peak * (0.995 ** (offset + 1))
            panel[symbol] = _bars(values)
        dates, aligned = align_bars(panel)
        regime = classify_ai_regime(compute_snapshot(dates, aligned, len(dates) - 1))
        self.assertEqual(regime["label"], "ai_logic_breakdown")
        self.assertTrue(regime["tests"]["broad_ai_weak"])
        self.assertTrue(regime["tests"]["broad_relative_breakdown"])


class PortfolioEvaluationTest(unittest.TestCase):
    def test_episode_uses_next_open_and_two_sided_cost(self) -> None:
        panel = {
            symbol: [
                DailyBar(str(index), 100.0, 111.0, 99.0, 100.0 if index < 2 else 110.0)
                for index in range(4)
            ]
            for symbol in ETF_META
        }
        result = _episode_result(
            panel,
            {"510300.SH": 0.50},
            signal_index=0,
            horizon_days=2,
            cost_per_side_bps=10.0,
        )
        self.assertAlmostEqual(result["gross_return"], 0.05)
        self.assertAlmostEqual(result["net_return"], 0.049)

    def test_full_report_is_research_only_and_has_no_order_effect(self) -> None:
        count = 420
        panel = {
            symbol: _bars(_trend(count, 1.0 + i * 0.1, 0.0002 + i * 0.00001))
            for i, symbol in enumerate(ETF_META)
        }
        report = build_month_report(panel, data_source="fixture")
        self.assertEqual(report["research_status"], "discovery_only_no_profit_guarantee")
        self.assertFalse(report["decision_contract"]["order_or_live_side_effects"])
        self.assertIn(report["recommendation"]["portfolio"], report["portfolio_evaluation"]["portfolios"])
        self.assertIn("instructions", report["execution"])
        effective = sum(
            row["target_weight"] for row in report["execution"]["instructions"].values()
        )
        self.assertAlmostEqual(effective, report["recommendation"]["initial_exposure_cap"])
        self.assertAlmostEqual(report["execution"]["target_cash_weight"], 1.0 - effective)
        rotation = build_execution_plan(
            report["snapshot"], "rotation_barbell", exposure_cap=0.375
        )
        self.assertGreaterEqual(
            rotation["instructions"]["159928.SZ"]["full_trigger_close"], 0.670
        )


if __name__ == "__main__":
    unittest.main()
