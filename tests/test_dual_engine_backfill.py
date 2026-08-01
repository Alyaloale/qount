from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs
from urllib.parse import urlparse

from qount.contracts import canonical_hash
from qount.dual_engine import C60_SYMBOLS
from qount.dual_engine import DUAL_ENGINE_PROGRAM_VERSION
from qount.dual_engine import DualEngineMarketConfig
from qount.dual_engine import collect_ytd_replay
from qount.dual_engine import run_paper_cycle
from scripts.operations.backfill_dual_engine_ytd import _CachedPublicGetter


class DualEngineYtdReplayTest(unittest.TestCase):
    def _config(self) -> DualEngineMarketConfig:
        return DualEngineMarketConfig.from_dict(
            {
                "schema_version": 1,
                "tiingo_token_env": "TIINGO_API_TOKEN",
                "timeout_seconds": 10,
                "history_calendar_days": 450,
                "g20_signal_dates": ["2026-01-30"],
                "g20_rebalance_dates": ["2026-01-02"],
                "orders_authorized": False,
                "private_exchange_api_used": False,
            }
        )

    def _getter(self, url, _headers, _timeout):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.path.startswith("/tiingo/daily/"):
            symbol = parsed.path.split("/")[3]
            start = dt.date(2025, 8, 1)
            payload = []
            for index in range(157):
                session = start + dt.timedelta(days=index)
                if session.weekday() >= 5:
                    continue
                payload.append(
                    {
                        "date": f"{session.isoformat()}T00:00:00.000Z",
                        "open": 99.5 + index / 10,
                        "close": 100.0 + index / 10,
                        "adjClose": 100.0
                        + index / 10
                        + (1.0 if symbol == "QQQ" else 0.0),
                    }
                )
        elif parsed.path.startswith("/iex/"):
            payload = [
                {"date": "2026-01-02T14:30:00.000Z", "open": 111.25}
            ]
        elif parsed.path == "/api/v3/klines" and query["interval"] == ["1d"]:
            start = dt.date(2025, 8, 1)
            payload = []
            for index in range(158):
                session = start + dt.timedelta(days=index)
                open_at = dt.datetime.combine(
                    session, dt.time(), tzinfo=dt.timezone.utc
                )
                open_ms = int(open_at.timestamp() * 1000)
                close_ms = open_ms + 86_399_999
                payload.append(
                    [
                        open_ms,
                        str(100.0 + index / 20),
                        "110",
                        "90",
                        str(100.0 + index / 15),
                        "10",
                        close_ms,
                    ]
                )
        elif parsed.path == "/api/v3/klines" and query["interval"] == ["1m"]:
            start_ms = int(query["startTime"][0])
            payload = [
                [start_ms, "109.5", "110", "109", "109.8", "1", start_ms + 59_999]
            ]
        elif parsed.path == "/api/v3/exchangeInfo":
            payload = {
                "symbols": [
                    {
                        "symbol": symbol,
                        "filters": [
                            {"filterType": "LOT_SIZE", "stepSize": "0.000001"},
                            {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
                        ],
                    }
                    for symbol in C60_SYMBOLS
                ]
            }
        else:
            raise AssertionError(url)
        return payload, canonical_hash({"url": url, "payload": payload})

    def test_collects_and_replays_first_valid_2026_session_into_curve(self) -> None:
        replay = collect_ytd_replay(
            self._config(),
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 1, 4),
            getter=self._getter,
            environment={"TIINGO_API_TOKEN": "fixture"},
        )

        self.assertEqual(len(replay.cycles), 4)
        self.assertTrue(replay.cycles[0].g20_rebalance_day)
        self.assertEqual(replay.first_observed_at, "2026-01-02T15:00:30+00:00")
        self.assertEqual(replay.last_observed_at, "2026-01-05T00:00:05+00:00")
        self.assertEqual(
            set(replay.archive_hashes),
            {
                "tiingo_public_archive",
                "binance_public_archive",
                "binance_exchange_rules",
            },
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "paper"
            snapshot = None
            for cycle in replay.cycles:
                snapshot = run_paper_cycle(root, cycle)

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.program_version, DUAL_ENGINE_PROGRAM_VERSION)
        self.assertEqual(snapshot.forward_start_at, "2026-01-02T15:00:30+00:00")
        self.assertEqual(snapshot.audit_row_count, 4)
        self.assertEqual(
            snapshot.history_reference,
            {
                "status": "owner_authorized_ytd_replay",
                "start_at": "2026-01-01T00:00:00+00:00",
                "method": "tiingo_daily_open_and_binance_minute",
                "curve_role": "simulated_not_realized",
            },
        )
        self.assertEqual(
            {len(portfolio["nav"]["points"]) for portfolio in snapshot.portfolios},
            {4},
        )
        self.assertFalse(snapshot.orders_authorized)
        self.assertFalse(snapshot.private_api_used)

    def test_public_download_cache_is_secret_free_and_resumable(self) -> None:
        calls = 0

        def upstream(url, _headers, _timeout):
            nonlocal calls
            calls += 1
            payload = [{"date": "2026-01-02", "close": 100.0}]
            return payload, canonical_hash(
                {"url_path": url.split("?", 1)[0], "payload": payload}
            )

        with tempfile.TemporaryDirectory() as temporary:
            getter = _CachedPublicGetter(
                Path(temporary) / "cache", upstream=upstream
            )
            url = "https://api.tiingo.com/tiingo/daily/SPY/prices?startDate=2026-01-01"
            first = getter(url, {"Authorization": "Token fixture-secret"}, 10)
            second = getter(url, {"Authorization": "Token fixture-secret"}, 10)
            cache_files = list((Path(temporary) / "cache").iterdir())

            self.assertEqual(first, second)
            self.assertEqual(calls, 1)
            self.assertEqual(len(cache_files), 1)
            self.assertEqual(os.stat(cache_files[0]).st_mode & 0o777, 0o600)
            self.assertNotIn(b"fixture-secret", cache_files[0].read_bytes())


if __name__ == "__main__":
    unittest.main()
