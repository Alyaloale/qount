"""Unit tests for simplified API schemas and data contracts."""

from __future__ import annotations

import unittest
from pydantic import ValidationError

from qount.api.schemas import (
    AccountSnapshot,
    HealthResponse,
    LineMetrics,
    LineSafety,
    LineSource,
    MarketCoverage,
    MarketKlinesBar,
    MarketKlinesResponse,
    NavPoint,
    PaperLine,
    PaperLineSummary,
    PositionItem,
)


class TestSchemas(unittest.TestCase):
    def test_valid_paper_line(self) -> None:
        line = PaperLine(
            line_id="test_line",
            name="Test Strategy",
            category="assistant",
            status="ACTIVE_PAPER",
            adjudication="Adjudication note",
            as_of="2026-10-09",
            freshness="FRESH",
            nav_series=[
                NavPoint(date="2026-01-02", nav=1.0, benchmark_nav=1.0),
                NavPoint(date="2026-10-09", nav=1.12, benchmark_nav=1.04),
            ],
            metrics=LineMetrics(
                ytd_return_pct=12.0,
                max_drawdown_pct=8.5,
                sharpe=0.85,
                trade_count=10,
                start_date="2026-01-02",
                days=180,
            ),
            positions=[
                PositionItem(symbol="SPY", weight=1.0, entry_date="2026-03-01")
            ],
            source=LineSource(
                path="state/research_runs/test/summary.json",
                sha256="abcdef123456",
                produced_at="2026-10-05T12:00:00Z",
            ),
            safety=LineSafety(research_only=True, orders_authorized=False),
        )

        self.assertEqual(line.line_id, "test_line")
        self.assertEqual(len(line.nav_series), 2)
        self.assertEqual(line.metrics.ytd_return_pct, 12.0)
        self.assertTrue(line.safety.research_only)
        self.assertFalse(line.safety.orders_authorized)

    def test_paper_line_defaults_and_empty_curves(self) -> None:
        line = PaperLine(
            line_id="empty_line",
            name="Empty Strategy",
            as_of="2026-10-09",
            source=LineSource(path="dummy/path"),
        )
        self.assertEqual(line.nav_series, [])
        self.assertEqual(line.positions, [])
        self.assertEqual(line.status, "ACTIVE_PAPER")
        self.assertEqual(line.freshness, "FRESH")
        self.assertTrue(line.safety.research_only)

    def test_paper_line_summary_matches_schema(self) -> None:
        summary = PaperLineSummary(
            line_id="summary_line",
            name="Summary Strategy",
            category="equity",
            status="ARCHIVED",
            adjudication="Archived line",
            as_of="2026-06-30",
            freshness="STALE",
            metrics=LineMetrics(cagr_pct=15.0),
            source=LineSource(path="dummy/path"),
        )
        self.assertEqual(summary.line_id, "summary_line")
        self.assertEqual(summary.status, "ARCHIVED")

    def test_account_snapshot_schema(self) -> None:
        acc = AccountSnapshot(
            as_of="2026-10-12T09:00:00Z",
            mode="PAPER",
            nav=1000000.0,
            cash=500000.0,
            positions=[PositionItem(symbol="513100.SH", weight=0.5)],
            currency="CNY",
            source=LineSource(path="state/research_runs/acc/summary.json"),
        )
        self.assertEqual(acc.nav, 1000000.0)
        self.assertEqual(acc.cash, 500000.0)
        self.assertEqual(len(acc.positions), 1)
        self.assertEqual(acc.mode, "PAPER")

    def test_account_snapshot_missing_required_fails(self) -> None:
        with self.assertRaises(ValidationError):
            AccountSnapshot.model_validate({"mode": "PAPER"})

    def test_market_klines_response(self) -> None:
        resp = MarketKlinesResponse(
            symbol="BTCUSDT",
            interval="1d",
            source="cache",
            bars=[
                MarketKlinesBar(
                    date="2026-10-09",
                    open=60000.0,
                    high=62000.0,
                    low=59500.0,
                    close=61500.0,
                    volume=1200.5,
                )
            ],
            coverage=MarketCoverage(
                start="2026-10-09",
                end="2026-10-09",
                gaps=[],
            ),
        )
        self.assertEqual(resp.symbol, "BTCUSDT")
        self.assertEqual(len(resp.bars), 1)
        self.assertEqual(resp.coverage.gaps, [])

    def test_health_response(self) -> None:
        h = HealthResponse(
            status="ok",
            db_connected=True,
            last_ingest_at="2026-10-12T09:00:00Z",
            paper_lines_count=4,
        )
        self.assertTrue(h.db_connected)
        self.assertTrue(h.safety.research_only)


if __name__ == "__main__":
    unittest.main()
