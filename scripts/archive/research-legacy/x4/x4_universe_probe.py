#!/usr/bin/env python3
"""Probe binance.vision UM 1d data availability for a BROAD candidate pool (线 D §22 Phase 2).

A dynamic-universe backtest is only honest if the candidate pool includes coins that DECLINED/died
(survivorship) and ones that listed LATE (ragged listing). This reports each candidate's bar count +
first/last date so we know what we can actually build with. Run on Mac (network, cached after first):
    .venv/bin/python scripts/research/x4_universe_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_klines  # noqa: E402

SURVIVORS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT", "DOTUSDT",
             "LINKUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT", "ATOMUSDT", "ETCUSDT", "TRXUSDT"]
DECLINED = ["DOGEUSDT", "MATICUSDT", "NEARUSDT", "FILUSDT", "SANDUSDT", "MANAUSDT", "AAVEUSDT",
            "UNIUSDT", "FTMUSDT", "ICPUSDT", "APEUSDT", "GALAUSDT", "ALGOUSDT", "EOSUSDT",
            "XLMUSDT", "VETUSDT", "THETAUSDT", "LUNAUSDT", "1000LUNCUSDT", "FTTUSDT"]
LATE = ["SUIUSDT", "APTUSDT", "TIAUSDT", "SEIUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "TONUSDT",
        "WLDUSDT", "1000PEPEUSDT", "ORDIUSDT", "WIFUSDT", "JUPUSDT", "RUNEUSDT"]


def probe(syms, label):
    print(f"\n=== {label} ({len(syms)}) ===")
    for s in syms:
        try:
            b = load_klines(s, "1d", start=(2020, 1), end=(2026, 6), market="um", skip_missing=True)
        except Exception as exc:
            print(f"  {s:14} ERR {type(exc).__name__}")
            continue
        if not b:
            print(f"  {s:14} -- no data")
        else:
            print(f"  {s:14} {len(b):>5} bars  {b[0].date} .. {b[-1].date}")


def main():
    for syms, label in [(SURVIVORS, "SURVIVORS (current pool)"),
                        (DECLINED, "DECLINED / dead (survivorship test)"),
                        (LATE, "LATE-LISTED (ragged listing test)")]:
        probe(syms, label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
