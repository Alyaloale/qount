from __future__ import annotations

import datetime as dt
import unittest

from qount.mini_trend.regime_dvol_ml import DVOL_FEATURE_NAMES
from qount.mini_trend.regime_dvol_ml import augment_dataset_with_dvol


_HOUR_MS = 3_600_000
_START = int(dt.datetime(2021, 1, 1, tzinfo=dt.UTC).timestamp() * 1000)


def _dvol(count: int) -> dict:
    rows = []
    for index in range(count):
        btc = 60.0 + index * 0.01
        eth = 70.0 + index * 0.015
        rows.append(
            {
                "ts_ms": _START + index * _HOUR_MS,
                "decision_ts_ms": _START + (index + 1) * _HOUR_MS,
                "btc_dvol_open": btc,
                "btc_dvol_high": btc + 1.0,
                "btc_dvol_low": btc - 1.0,
                "btc_dvol_close": btc,
                "eth_dvol_open": eth,
                "eth_dvol_high": eth + 1.0,
                "eth_dvol_low": eth - 1.0,
                "eth_dvol_close": eth,
                "eth_minus_btc_dvol_close": eth - btc,
                "complete": True,
            }
        )
    return {"meta": {"data_hash": "dvol"}, "hourly_features": rows}


def _dataset() -> dict:
    return {
        "schema_version": "base",
        "features": ["base"],
        "contract": {"contract_hash": "base-contract"},
        "data_hash": "base-data",
        "summary": {"row_count": 2},
        "rows": [
            {"decision_date": "2021-02-05", "features": {"base": 1.0}},
            {"decision_date": "2021-02-06", "features": {"base": 2.0}},
        ],
    }


class MiniTrendRegimeDvolMLTest(unittest.TestCase):
    def test_dvol_features_are_point_in_time_and_future_invariant(self) -> None:
        original = _dvol(1_000)
        changed = _dvol(1_000)
        cutoff = int(
            dt.datetime(2021, 2, 6, tzinfo=dt.UTC).timestamp() * 1000
        )
        for row in changed["hourly_features"]:
            if row["decision_ts_ms"] > cutoff:
                row["btc_dvol_close"] *= 10
                row["eth_dvol_close"] *= 10
        left = augment_dataset_with_dvol(_dataset(), original)
        right = augment_dataset_with_dvol(_dataset(), changed)
        self.assertEqual(len(left["rows"]), 2)
        self.assertEqual(
            {name: left["rows"][0]["features"][name] for name in DVOL_FEATURE_NAMES},
            {name: right["rows"][0]["features"][name] for name in DVOL_FEATURE_NAMES},
        )
        decision_cutoff = int(
            dt.datetime(2021, 2, 6, tzinfo=dt.UTC).timestamp() * 1000
        )
        self.assertLessEqual(left["rows"][0]["dvol_decision_ts_ms"], decision_cutoff)
        self.assertEqual(left["summary"]["dvol_skipped_coverage"], 0)


if __name__ == "__main__":
    unittest.main()
