from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.parse
import zipfile
from pathlib import Path

from qount.alpha_agents.feature_experiment import FeatureExperimentConfig
from qount.alpha_agents.feature_experiment import _derivative_feature_value
from qount.alpha_agents.feature_experiment import _rolling_betas
from qount.alpha_agents.feature_experiment import build_feature_experiment_dataset
from qount.alpha_agents.metrics import build_beta_residual_metrics
from qount.alpha_agents.metrics import load_return_rows
from qount.alpha_agents.promotion import evaluate_promotion_scorecard


def _zip_csv(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.csv", text)
    return buf.getvalue()


def _close_for_symbol(symbol: str, day: int) -> float:
    base = {
        "BTCUSDT": 100.0,
        "ETHUSDT": 50.0,
        "BNBUSDT": 20.0,
        "SOLUSDT": 10.0,
    }[symbol]
    if symbol == "ETHUSDT":
        return base + day + (3 if day % 5 in {3, 4} else 0)
    if symbol == "BTCUSDT":
        return base + day * 0.7
    if symbol == "BNBUSDT":
        return base + day * 0.4
    return base + day * 0.2


def _kline_csv(symbol: str) -> str:
    rows = []
    for day in range(1, 32):
        ts = 1704067200000 + (day - 1) * 86_400_000
        close = _close_for_symbol(symbol, day)
        volume = 100 + day * 2
        taker_buy = volume * (0.7 if day % 4 in {0, 1} else 0.3)
        rows.append(
            f"{ts},{close - 0.5},{close + 1},{close - 1},{close},{volume},{ts + 1},"
            f"{volume * close},{50 + day},{taker_buy},{taker_buy * close},0"
        )
    return "\n".join(rows)


def _rest_kline_json(symbol: str, start_ms: int, end_ms: int) -> bytes:
    rows = []
    for day in range(1, 32):
        ts = 1704067200000 + (day - 1) * 86_400_000
        if not start_ms <= ts <= end_ms:
            continue
        close = _close_for_symbol(symbol, day)
        volume = 100 + day * 2
        taker_buy = volume * (0.7 if day % 4 in {0, 1} else 0.3)
        rows.append(
            [
                ts,
                str(close - 0.5),
                str(close + 1),
                str(close - 1),
                str(close),
                str(volume),
                ts + 1,
                str(volume * close),
                50 + day,
                str(taker_buy),
                str(taker_buy * close),
                "0",
            ]
        )
    return json.dumps(rows).encode("utf-8")


def _exchange_info() -> dict:
    return {
        "symbols": [
            {
                "symbol": "ETHUSDT",
                "status": "TRADING",
                "baseAsset": "ETH",
                "quoteAsset": "USDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "1000000", "tickSize": "0.01"},
                    {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100000", "stepSize": "0.001"},
                    {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "100000", "stepSize": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }
        ]
    }


def _fake_fetch(url: str) -> bytes:
    if "/fapi/v1/klines" in url:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        symbol = params["symbol"][0]
        return _rest_kline_json(symbol, int(params["startTime"][0]), int(params["endTime"][0]))
    if "fundingRate" in url:
        rows = [
            "1704412800000,8,0.00010000",
            "1704499200000,8,-0.00005000",
        ]
        return _zip_csv("\n".join(rows))
    for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"):
        if f"/{symbol}/" in url:
            return _zip_csv(_kline_csv(symbol))
    raise AssertionError(f"unexpected url {url}")


def _write_derivatives_state(path: Path) -> None:
    oi_rows = []
    taker_rows = []
    for day in range(1, 32):
        open_ts = 1704067200000 + (day - 1) * 86_400_000
        close_ts = open_ts + 86_400_000
        oi_rows.append(
            {
                "symbol": "ETHUSDT",
                "ts_ms": close_ts,
                "sum_open_interest": 1000 + day * 10,
                "sum_open_interest_value": 200000 + day * 1000,
                "cmc_circulating_supply": None,
            }
        )
        taker_rows.append(
            {
                "symbol": "ETHUSDT",
                "ts_ms": close_ts,
                "buy_sell_ratio": 1.2 if day % 2 == 0 else 0.8,
                "buy_vol": 120.0 if day % 2 == 0 else 80.0,
                "sell_vol": 80.0 if day % 2 == 0 else 120.0,
            }
        )
    path.write_text(
        json.dumps(
            {
                "schema_version": "alpha_agent_derivatives_state_v0.1",
                "meta": {
                    "official_source": "binance_usdm_futures_rest",
                    "history_limit": "latest_30_days_official_limit",
                },
                "diagnostics": {"errors": []},
                "open_interest_hist": oi_rows,
                "taker_long_short": taker_rows,
                "current_open_interest": [],
            }
        ),
        encoding="utf-8",
    )


class AlphaAgentsFeatureExperimentTest(unittest.TestCase):
    def test_oi_delta_does_not_cross_historical_segment(self) -> None:
        derivatives_state = {
            "by_symbol": {
                "ETHUSDT": {
                    "open_interest_hist": [
                        {"ts_ms": 100, "segment_id": 0, "sum_open_interest": 100.0},
                        {"ts_ms": 200, "segment_id": 1, "sum_open_interest": 120.0},
                    ]
                }
            }
        }
        value = _derivative_feature_value(
            "oi_delta",
            symbol="ETHUSDT",
            decision_ts_ms=200,
            lookback=1,
            derivatives_state=derivatives_state,
        )
        self.assertIsNone(value)

    def test_rolling_beta_restarts_after_timestamp_gap(self) -> None:
        closes = [100.0 + index for index in range(50)]
        btc = [200.0 + index * 0.5 for index in range(50)]
        timestamps = [index * 300_000 for index in range(50)]
        timestamps[25:] = [value + 3_600_000 for value in timestamps[25:]]
        betas = _rolling_betas(
            closes,
            btc,
            timestamps,
            interval_ms=300_000,
            lookback=24,
        )
        self.assertIsNone(betas[25])
        self.assertIsNone(betas[44])
        self.assertIsNotNone(betas[45])

    def test_build_feature_experiment_oos_returns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = FeatureExperimentConfig(
                start_month="2024-01",
                end_month="2024-01",
                interval="1d",
                horizon_bars=2,
                train_fraction=0.55,
                lookbacks=(2, 4),
                feature_families=("momentum", "reversal"),
                thresholds=(0.0, 0.005),
                modes=("long_short", "long_cash"),
                include_funding=True,
                cache_dir=str(Path(tmp) / "klines"),
                funding_cache_dir=str(Path(tmp) / "funding"),
            )
            dataset = build_feature_experiment_dataset(config, fetch=_fake_fetch, exchange_info=_exchange_info())
        self.assertEqual(dataset["schema_version"], "alpha_agent_feature_experiment_v0.2")
        self.assertEqual(dataset["meta"]["trial_count"], 16)
        self.assertEqual(dataset["meta"]["exchange_rules_source"], "runtime_exchange_info")
        self.assertTrue(dataset["meta"]["filter_validator_reused"])
        self.assertTrue(dataset["meta"]["funding_included"])
        self.assertGreaterEqual(dataset["meta"]["min_notional_coverage"], 0.0)
        self.assertIn("candidate_id", dataset["selected_candidate"])
        self.assertGreater(len(dataset["periods"]), 0)

    def test_kline_taker_flow_features_and_inverse_polarity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = FeatureExperimentConfig(
                start_month="2024-01",
                end_month="2024-01",
                interval="1d",
                horizon_bars=1,
                train_fraction=0.8,
                lookbacks=(2,),
                feature_families=(
                    "kline_taker_imbalance",
                    "kline_taker_pressure_change",
                    "kline_quote_volume_z",
                    "kline_realized_vol_change",
                ),
                thresholds=(0.0,),
                modes=("long_short",),
                polarities=(1, -1),
                selection_metric="rank_ic",
                beta_lookback_bars=4,
                include_funding=False,
                output_granularity="bar",
                cache_dir=str(Path(tmp) / "klines"),
                funding_cache_dir=str(Path(tmp) / "funding"),
            )
            dataset = build_feature_experiment_dataset(
                config,
                fetch=_fake_fetch,
                exchange_info=_exchange_info(),
                include_validation_matrix=True,
            )
        self.assertEqual(dataset["meta"]["trial_count"], 8)
        self.assertEqual(dataset["diagnostics"]["selection_metric"], "rank_ic")
        self.assertGreater(dataset["diagnostics"]["selected_train_ic"]["sample_count"], 0)
        self.assertEqual(dataset["diagnostics"]["kline_field_coverage"]["taker_buy_base_volume"], 1.0)
        self.assertIn(
            dataset["selected_candidate"]["feature_family"],
            {
                "kline_taker_imbalance",
                "kline_taker_pressure_change",
                "kline_quote_volume_z",
                "kline_realized_vol_change",
            },
        )
        self.assertTrue(any(row["polarity"] == -1 for row in dataset["diagnostics"]["top_train_candidates"]))
        matrix = dataset["validation_matrix"]
        self.assertEqual(matrix["candidate_count"], 8)
        self.assertEqual(len(matrix["daily_timestamps"]), len(matrix["btc_returns_pct"]))
        self.assertEqual(len(matrix["ic_timestamps"]), len(matrix["ic_residual_forward_returns_pct"]))
        self.assertEqual(len(matrix["candidates"][0]["ic_feature_values"]), len(matrix["ic_timestamps"]))

    def test_derivatives_state_features_feed_candidate_grid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            derivatives_path = Path(tmp) / "derivatives_state.json"
            _write_derivatives_state(derivatives_path)
            config = FeatureExperimentConfig(
                start_month="2024-01",
                end_month="2024-01",
                interval="1d",
                horizon_bars=2,
                train_fraction=0.55,
                lookbacks=(1,),
                feature_families=("oi_delta", "taker_imbalance", "taker_ratio"),
                thresholds=(0.0,),
                modes=("long_short",),
                include_funding=False,
                output_granularity="bar",
                derivatives_state_path=str(derivatives_path),
                cache_dir=str(Path(tmp) / "klines"),
                funding_cache_dir=str(Path(tmp) / "funding"),
            )
            dataset = build_feature_experiment_dataset(config, fetch=_fake_fetch, exchange_info=_exchange_info())
        self.assertEqual(dataset["meta"]["trial_count"], 3)
        self.assertTrue(dataset["diagnostics"]["derivatives_state"]["used"])
        self.assertEqual(dataset["diagnostics"]["derivatives_state"]["history_limit"], "latest_30_days_official_limit")
        self.assertIn(dataset["selected_candidate"]["feature_family"], {"oi_delta", "taker_imbalance", "taker_ratio"})
        self.assertTrue(any(row.get("strategy_feature_value") is not None for row in dataset["periods"]))

    def test_rest_kline_source_uses_rest_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = FeatureExperimentConfig(
                start_month="2024-01",
                end_month="2024-01",
                interval="1d",
                kline_source="rest",
                market="um",
                horizon_bars=2,
                train_fraction=0.55,
                lookbacks=(2,),
                feature_families=("momentum",),
                thresholds=(0.0,),
                modes=("long_short",),
                include_funding=False,
                output_granularity="bar",
                cache_dir=str(Path(tmp) / "rest-klines"),
                funding_cache_dir=str(Path(tmp) / "funding"),
            )
            dataset = build_feature_experiment_dataset(config, fetch=_fake_fetch, exchange_info=_exchange_info())
        self.assertEqual(dataset["config"]["kline_source"], "rest")
        self.assertEqual(dataset["diagnostics"]["kline_source"]["source"], "rest")
        self.assertGreater(len(dataset["periods"]), 0)

    def test_feature_experiment_feeds_metrics_without_data_gate_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = FeatureExperimentConfig(
                start_month="2024-01",
                end_month="2024-01",
                interval="1d",
                horizon_bars=2,
                train_fraction=0.55,
                lookbacks=(2,),
                feature_families=("momentum",),
                thresholds=(0.0,),
                modes=("long_short",),
                include_funding=False,
                output_granularity="bar",
                cache_dir=str(Path(tmp) / "klines"),
                funding_cache_dir=str(Path(tmp) / "funding"),
            )
            dataset = build_feature_experiment_dataset(config, fetch=_fake_fetch, exchange_info=_exchange_info())
            path = Path(tmp) / "feature.json"
            path.write_text(json.dumps(dataset), encoding="utf-8")
            rows, meta, data_hash = load_return_rows(path)
        metrics = build_beta_residual_metrics(
            rows,
            source_label="feature-fixture",
            data_hash=data_hash,
            holdout_role="discovery",
            meta=meta,
        )
        scorecard = evaluate_promotion_scorecard(metrics, target="paper")
        blocked = {gate["gate_id"] for gate in scorecard["gates"] if gate["status"] == "block"}
        self.assertNotIn("G1", blocked)
        self.assertIn("G6", blocked)


if __name__ == "__main__":
    unittest.main()
