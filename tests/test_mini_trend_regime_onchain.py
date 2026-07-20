from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from qount.mini_trend.regime_onchain import ONCHAIN_METRICS
from qount.mini_trend.regime_onchain import OnchainDatasetConfig
from qount.mini_trend.regime_onchain import build_onchain_dataset
from qount.mini_trend.regime_onchain_audit import OnchainAuditConfig
from qount.mini_trend.regime_onchain_audit import _folds


def _response(start: dt.date, days: int) -> bytes:
    rows = []
    for index in range(days):
        date = start + dt.timedelta(days=index)
        rows.append(
            {
                "asset": "btc",
                "time": f"{date.isoformat()}T00:00:00.000000000Z",
                "CapMVRVCur": str(1.0 + index / 1000),
                "AdrActCnt": str(100_000 + index),
                "TxCnt": str(200_000 + index * 2),
                "HashRate": str(1e8 + index * 1000),
                "FlowInExUSD": str(1e6 + index * 100),
                "FlowOutExUSD": str(9e5 + index * 80),
                "FlowInExUSD-status": "reviewed",
                "FlowOutExUSD-status": "reviewed",
            }
        )
    return json.dumps({"data": rows}).encode()


class MiniTrendRegimeOnchainTest(unittest.TestCase):
    def test_dataset_is_cached_lagged_and_reproducible(self) -> None:
        start = dt.date(2020, 1, 1)
        days = 400
        end = start + dt.timedelta(days=days - 1)
        config = OnchainDatasetConfig(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            request_retries=0,
        )
        raw = _response(start, days)
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "raw.json"
            first = build_onchain_dataset(cache, config, fetch=lambda _: raw)
            second = build_onchain_dataset(
                cache,
                config,
                fetch=lambda _: (_ for _ in ()).throw(AssertionError("cache miss")),
            )
        self.assertEqual(first["diagnostics"]["verdict"], "pass_latest_vintage_dataset")
        self.assertEqual(first["diagnostics"]["coverage_ratio"], 1.0)
        self.assertEqual(first["data_hash"], second["data_hash"])
        self.assertEqual(first["contract"]["metrics"], list(ONCHAIN_METRICS))
        first_feature = first["daily_features"][0]
        self.assertEqual(
            dt.date.fromisoformat(first_feature["decision_date"])
            - dt.date.fromisoformat(first_feature["source_date"]),
            dt.timedelta(days=1),
        )

    def test_audit_counts_seven_fixed_polarity_trials(self) -> None:
        config = OnchainAuditConfig(prior_research_trial_count=120)
        self.assertEqual(config.trial_count, 7)
        self.assertEqual(config.cumulative_trial_count, 127)

    def test_audit_folds_are_limited_to_contract_test_years(self) -> None:
        rows = [
            {"decision_date": f"{year}-01-01", "predicted": 1.0, "actual": 1.0}
            for year in (2021, 2022, 2023, 2024)
        ]
        self.assertEqual(
            [row["test_year"] for row in _folds(rows, (2023, 2024))],
            [2023, 2024],
        )


if __name__ == "__main__":
    unittest.main()
