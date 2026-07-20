from __future__ import annotations

import io
import zipfile
import unittest

from qount.alpha_agents.binance_returns import BinanceReturnsConfig
from qount.alpha_agents.binance_returns import build_binance_returns_dataset
from qount.alpha_agents.metrics import build_beta_residual_metrics
from qount.alpha_agents.metrics import load_return_rows
from qount.alpha_agents.promotion import evaluate_promotion_scorecard


def _zip_csv(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.csv", text)
    return buf.getvalue()


def _monthly_kline_csv(symbol: str) -> str:
    base = {
        "BTCUSDT": 100.0,
        "ETHUSDT": 50.0,
        "BNBUSDT": 20.0,
    }[symbol]
    rows = []
    for day in range(1, 76):
        ts = 1704067200000 + (day - 1) * 86_400_000
        close = base + day
        open_ = close - 0.5
        high = close + 1
        low = close - 1
        rows.append(f"{ts},{open_},{high},{low},{close},100,{ts + 1}")
    return "\n".join(rows)


def _fake_fetch(url: str) -> bytes:
    for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
        if f"/{symbol}/" in url:
            return _zip_csv(_monthly_kline_csv(symbol))
    raise AssertionError(f"unexpected url {url}")


class AlphaAgentsBinanceReturnsTest(unittest.TestCase):
    def test_build_public_dump_returns_without_network(self) -> None:
        config = BinanceReturnsConfig(
            start_month="2024-01",
            end_month="2024-01",
            fast_window=3,
            slow_window=5,
            cache_dir="/tmp/qount-alpha-agent-test-cache",
        )
        dataset = build_binance_returns_dataset(config, fetch=_fake_fetch)
        self.assertEqual(dataset["schema_version"], "alpha_agent_binance_returns_v0.1")
        self.assertGreater(dataset["diagnostics"]["period_count"], 60)
        first_active = [row for row in dataset["periods"] if row["strategy_position"] != 0.0][0]
        self.assertIn("strategy_return_pct", first_active)
        self.assertTrue(dataset["meta"]["costs_included"])
        self.assertEqual(dataset["meta"]["exchange_rules_source"], "binance_public_dump")

    def test_public_dump_returns_feed_metrics_and_block_without_validation(self) -> None:
        config = BinanceReturnsConfig(
            start_month="2024-01",
            end_month="2024-01",
            fast_window=3,
            slow_window=5,
            cache_dir="/tmp/qount-alpha-agent-test-cache-2",
        )
        dataset = build_binance_returns_dataset(config, fetch=_fake_fetch)
        rows, meta, data_hash = load_return_rows_from_payload(dataset)
        metrics = build_beta_residual_metrics(
            rows,
            source_label="binance-fixture",
            data_hash=data_hash,
            holdout_role="discovery",
            meta=meta,
        )
        scorecard = evaluate_promotion_scorecard(metrics, target="paper")
        blocked = {gate["gate_id"]: gate for gate in scorecard["gates"] if gate["status"] == "block"}
        self.assertIn("G1", blocked)
        self.assertIn("G4", blocked)
        self.assertIn("G6", blocked)


def load_return_rows_from_payload(payload):
    import hashlib
    import json
    import tempfile
    from pathlib import Path

    from qount.alpha_agents.metrics import load_return_rows

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "returns.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return load_return_rows(path)


if __name__ == "__main__":
    unittest.main()
