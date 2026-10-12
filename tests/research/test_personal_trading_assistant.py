"""Unit tests for Personal Trading Assistant & Core ETF Baseline Kernel."""
from pathlib import Path
import unittest

from qount.research.personal_trading_assistant import (
    AssistantBar,
    CORE_ETF_UNIVERSE,
    ETFAssetMeta,
    PersonalTradingAssistantKernel,
    format_daily_report_markdown,
    generate_deterministic_daily_report,
)


class TestPersonalTradingAssistant(unittest.TestCase):
    def setUp(self):
        self.kernel = PersonalTradingAssistantKernel(cash_apr=0.02, initial_capital=100_000.0)
        self.meta = ETFAssetMeta(
            symbol="TEST_ETF",
            name="测试ETF",
            tracking_target="测试指数",
            listing_date="20230105",  # Listed on day 5
            is_index_proxy=False,
            annual_expense_ratio=0.005,
            commission_bps=6.0,
            slippage_bps=5.0,
        )

    def test_listing_date_constraint(self):
        """Invariant: Simulators must reject/filter bars prior to official listing date."""
        # 10 bars from 20230101 to 20230110
        bars = [
            AssistantBar(f"202301{i+1:02d}", 10.0, 10.5, 9.5, 10.0)
            for i in range(10)
        ]
        # B&H should start strictly on listing date 20230105
        nav, metrics = self.kernel.simulate_buy_and_hold(bars, self.meta)
        self.assertEqual(metrics.start_date, "20230105")
        self.assertEqual(metrics.trading_days, 6)

    def test_causal_execution_timing(self):
        """Invariant: Breakout on Close(T) must be filled strictly on Open(T+1)."""
        # Bars with listing on 20230101
        meta = ETFAssetMeta("TEST2", "测试2", "测试", "20230101", False, 0.005, 0.0, 0.0)
        # 10 bars: first 5 flat at 10.0, bar 6 closes at 15.0 (breakout), bar 7 open at 15.0
        bars = [
            AssistantBar("20230101", 10.0, 10.0, 10.0, 10.0),
            AssistantBar("20230102", 10.0, 10.0, 10.0, 10.0),
            AssistantBar("20230103", 10.0, 10.0, 10.0, 10.0),
            AssistantBar("20230104", 10.0, 10.0, 10.0, 10.0),
            AssistantBar("20230105", 10.0, 10.0, 10.0, 10.0),
            AssistantBar("20230106", 12.0, 15.0, 12.0, 15.0),  # Breakout on close!
            AssistantBar("20230107", 15.0, 15.0, 15.0, 15.0),  # Open execution here!
            AssistantBar("20230108", 15.0, 15.0, 15.0, 15.0),
        ]
        # MA period = 3, confirm = 1, band = 0
        nav, metrics = self.kernel.simulate_trend_timing(bars, meta, ma_period=3, band_pct=0.0, confirm_days=1)
        self.assertGreater(metrics.trade_count, 0)
        self.assertGreater(metrics.terminal_equity, 100_000.0)

    def test_pure_cash_compounding(self):
        """Invariant: Pure cash control must compound at exactly cash_apr with zero drawdown."""
        meta = ETFAssetMeta("CASH", "现金", "现金", "20230101", False, 0.0, 0.0, 0.0)
        bars = [AssistantBar(f"202301{i+1:02d}", 10.0, 10.0, 10.0, 10.0) for i in range(252)]
        nav, metrics = self.kernel.simulate_pure_cash(bars, meta)
        expected_terminal = 100_000.0 * (1.0 + 0.02)
        self.assertAlmostEqual(metrics.terminal_equity, expected_terminal, delta=50.0)
        self.assertEqual(metrics.max_drawdown_pct, 0.0)
        self.assertEqual(metrics.trade_count, 0)

    def test_hysteresis_buffer_prevents_whipsaw(self):
        """Invariant: Hysteresis deadband prevents oscillation around MA."""
        meta = ETFAssetMeta("WHIP", "防抖", "测试", "20230101", False, 0.0, 0.0, 0.0)
        # Steady uptrend followed by small ±0.5% oscillation around MA
        # With band_pct=0.015 (1.5%), small 0.5% fluctuation must NOT trigger sell
        bars = [AssistantBar(f"202301{i+1:02d}", 10.0 + 0.1 * i, 10.0 + 0.1 * i, 10.0 + 0.1 * i, 10.0 + 0.1 * i) for i in range(20)]
        # Add 5 fluctuating bars that stay within 1.5% band
        last_p = 10.0 + 0.1 * 19
        for j in range(5):
            p = last_p * (1.0 - 0.005 if j % 2 == 0 else 1.0 + 0.005)
            bars.append(AssistantBar(f"202302{j+1:02d}", p, p, p, p))

        nav, metrics = self.kernel.simulate_trend_timing(bars, meta, ma_period=10, band_pct=0.015, confirm_days=2)
        # Should buy once and not whip back and forth
        self.assertEqual(metrics.trade_count, 1)

    def test_daily_status_safety_boundary(self):
        """Invariant: Daily status report strictly enforces orders_authorized=False."""
        bars = [AssistantBar(f"202301{i+1:02d}", 10.0, 10.0, 10.0, 10.0) for i in range(130)]
        meta = CORE_ETF_UNIVERSE["513100.SH"]
        status = self.kernel.evaluate_daily_status(bars, meta, ma_period=120)
        self.assertTrue(status.safety_boundary["research_only"])
        self.assertFalse(status.safety_boundary["orders_authorized"])
        self.assertFalse(status.safety_boundary["promotion_evidence"])
        self.assertIn("MA120", status.reason)

    def test_corporate_action_split_continuity(self):
        """Invariant: 1:5 stock split must preserve equity continuity without artificial 80% drawdown."""
        from qount.research.personal_trading_assistant import CorporateAction
        meta = ETFAssetMeta(
            symbol="SPLIT_ETF",
            name="拆分ETF",
            tracking_target="拆分指数",
            listing_date="20220101",
            is_index_proxy=False,
            annual_expense_ratio=0.005,
            commission_bps=0.0,
            slippage_bps=0.0,
            corporate_actions=(CorporateAction(ex_date="20220105", split_ratio=5.0, note="1:5拆分"),),
        )
        # 7 bars: before split close is 5.0, after split close is 1.0 (economic return is 0%)
        bars = [
            AssistantBar("20220101", 5.0, 5.0, 5.0, 5.0),
            AssistantBar("20220102", 5.0, 5.0, 5.0, 5.0),
            AssistantBar("20220103", 5.0, 5.0, 5.0, 5.0),
            AssistantBar("20220104", 5.0, 5.0, 5.0, 5.0),
            AssistantBar("20220105", 1.0, 1.0, 1.0, 1.0),
            AssistantBar("20220106", 1.0, 1.0, 1.0, 1.0),
            AssistantBar("20220107", 1.0, 1.0, 1.0, 1.0),
        ]
        nav, metrics = self.kernel.simulate_buy_and_hold(bars, meta)
        # Without adjustment, terminal equity would drop from 100k to 20k (80% drawdown)
        # With adjustment, terminal equity is exactly 100,000 and max drawdown is 0%
        self.assertAlmostEqual(metrics.terminal_equity, 100_000.0, delta=1.0)
        self.assertAlmostEqual(metrics.max_drawdown_pct, 0.0, delta=0.01)

    def test_validate_bars_rejects_duplicate_dates(self):
        """Invariant: Input validator must reject duplicate trade dates with ValueError."""
        bars = [
            AssistantBar("20230101", 10.0, 10.0, 10.0, 10.0),
            AssistantBar("20230102", 10.0, 10.0, 10.0, 10.0),
            AssistantBar("20230102", 10.0, 10.0, 10.0, 10.0),  # Duplicate!
        ]
        with self.assertRaises(ValueError):
            self.kernel.simulate_buy_and_hold(bars, self.meta)

    def test_unified_state_machine_confirmation(self):
        """Invariant: Daily evaluation and backtest share identical confirmation and target rules."""
        # 130 flat bars at 10.0
        dates = [f"2023{i//28+1:02d}{i%28+1:02d}" for i in range(130)]
        flat_bars = [AssistantBar(d, 10.0, 10.0, 10.0, 10.0) for d in dates]
        meta = ETFAssetMeta("TEST_SM", "测试状态机", "测试", dates[0], False, 0.0, 0.0, 0.0)

        # In deadband, target_weight must be strictly 0.0 (never 0.5!)
        status_flat = self.kernel.evaluate_daily_status(flat_bars, meta, ma_period=120, band_pct=0.015, confirm_days=2)
        self.assertEqual(status_flat.target_weight, 0.0)
        self.assertEqual(status_flat.regime, "TRANSITION_DEADBAND")

        # Breakout day 1 (confirm progress 1/2): target_weight must remain 0.0 until confirmed!
        breakout_day1 = flat_bars[:-1] + [AssistantBar(dates[-1], 10.0, 20.0, 10.0, 20.0)]
        status_d1 = self.kernel.evaluate_daily_status(breakout_day1, meta, ma_period=120, band_pct=0.015, confirm_days=2)
        self.assertEqual(status_d1.target_weight, 0.0)
        self.assertEqual(status_d1.confirm_count, 1)
        self.assertEqual(status_d1.regime, "BULLISH_CONFIRMING")

        # Breakout day 2 (confirm completed): target_weight becomes 1.0
        breakout_day2 = breakout_day1 + [AssistantBar("20240101", 20.0, 20.0, 20.0, 20.0)]
        status_d2 = self.kernel.evaluate_daily_status(breakout_day2, meta, ma_period=120, band_pct=0.015, confirm_days=2)
        self.assertEqual(status_d2.target_weight, 1.0)
        self.assertEqual(status_d2.regime, "BULLISH_HOLD")

    def test_turnover_separation_and_cash_calmar(self):
        """Invariant: Baseline metrics distinguish 252 vs calendar CAGR and one-sided vs two-sided turnover."""
        bars = [AssistantBar(f"2023{i//28+1:02d}{i%28+1:02d}", 10.0, 10.0, 10.0, 10.0) for i in range(125)]
        meta = ETFAssetMeta("TEST_CASH", "现金", "测试", bars[0].trade_date, False, 0.0, 0.0, 0.0)
        _, m_cash = self.kernel.simulate_pure_cash(bars, meta)
        self.assertIsNone(m_cash.calmar_ratio, "Cash Calmar must be None, not 99.0")
        self.assertIsNone(m_cash.win_rate_pct, "Cash win rate must be None, not 100.0")
        self.assertGreater(m_cash.calendar_years, 0.0)
        self.assertGreater(m_cash.cagr_252_pct, 0.0)


    def test_validate_bars_rejects_inconsistent_ohlc(self):
        """Invariant: validate_bars must reject bars with open/close outside low-high range."""
        bars = [
            AssistantBar("20230101", 10.0, 9.0, 8.0, 8.5),  # open 10.0 > high 9.0!
        ]
        with self.assertRaises(ValueError):
            self.kernel.simulate_buy_and_hold(bars, self.meta)

    def test_daily_status_rejects_stale_data(self):
        """Invariant: Stale data gate must set is_actionable=False and target_weight=0.0."""
        dates = [f"2023{i//28+1:02d}{i%28+1:02d}" for i in range(130)]
        breakout = [AssistantBar(d, 10.0, 10.0, 10.0, 10.0) for d in dates[:-1]] + [
            AssistantBar(dates[-1], 10.0, 20.0, 10.0, 20.0)
        ]
        meta = CORE_ETF_UNIVERSE["513100.SH"]
        # Expected trading date is in the future relative to latest bar
        status = self.kernel.evaluate_daily_status(
            breakout, meta, ma_period=120, expected_as_of_date="20250101"
        )
        self.assertEqual(status.data_qualification_status, "STALE_DATA")
        self.assertFalse(status.is_actionable)
        self.assertEqual(status.target_weight, 0.0)
        self.assertIn("陈旧数据", status.reason)

    def test_daily_status_rejects_index_proxy_and_missing_series(self):
        """Invariant: Benchmark proxies and missing independent series reject actionable position advice."""
        dates = [f"2023{i//28+1:02d}{i%28+1:02d}" for i in range(130)]
        bars = [AssistantBar(d, 10.0, 10.0, 10.0, 10.0) for d in dates]

        # 000300.SH is benchmark proxy
        meta_proxy = CORE_ETF_UNIVERSE["000300.SH"]
        status_proxy = self.kernel.evaluate_daily_status(bars, meta_proxy, ma_period=120)
        self.assertEqual(status_proxy.data_qualification_status, "BENCHMARK_PROXY_ONLY")
        self.assertFalse(status_proxy.is_actionable)
        self.assertEqual(status_proxy.target_weight, 0.0)

        # 510300.SH has missing independent series
        meta_510300 = CORE_ETF_UNIVERSE["510300.SH"]
        status_510300 = self.kernel.evaluate_daily_status(bars, meta_510300, ma_period=120)
        self.assertEqual(status_510300.data_qualification_status, "MISSING_INDEPENDENT_SERIES")
        self.assertFalse(status_510300.is_actionable)
        self.assertEqual(status_510300.target_weight, 0.0)

    def test_runner_write_protection(self):
        """Invariant: Runner must reject overwriting non-empty output directories and preserve existing hash."""
        import hashlib
        import tempfile
        from scripts.research import run_personal_assistant_daily as runner

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "protected-run"
            target.mkdir()
            summary = target / "summary.json"
            summary.write_text("sentinel_test_content", encoding="utf-8")
            h_before = hashlib.sha256(summary.read_bytes()).hexdigest()

            with self.assertRaises(FileExistsError):
                runner.run_baseline_and_daily_review(output_dir=target)

            h_after = hashlib.sha256(summary.read_bytes()).hexdigest()
            self.assertEqual(h_before, h_after)

    def test_daily_status_rejects_incomplete_bar(self):
        """Invariant: Incomplete bar (is_complete=False) must be rejected with INCOMPLETE_BAR status and 0% target weight."""
        dates = [f"2023{i//28+1:02d}{i%28+1:02d}" for i in range(132)]
        # 130 flat bars + 2 breakout bars (20.0), last one is incomplete
        bars = [AssistantBar(d, 10.0, 10.0, 10.0, 10.0) for d in dates[:-2]] + [
            AssistantBar(dates[-2], 10.0, 20.0, 10.0, 20.0, is_complete=True),
            AssistantBar(dates[-1], 10.0, 20.0, 10.0, 20.0, is_complete=False),
        ]
        meta = CORE_ETF_UNIVERSE["513100.SH"]
        # With require_completed_bar=True (default)
        status = self.kernel.evaluate_daily_status(bars, meta, ma_period=120, require_completed_bar=True)
        self.assertEqual(status.data_qualification_status, "INCOMPLETE_BAR")
        self.assertFalse(status.is_actionable)
        self.assertEqual(status.target_weight, 0.0)
        self.assertEqual(status.regime, "DATA_DISQUALIFIED_INCOMPLETE")
        self.assertIn("未收盘/不完整K线拦截", status.reason)

        # With require_completed_bar=False, bar is accepted for preview and completes 2-day confirmation
        status_preview = self.kernel.evaluate_daily_status(bars, meta, ma_period=120, require_completed_bar=False)
        self.assertEqual(status_preview.data_qualification_status, "QUALIFIED")
        self.assertTrue(status_preview.is_actionable)
        self.assertEqual(status_preview.target_weight, 1.0)
        self.assertEqual(status_preview.regime, "BULLISH_HOLD")

    def test_daily_status_reports_co_occurring_disqualifications(self):
        """Invariant: Freshness gates accumulate; a bar that is both stale and incomplete must
        report both reasons rather than the first one encountered."""
        dates = [f"2023{i//28+1:02d}{i%28+1:02d}" for i in range(132)]
        bars = [AssistantBar(d, 10.0, 10.0, 10.0, 10.0) for d in dates[:-2]] + [
            AssistantBar(dates[-2], 10.0, 20.0, 10.0, 20.0, is_complete=True),
            AssistantBar(dates[-1], 10.0, 20.0, 10.0, 20.0, is_complete=False),
        ]
        meta = CORE_ETF_UNIVERSE["513100.SH"]
        status = self.kernel.evaluate_daily_status(
            bars, meta, ma_period=120, expected_as_of_date="20250101", require_completed_bar=True
        )
        self.assertEqual(status.data_qualification_status, "INCOMPLETE_BAR+STALE_DATA")
        self.assertEqual(status.regime, "DATA_DISQUALIFIED_INCOMPLETE_AND_STALE_DATA")
        self.assertIn("INCOMPLETE_BAR", status.data_qualification_status)
        self.assertFalse(status.is_actionable)
        self.assertEqual(status.target_weight, 0.0)
        self.assertIn("未收盘/不完整K线拦截", status.reason)
        self.assertIn("陈旧数据拦截", status.reason)

    def test_identity_disqualification_composes_with_freshness(self):
        """Invariant: An index proxy whose series is also stale reports both identity and
        freshness disqualification, with 0% target weight."""
        dates = [f"2023{i//28+1:02d}{i%28+1:02d}" for i in range(130)]
        bars = [AssistantBar(d, 10.0, 10.0, 10.0, 10.0) for d in dates]
        meta = CORE_ETF_UNIVERSE["000300.SH"]
        status = self.kernel.evaluate_daily_status(
            bars, meta, ma_period=120, expected_as_of_date="20250101"
        )
        self.assertEqual(status.data_qualification_status, "BENCHMARK_PROXY_ONLY+STALE_DATA")
        self.assertEqual(status.regime, "DATA_DISQUALIFIED_BENCHMARK_PROXY_ONLY_AND_STALE_DATA")
        self.assertFalse(status.is_actionable)
        self.assertEqual(status.target_weight, 0.0)
        self.assertIn("基准指数代理", status.reason)
        self.assertIn("陈旧数据拦截", status.reason)

    def test_deterministic_daily_report_generation(self):
        """Invariant: Deterministic daily brief outputs required 4 sections and parses to valid markdown."""
        dates = [f"2023{i//28+1:02d}{i%28+1:02d}" for i in range(130)]
        bars = [AssistantBar(d, 10.0, 10.0, 10.0, 10.0) for d in dates]
        meta = CORE_ETF_UNIVERSE["513100.SH"]
        st = self.kernel.evaluate_daily_status(bars, meta, ma_period=120)

        report = generate_deterministic_daily_report(
            daily_statuses=[st],
            expected_as_of_date=dates[-1],
            source_data_hash="fake_test_hash",
            source_data_path="test/path.json",
            execution_run_id="test_run",
        )
        self.assertIn("input_status", report)
        self.assertIn("rule_status", report)
        self.assertIn("risk_and_evidence", report)
        self.assertIn("tool_status", report)
        self.assertEqual(report["input_status"]["freshness_status"], "FRESH")
        self.assertEqual(report["tool_status"]["report_generation_status"], "SUCCESS")

        md = format_daily_report_markdown(report)
        self.assertIn("个人量化交易助手每日收盘复盘报告", md)
        self.assertIn("1. 输入与数据资格状态", md)
        self.assertIn("2. 规则决策与无订单看板", md)
        self.assertIn("3. 风险基线与证据追踪", md)
        self.assertIn("4. 工具与系统状态", md)

    def test_runner_creates_daily_report_artifacts(self):
        """Invariant: Runner generates daily-report.json and daily-report.md in output directory."""
        import json
        import tempfile
        from scripts.research import run_personal_assistant_daily as runner

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "daily-test-run"
            summary = runner.run_baseline_and_daily_review(
                output_dir=target,
                expected_as_of_date="20261009",
            )
            self.assertIn("daily_after_market_review", summary)
            report_json = target / "daily-report.json"
            report_md = target / "daily-report.md"
            self.assertTrue(report_json.exists())
            self.assertTrue(report_md.exists())

            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("daily_report_json", manifest["output_artifacts"])
            self.assertIn("daily_report_md", manifest["output_artifacts"])
            self.assertEqual(manifest["parameters"]["expected_as_of_date"], "20261009")


if __name__ == "__main__":
    unittest.main()

