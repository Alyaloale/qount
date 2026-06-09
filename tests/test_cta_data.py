from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

if "ccxt" not in sys.modules:
    class _StubExchange:
        def __init__(self, options=None) -> None:
            self.options = options or {}

    sys.modules["ccxt"] = types.SimpleNamespace(binance=_StubExchange, binanceus=_StubExchange)

import sqlite3
import zipfile

from qount.cta_data import AKSHARE_DEFAULT_UNIVERSE
from qount.cta_data import BINANCE_DEFAULT_UNIVERSE
from qount.cta_data import OPENQUANT_DEFAULT_UNIVERSE
from qount.cta_data import TQSDK_DEFAULT_FUTURES
from qount.cta_data import align_on_common_dates
from qount.cta_data import exclude_asset_classes
from qount.cta_data import fetch_akshare_panel
from qount.cta_data import fetch_binance_panel
from qount.cta_data import fetch_ibkr_panel
from qount.cta_data import fetch_openquant_panel
from qount.cta_data import load_etf_cache
from qount.cta_data import read_etf_adjusted_close_from_zip
from qount.cta_data import save_etf_cache
from qount.cta_data import fetch_norgate_panel
from qount.cta_data import fetch_tiingo_panel
from qount.cta_data import fetch_tqsdk_panel
from qount.cta_data import align_prices_and_carry
from qount.cta_data import annualized_roll_yield
from qount.cta_data import build_term_structure_carry
from qount.cta_data import load_panel


class AlignOnCommonDatesTest(unittest.TestCase):
    def test_intersects_and_sorts(self) -> None:
        by_symbol = {
            "A": {"2020-01-03": 3.0, "2020-01-01": 1.0, "2020-01-02": 2.0},
            "B": {"2020-01-02": 20.0, "2020-01-03": 30.0, "2019-12-31": 9.0},
        }
        aligned = align_on_common_dates(by_symbol)
        # Common dates are 01-02 and 01-03, sorted ascending.
        self.assertEqual(aligned["A"], [2.0, 3.0])
        self.assertEqual(aligned["B"], [20.0, 30.0])

    def test_raises_when_too_few_common_dates(self) -> None:
        by_symbol = {"A": {"2020-01-01": 1.0}, "B": {"2020-01-02": 2.0}}
        with self.assertRaises(ValueError):
            align_on_common_dates(by_symbol)

    def test_raises_on_empty(self) -> None:
        with self.assertRaises(ValueError):
            align_on_common_dates({})


class TiingoPanelTest(unittest.TestCase):
    def test_missing_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            fetch_tiingo_panel(["SPY"], api_key=None)

    def test_injected_fetcher_builds_aligned_panel(self) -> None:
        payloads = {
            "spy": [
                {"date": "2020-01-01T00:00:00.000Z", "adjClose": 100.0},
                {"date": "2020-01-02T00:00:00.000Z", "adjClose": 101.0},
                {"date": "2020-01-03T00:00:00.000Z", "adjClose": 102.0},
            ],
            "tlt": [
                {"date": "2020-01-02", "adjClose": 50.0},
                {"date": "2020-01-03", "adjClose": 49.0},
                {"date": "2020-01-06", "adjClose": 51.0},
            ],
        }

        def fake_fetcher(url: str):
            for key, rows in payloads.items():
                if f"/{key}/" in url:
                    return rows
            raise AssertionError(f"unexpected url {url}")

        panel = fetch_tiingo_panel(["SPY", "TLT"], api_key="x", fetcher=fake_fetcher)
        # Common dates: 01-02, 01-03.
        self.assertEqual(panel["SPY"], [101.0, 102.0])
        self.assertEqual(panel["TLT"], [50.0, 49.0])

    def test_no_usable_rows_raises(self) -> None:
        with self.assertRaises(ValueError):
            fetch_tiingo_panel(["SPY"], api_key="x", fetcher=lambda url: [])


class GracefulVendorTest(unittest.TestCase):
    def test_ibkr_without_dep_raises_clear_error(self) -> None:
        if "ib_insync" in sys.modules:
            self.skipTest("ib_insync is installed in this env")
        with self.assertRaises(RuntimeError) as ctx:
            fetch_ibkr_panel()
        self.assertIn("ib_insync", str(ctx.exception))

    def test_norgate_without_dep_raises_clear_error(self) -> None:
        if "norgatedata" in sys.modules:
            self.skipTest("norgatedata is installed in this env")
        with self.assertRaises(RuntimeError) as ctx:
            fetch_norgate_panel()
        self.assertIn("norgatedata", str(ctx.exception))

    def test_tqsdk_missing_credentials_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            fetch_tqsdk_panel(user=None, password=None)
        self.assertIn("天勤", str(ctx.exception))

    def test_tqsdk_without_dep_raises_clear_error(self) -> None:
        if "tqsdk" in sys.modules:
            self.skipTest("tqsdk is installed in this env")
        with self.assertRaises(RuntimeError) as ctx:
            fetch_tqsdk_panel(user="u", password="p")
        self.assertIn("tqsdk", str(ctx.exception))

    def test_tqsdk_default_universe_is_cross_sector(self) -> None:
        # Spans at least 3 exchanges so breadth isn't trapped in one sector.
        exchanges = {s.split("@")[1].split(".")[0] for s in TQSDK_DEFAULT_FUTURES}
        self.assertGreaterEqual(len(exchanges), 3)
        self.assertGreaterEqual(len(TQSDK_DEFAULT_FUTURES), 12)


class BinancePanelTest(unittest.TestCase):
    def test_injected_fetcher_builds_aligned_daily_panel(self) -> None:
        payloads = {
            "BTC/USDT": [
                [1577836800000, 1, 1, 1, 100.0, 0],  # 2020-01-01
                [1577923200000, 1, 1, 1, 101.0, 0],  # 2020-01-02
                [1578009600000, 1, 1, 1, 102.0, 0],  # 2020-01-03
            ],
            "ETH/USDT": [
                [1577923200000, 1, 1, 1, 50.0, 0],   # 2020-01-02
                [1578009600000, 1, 1, 1, 49.0, 0],   # 2020-01-03
                [1578096000000, 1, 1, 1, 51.0, 0],   # 2020-01-04
            ],
        }
        panel = fetch_binance_panel(
            ["BTC/USDT", "ETH/USDT"], fetcher=lambda symbol: payloads[symbol]
        )
        # Common dates: 01-02, 01-03.
        self.assertEqual(panel["BTC/USDT"], [101.0, 102.0])
        self.assertEqual(panel["ETH/USDT"], [50.0, 49.0])

    def test_intraday_timeframe_keeps_same_day_bars_separate(self) -> None:
        # Two 4h bars on the same UTC date must not collapse to a single daily close.
        rows = {
            "BTC/USDT": [
                [1577836800000, 0, 0, 0, 100.0, 0],  # 2020-01-01T00:00
                [1577851200000, 0, 0, 0, 105.0, 0],  # 2020-01-01T04:00
            ],
            "ETH/USDT": [
                [1577836800000, 0, 0, 0, 10.0, 0],
                [1577851200000, 0, 0, 0, 11.0, 0],
            ],
        }
        panel = fetch_binance_panel(
            ["BTC/USDT", "ETH/USDT"], timeframe="4h", fetcher=lambda symbol: rows[symbol]
        )
        self.assertEqual(panel["BTC/USDT"], [100.0, 105.0])
        self.assertEqual(panel["ETH/USDT"], [10.0, 11.0])

    def test_no_usable_rows_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            fetch_binance_panel(["BTC/USDT"], fetcher=lambda symbol: [])

    def test_default_universe_is_usdt_quoted_basket(self) -> None:
        self.assertGreaterEqual(len(BINANCE_DEFAULT_UNIVERSE), 8)
        self.assertTrue(all(pair.endswith("/USDT") for pair in BINANCE_DEFAULT_UNIVERSE))
        self.assertIn("BTC/USDT", BINANCE_DEFAULT_UNIVERSE)


class OpenquantPanelTest(unittest.TestCase):
    def test_injected_fetcher_builds_aligned_panel(self) -> None:
        rows = {
            "000300": [("2020-01-02", 100.0), ("2020-01-03", 101.0), ("2020-01-06", 102.0)],
            "000012": [("2020-01-03", 50.0), ("2020-01-06", 49.0), ("2020-01-07", 51.0)],
        }
        panel = fetch_openquant_panel(
            ["000300", "000012"], fetcher=lambda symbol: rows[symbol]
        )
        # Common dates: 01-03, 01-06.
        self.assertEqual(panel["000300"], [101.0, 102.0])
        self.assertEqual(panel["000012"], [50.0, 49.0])

    def test_reads_real_temp_sqlite_index_bars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "market_data.sqlite")
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE index_bars (symbol TEXT, date TEXT, close REAL)")
            con.executemany(
                "INSERT INTO index_bars VALUES (?,?,?)",
                [
                    ("000300", "2020-01-02", 10.0), ("000300", "2020-01-03", 11.0),
                    ("000012", "2020-01-02", 5.0), ("000012", "2020-01-03", 5.5),
                ],
            )
            con.commit()
            con.close()
            panel = fetch_openquant_panel(["000300", "000012"], db_path=db, table="index_bars")
            self.assertEqual(panel["000300"], [10.0, 11.0])
            self.assertEqual(panel["000012"], [5.0, 5.5])

    def test_reads_real_temp_sqlite_price_bars_filters_period_adjust(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "market_data.sqlite")
            con = sqlite3.connect(db)
            con.execute(
                "CREATE TABLE price_bars (symbol TEXT, period TEXT, adjust TEXT, date TEXT, close REAL)"
            )
            con.executemany(
                "INSERT INTO price_bars VALUES (?,?,?,?,?)",
                [
                    ("600519", "daily", "qfq", "2020-01-02", 100.0),
                    ("600519", "daily", "qfq", "2020-01-03", 101.0),
                    ("600519", "weekly", "qfq", "2020-01-03", 999.0),  # wrong period, excluded
                    ("000001", "daily", "qfq", "2020-01-02", 12.0),
                    ("000001", "daily", "qfq", "2020-01-03", 12.5),
                ],
            )
            con.commit()
            con.close()
            panel = fetch_openquant_panel(["600519", "000001"], db_path=db, table="price_bars")
            self.assertEqual(panel["600519"], [100.0, 101.0])
            self.assertEqual(panel["000001"], [12.0, 12.5])

    def test_missing_db_raises_clear_error(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            fetch_openquant_panel(["000300"], db_path="/no/such/market_data.sqlite")
        self.assertIn("market_data.sqlite", str(ctx.exception))

    def test_bad_table_raises(self) -> None:
        with self.assertRaises(ValueError):
            fetch_openquant_panel(["000300"], table="bogus")

    def test_no_usable_rows_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            fetch_openquant_panel(["000300"], fetcher=lambda symbol: [])

    def test_default_universe_has_bond_diversifier(self) -> None:
        # 上证国债指数 000012 is the only genuine non-equity diversifier; it must be present.
        self.assertIn("000012", OPENQUANT_DEFAULT_UNIVERSE)
        self.assertGreaterEqual(len(OPENQUANT_DEFAULT_UNIVERSE), 12)


class AksharePanelTest(unittest.TestCase):
    def _make_zip(self, path: str) -> None:
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(
                "etf_data/daily/510300.SH.csv",
                "ts_code,trade_date,pre_close,open,high,low,close,change,pct_chg,vol,amount\n"
                "510300.SH,20200103,1,1,1,1,10.0,0,0,0,0\n"
                "510300.SH,20200102,1,1,1,1,9.0,0,0,0,0\n",  # out-of-order on purpose
            )
            # adj_factor doubles the close (exercises the adjust multiply)
            zf.writestr(
                "etf_data/adj/510300.SH.csv",
                "ts_code,trade_date,adj_factor\n"
                "510300.SH,20200103,2.0\n510300.SH,20200102,2.0\n",
            )
            zf.writestr(
                "etf_data/daily/518880.SH.csv",
                "ts_code,trade_date,pre_close,open,high,low,close,change,pct_chg,vol,amount\n"
                "518880.SH,20200102,1,1,1,1,5.0,0,0,0,0\n"
                "518880.SH,20200103,1,1,1,1,5.5,0,0,0,0\n",
            )  # no adj file -> factor 1

    def test_read_adjusted_close_from_zip_applies_factor_and_sorts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zp = str(Path(tmp) / "etf_data.zip")
            self._make_zip(zp)
            series = read_etf_adjusted_close_from_zip(zp, "510300.SH")
            self.assertEqual(series["2020-01-02"], 18.0)  # 9.0 * 2.0
            self.assertEqual(series["2020-01-03"], 20.0)  # 10.0 * 2.0
            bare = read_etf_adjusted_close_from_zip(zp, "518880.SH")
            self.assertEqual(bare["2020-01-02"], 5.0)  # no adj -> raw
            self.assertEqual(read_etf_adjusted_close_from_zip(zp, "999999.SZ"), {})

    def test_cache_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_etf_cache(tmp, "510300.SH", {"2020-01-03": 20.0, "2020-01-02": 18.0})
            self.assertEqual(
                load_etf_cache(tmp, "510300.SH"), {"2020-01-02": 18.0, "2020-01-03": 20.0}
            )
            self.assertEqual(load_etf_cache(tmp, "missing.SZ"), {})

    def test_panel_seeds_from_zip_then_uses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zp = str(Path(tmp) / "etf_data.zip")
            self._make_zip(zp)
            cache = str(Path(tmp) / "cache")
            panel = fetch_akshare_panel(["510300.SH", "518880.SH"], cache_dir=cache, zip_path=zp)
            # Common dates 01-02, 01-03 (518880 has both); aligned + sorted.
            self.assertEqual(panel["510300.SH"], [18.0, 20.0])
            self.assertEqual(panel["518880.SH"], [5.0, 5.5])
            # Cache now exists; a second call with no zip still works (cache-first).
            panel2 = fetch_akshare_panel(["510300.SH", "518880.SH"], cache_dir=cache)
            self.assertEqual(panel2["510300.SH"], [18.0, 20.0])

    def test_online_fetcher_appends_only_new_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = str(Path(tmp) / "cache")
            save_etf_cache(cache, "510300.SH", {"2020-01-02": 18.0, "2020-01-03": 20.0})
            save_etf_cache(cache, "518880.SH", {"2020-01-02": 5.0, "2020-01-03": 5.5})
            # Injected "online" tail: one stale date (ignored) + one new date (appended).
            tail = {"2020-01-03": 999.0, "2020-01-06": 21.0}
            panel = fetch_akshare_panel(
                ["510300.SH", "518880.SH"],
                cache_dir=cache,
                online=True,
                fetcher=lambda s: tail if s == "510300.SH" else {"2020-01-06": 6.0},
            )
            # 510300 got 01-06 appended, stale 01-03 not overwritten (999 ignored).
            self.assertEqual(load_etf_cache(cache, "510300.SH")["2020-01-03"], 20.0)
            self.assertEqual(panel["510300.SH"][-1], 21.0)

    def test_missing_everything_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                fetch_akshare_panel(["510300.SH"], cache_dir=str(Path(tmp) / "empty"))
            self.assertIn("akshare", str(ctx.exception))

    def test_default_universe_is_cross_asset(self) -> None:
        self.assertIn("518880.SH", AKSHARE_DEFAULT_UNIVERSE)  # gold
        self.assertIn("511010.SH", AKSHARE_DEFAULT_UNIVERSE)  # bond
        self.assertIn("513100.SH", AKSHARE_DEFAULT_UNIVERSE)  # foreign equity
        self.assertGreaterEqual(len(AKSHARE_DEFAULT_UNIVERSE), 6)

    def test_exclude_asset_classes_drops_bonds_keeps_rest(self) -> None:
        prices = {
            "510300.SH": [1.0, 1.1],  # cn_equity
            "518880.SH": [2.0, 2.1],  # gold
            "511010.SH": [3.0, 3.1],  # bond -> dropped
            "513100.SH": [4.0, 4.1],  # foreign_equity
        }
        kept = exclude_asset_classes(prices, ("bond",))
        self.assertNotIn("511010.SH", kept)
        self.assertIn("510300.SH", kept)
        self.assertIn("518880.SH", kept)
        self.assertEqual(exclude_asset_classes(prices, ()), prices)  # no-op

    def test_exclude_too_many_raises(self) -> None:
        prices = {"510300.SH": [1.0, 1.1], "511010.SH": [3.0, 3.1]}  # 1 equity + 1 bond
        with self.assertRaises(ValueError):
            exclude_asset_classes(prices, ("cn_equity",))  # leaves only the bond


class LoadPanelDispatchTest(unittest.TestCase):
    def test_synthetic(self) -> None:
        prices, desc = load_panel("synthetic", days=400, seed=3)
        self.assertTrue(desc.startswith("synthetic"))
        self.assertGreater(len(prices), 1)
        any_series = next(iter(prices.values()))
        self.assertEqual(len(any_series), 400)

    def test_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.csv"
            path.write_text("date,A,B\n2020-01-01,1,2\n2020-01-02,1.1,2.1\n", encoding="utf-8")
            prices, desc = load_panel("csv", prices_csv=str(path))
            self.assertEqual(prices["A"], [1.0, 1.1])
            self.assertTrue(desc.startswith("csv:"))

    def test_csv_without_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_panel("csv")

    def test_binance_dispatch_via_injected_fetcher(self) -> None:
        payloads = {
            "BTC/USDT": [
                [1577836800000, 1, 1, 1, 100.0, 0],
                [1577923200000, 1, 1, 1, 101.0, 0],
            ],
            "ETH/USDT": [
                [1577836800000, 1, 1, 1, 10.0, 0],
                [1577923200000, 1, 1, 1, 11.0, 0],
            ],
        }
        prices, desc = load_panel(
            "binance",
            tickers=["BTC/USDT", "ETH/USDT"],
            fetcher=lambda symbol: payloads[symbol],
        )
        self.assertEqual(prices["BTC/USDT"], [100.0, 101.0])
        self.assertTrue(desc.startswith("binance"))

    def test_openquant_dispatch_via_injected_fetcher(self) -> None:
        rows = {
            "000300": [("2020-01-02", 100.0), ("2020-01-03", 101.0)],
            "000012": [("2020-01-02", 5.0), ("2020-01-03", 5.5)],
        }
        prices, desc = load_panel(
            "openquant",
            tickers=["000300", "000012"],
            fetcher=lambda symbol: rows[symbol],
        )
        self.assertEqual(prices["000300"], [100.0, 101.0])
        self.assertTrue(desc.startswith("openquant"))

    def test_akshare_dispatch_via_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = str(Path(tmp) / "cache")
            save_etf_cache(cache, "510300.SH", {"2020-01-02": 18.0, "2020-01-03": 20.0})
            save_etf_cache(cache, "518880.SH", {"2020-01-02": 5.0, "2020-01-03": 5.5})
            prices, desc = load_panel(
                "akshare", tickers=["510300.SH", "518880.SH"], akshare_cache_dir=cache
            )
            self.assertEqual(prices["510300.SH"], [18.0, 20.0])
            self.assertTrue(desc.startswith("akshare"))

    def test_unknown_source_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_panel("bogus")


class TermStructureCarryTest(unittest.TestCase):
    def test_roll_yield_sign_and_annualization(self) -> None:
        # Backwardation: near 102 > far 100, 30 vs 60 dte -> positive, annualized over 30d gap.
        ry = annualized_roll_yield(102.0, 100.0, 30, 60)
        self.assertAlmostEqual(ry, (102.0 / 100.0 - 1.0) * 365.0 / 30.0, places=9)
        self.assertGreater(ry, 0.0)
        # Contango: near < far -> negative.
        self.assertLess(annualized_roll_yield(98.0, 100.0, 30, 60), 0.0)
        # Degenerate tenor gap / bad price -> None.
        self.assertIsNone(annualized_roll_yield(100.0, 100.0, 60, 60))
        self.assertIsNone(annualized_roll_yield(100.0, 0.0, 30, 60))

    def test_build_carry_picks_nearest_two_above_min_dte(self) -> None:
        contracts = {
            "F1": {"expire": "2024-01-20", "closes": {"2024-01-02": 105.0, "2024-01-03": 104.0}},
            "F2": {"expire": "2024-02-20", "closes": {"2024-01-02": 100.0, "2024-01-03": 100.0}},
            "F3": {"expire": "2024-03-20", "closes": {"2024-01-02": 99.0}},
        }
        carry = build_term_structure_carry(contracts, ["2024-01-02", "2024-01-03"], min_dte_days=5)
        # 01-02: near F1(18d,105) vs far F2(49d,100) -> backwardation positive
        self.assertIn("2024-01-02", carry)
        self.assertGreater(carry["2024-01-02"], 0.0)

    def test_build_carry_drops_about_to_deliver_front(self) -> None:
        # F1 has only 3 dte (< min_dte 10) -> skipped; only F2,F3 remain -> they set the curve.
        contracts = {
            "F1": {"expire": "2024-01-05", "closes": {"2024-01-02": 200.0}},
            "F2": {"expire": "2024-02-20", "closes": {"2024-01-02": 100.0}},
            "F3": {"expire": "2024-03-20", "closes": {"2024-01-02": 101.0}},
        }
        carry = build_term_structure_carry(contracts, ["2024-01-02"], min_dte_days=10)
        # near=F2(100), far=F3(101) -> contango (negative), F1's 200 ignored
        self.assertLess(carry["2024-01-02"], 0.0)

    def test_align_prices_and_carry_lays_carry_on_price_axis(self) -> None:
        prices, carry = align_prices_and_carry(
            {"A": {"d1": 10.0, "d2": 11.0, "d3": 12.0}, "B": {"d1": 5.0, "d2": 5.5, "d3": 6.0}},
            {"A": {"d2": 0.1}, "B": {"d1": -0.2, "d3": 0.3}},
        )
        self.assertEqual(prices["A"], [10.0, 11.0, 12.0])
        self.assertEqual(carry["A"], [None, 0.1, None])  # carry None where missing
        self.assertEqual(carry["B"], [-0.2, None, 0.3])


if __name__ == "__main__":
    unittest.main()
