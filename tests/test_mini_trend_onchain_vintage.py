from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from qount.mini_trend.onchain_vintage import OnchainVintageConfig
from qount.mini_trend.onchain_vintage import collect_onchain_vintage
from qount.mini_trend.onchain_vintage import parse_vintage_response
from qount.mini_trend.regime_onchain import ONCHAIN_METRICS


def _raw(source_date: str, *, hashrate: float = 100.0) -> bytes:
    row = {
        "asset": "btc",
        "time": f"{source_date}T00:00:00.000000000Z",
        **{metric: "1" for metric in ONCHAIN_METRICS},
        "HashRate": str(hashrate),
        "FlowInExUSD-status": "reviewed",
        "FlowOutExUSD-status": "reviewed",
    }
    return json.dumps({"data": [row]}, sort_keys=True).encode()


class MiniTrendOnchainVintageTest(unittest.TestCase):
    def test_snapshot_binds_completed_source_day_and_local_retrieval(self) -> None:
        retrieved_at = dt.datetime(2026, 7, 18, 1, 2, 3, tzinfo=dt.UTC)
        payload = parse_vintage_response(
            _raw("2026-07-17"),
            source_date="2026-07-17",
            retrieved_at=retrieved_at,
            config=OnchainVintageConfig(),
        )
        self.assertEqual(payload["snapshot"]["decision_date"], "2026-07-18")
        self.assertEqual(payload["snapshot"]["retrieval_lag_days"], 1)
        self.assertTrue(payload["diagnostics"]["local_retrieval_timestamp_bound"])
        self.assertFalse(payload["diagnostics"]["provider_publication_timestamp_available"])

    def test_collection_refuses_same_id_with_different_raw_response(self) -> None:
        retrieved_at = dt.datetime(2026, 7, 18, 1, 2, 3, tzinfo=dt.UTC)
        with tempfile.TemporaryDirectory() as tmp:
            first, path = collect_onchain_vintage(
                raw_root=tmp,
                source_date="2026-07-17",
                retrieved_at=retrieved_at,
                fetch=lambda _: _raw("2026-07-17", hashrate=100.0),
            )
            self.assertTrue(Path(path).is_file())
            second, _ = collect_onchain_vintage(
                raw_root=tmp,
                source_date="2026-07-17",
                retrieved_at=retrieved_at,
                fetch=lambda _: _raw("2026-07-17", hashrate=100.0),
            )
            self.assertEqual(first["snapshot_hash"], second["snapshot_hash"])
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                collect_onchain_vintage(
                    raw_root=tmp,
                    source_date="2026-07-17",
                    retrieved_at=retrieved_at,
                    fetch=lambda _: _raw("2026-07-17", hashrate=101.0),
                )


if __name__ == "__main__":
    unittest.main()
