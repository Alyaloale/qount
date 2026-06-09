from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qount.l6_microstructure import BookSnapshot
from qount.l6_microstructure import TradeEvent
from qount.l6_microstructure import _depth_imbalance
from qount.l6_microstructure import _l1_ofi
from qount.l6_microstructure import _micro_price_dev
from qount.l6_microstructure import as_of_price
from qount.l6_microstructure import evaluate_instrument
from qount.l6_microstructure import exchange_of
from qount.l6_microstructure import forward_return
from qount.l6_microstructure import mid_price_series
from qount.l6_microstructure import parse_orders
from qount.l6_microstructure import parse_session_time_to_ms
from qount.l6_microstructure import parse_snapshots
from qount.l6_microstructure import parse_trades
from qount.l6_microstructure import run_l6_microstructure_ic_scan


def _snap(t: int, mid: float, bidq: int, askq: int, tick: float = 0.005) -> BookSnapshot:
    bid1 = round(mid - tick, 4)
    ask1 = round(mid + tick, 4)
    return BookSnapshot(
        time_ms=t, last=mid,
        bid_px=(bid1,) + (0.0,) * 9, bid_qty=(bidq,) + (0,) * 9,
        ask_px=(ask1,) + (0.0,) * 9, ask_qty=(askq,) + (0,) * 9,
    )


def _synth_instrument(n_sec: int = 60, block: int = 10, alpha: float = 0.002):
    """Build an instrument where depth imbalance predicts forward mid moves."""
    snaps = []
    mid = 10.0
    for i in range(n_sec):
        d = 1 if (i // block) % 2 == 0 else -1
        bidq = round(1000 * (1 + 0.5 * d))
        askq = round(1000 * (1 - 0.5 * d))
        snaps.append(_snap(i * 1000, mid, bidq, askq))
        mid = mid * (1 + alpha * d)
    return snaps, []


ORDER_HEADER = "万得代码,交易所代码,自然日,时间,委托编号,交易所委托号,委托类型,委托代码,委托价格,委托数量,"
TRADE_HEADER = "万得代码,交易所代码,自然日,时间,成交编号,成交代码,委托代码,BS标志,成交价格,成交数量,叫卖序号,叫买序号,"


def _quote_header() -> str:
    cols = ["万得代码", "交易所代码", "自然日", "时间", "成交价"]
    cols += [f"申卖价{i}" for i in range(1, 11)]
    cols += [f"申卖量{i}" for i in range(1, 11)]
    cols += [f"申买价{i}" for i in range(1, 11)]
    cols += [f"申买量{i}" for i in range(1, 11)]
    return ",".join(cols)


def _quote_row(code: str, t: int, last: int, bid1: int, bidq1: int, ask1: int, askq1: int) -> str:
    vals = [code, code.split(".")[0], "20260407", str(t), str(last)]
    ask_px = [str(ask1)] + ["0"] * 9
    ask_qty = [str(askq1)] + ["0"] * 9
    bid_px = [str(bid1)] + ["0"] * 9
    bid_qty = [str(bidq1)] + ["0"] * 9
    return ",".join(vals + ask_px + ask_qty + bid_px + bid_qty)


def _write(tmp: Path, name: str, lines: list[str]) -> Path:
    path = tmp / name
    path.write_text("\n".join(lines) + "\n", encoding="gbk")
    return path


class TimeAndCodeTest(unittest.TestCase):
    def test_session_time_to_ms(self) -> None:
        self.assertEqual(parse_session_time_to_ms("91500030"), 33300030)
        self.assertEqual(parse_session_time_to_ms(150000000), 54000000)
        self.assertEqual(parse_session_time_to_ms("93000000"), 34200000)

    def test_exchange_of(self) -> None:
        self.assertEqual(exchange_of("000001.SZ"), "SZ")
        self.assertEqual(exchange_of("600000.SH"), "SH")
        with self.assertRaises(ValueError):
            exchange_of("AAPL")


class ShenzhenParseTest(unittest.TestCase):
    def test_orders_all_adds_with_direction(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            p = _write(tmp, "逐笔委托.csv", [
                ORDER_HEADER,
                "000001.SZ,000001,20260407,93000000,1,10,0,B,111200,100,",
                "000001.SZ,000001,20260407,93000100,2,11,0,S,111300,200,",
            ])
            orders = parse_orders(p)
        self.assertEqual([o.kind for o in orders], ["add", "add"])
        self.assertEqual([o.side for o in orders], ["B", "S"])
        self.assertAlmostEqual(orders[0].price, 11.12)
        self.assertEqual(orders[1].qty, 200)

    def test_trades_split_from_cancels(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            p = _write(tmp, "逐笔成交.csv", [
                TRADE_HEADER,
                # real trade: 成交代码=0, BS标志=B (buyer-initiated)
                "000001.SZ,000001,20260407,93000000,500,0,0,B,111200,2300,6856,21415,",
                # cancel of a buy order: 成交代码=C, 叫买序号>0
                "000001.SZ,000001,20260407,93000050,501,C,0, ,0,100,0,776,",
                # cancel of a sell order: 成交代码=C, 叫卖序号>0
                "000001.SZ,000001,20260407,93000060,502,C,0, ,0,400,888,0,",
            ])
            trades, cancels = parse_trades(p)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].aggressor, "B")
        self.assertAlmostEqual(trades[0].price, 11.12)
        self.assertEqual(trades[0].qty, 2300)
        self.assertEqual([c.kind for c in cancels], ["cancel", "cancel"])
        self.assertEqual([c.side for c in cancels], ["B", "S"])
        self.assertEqual(cancels[0].qty, 100)
        self.assertEqual(cancels[1].qty, 400)


class ShanghaiParseTest(unittest.TestCase):
    def test_orders_add_delete_model(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            p = _write(tmp, "逐笔委托.csv", [
                ORDER_HEADER,
                "600000.SH,600000,20260407,93000000,1,10,A,B,71500,100,",
                "600000.SH,600000,20260407,93000100,2,11,D,B,71500,100,",
                "600000.SH,600000,20260407,93000200,3,12,S,S,71600,300,",
            ])
            orders = parse_orders(p)
        self.assertEqual([o.kind for o in orders], ["add", "cancel", "other"])
        self.assertEqual([o.side for o in orders], ["B", "B", "S"])

    def test_mislabeled_suffix_detected_from_content(self) -> None:
        # 588000 etc. are SH instruments stored with a .SZ suffix in this dataset;
        # semantics must come from the A/D content, not the suffix.
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            p = _write(tmp, "逐笔委托.csv", [
                ORDER_HEADER,
                "588000.SZ,588000,20260407,93000000,1,10,A,B,12000,100,",
                "588000.SZ,588000,20260407,93000100,2,11,D,B,12000,100,",
                "588000.SZ,588000,20260407,93000200,3,12,S,S,12010,300,",
            ])
            orders = parse_orders(p)
        self.assertEqual([o.kind for o in orders], ["add", "cancel", "other"])

    def test_trades_no_cancels(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            p = _write(tmp, "逐笔成交.csv", [
                TRADE_HEADER,
                "600000.SH,600000,20260407,93000000,1,,0,B,71500,500,10,20,",
                "600000.SH,600000,20260407,93000100,2,,0,S,71400,300,30,40,",
            ])
            trades, cancels = parse_trades(p)
        self.assertEqual(len(trades), 2)
        self.assertEqual(cancels, [])
        self.assertEqual([t.aggressor for t in trades], ["B", "S"])


class SnapshotAndAlignmentTest(unittest.TestCase):
    def test_snapshot_mid_two_sided_vs_one_sided(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            p = _write(tmp, "行情.csv", [
                _quote_header(),
                _quote_row("159919.SZ", 93000000, 40000, 39990, 1000, 40010, 800),  # two-sided
                _quote_row("159919.SZ", 93000300, 40050, 0, 0, 40060, 500),          # one-sided (no bid)
            ])
            snaps = parse_snapshots(p)
        self.assertEqual(len(snaps), 2)
        self.assertAlmostEqual(snaps[0].mid, (3.999 + 4.001) / 2)
        self.assertIsNone(snaps[1].mid)
        times, mids = mid_price_series(snaps)
        self.assertEqual(times, [parse_session_time_to_ms(93000000)])
        self.assertEqual(len(mids), 1)

    def test_as_of_price_no_lookahead(self) -> None:
        times = [100, 200, 300]
        mids = [10.0, 11.0, 12.0]
        self.assertIsNone(as_of_price(times, mids, 50))      # before first
        self.assertEqual(as_of_price(times, mids, 100), 10.0)
        self.assertEqual(as_of_price(times, mids, 150), 10.0)  # uses <=t, not future 11.0
        self.assertEqual(as_of_price(times, mids, 250), 11.0)
        self.assertEqual(as_of_price(times, mids, 999), 12.0)

    def test_forward_return(self) -> None:
        times = [100, 200, 300, 400]
        mids = [10.0, 10.5, 11.0, 11.0]
        # anchor at t0=150 -> 10.0; t0+h=350 -> 11.0 -> +10%
        self.assertAlmostEqual(forward_return(times, mids, 150, 200), 0.10)
        # horizon extends past last observation -> not realizable
        self.assertIsNone(forward_return(times, mids, 300, 200))
        # anchor before first observation -> None
        self.assertIsNone(forward_return(times, mids, 50, 100))
        with self.assertRaises(ValueError):
            forward_return(times, mids, 100, 0)


class FeatureMathTest(unittest.TestCase):
    def test_l1_ofi(self) -> None:
        prev = _snap(0, 10.0, 100, 100)
        # bid price up (buy pressure) + ask qty pulled: OFI positive
        cur = BookSnapshot(time_ms=1, last=10.0,
                           bid_px=(9.999,) + (0.0,) * 9, bid_qty=(200,) + (0,) * 9,
                           ask_px=(10.006,) + (0.0,) * 9, ask_qty=(50,) + (0,) * 9)
        prev = BookSnapshot(time_ms=0, last=10.0,
                            bid_px=(9.998,) + (0.0,) * 9, bid_qty=(100,) + (0,) * 9,
                            ask_px=(10.005,) + (0.0,) * 9, ask_qty=(100,) + (0,) * 9)
        # bid: cb(9.999)>pb(9.998) -> +cur.bidq 200; ask: ca(10.006)>pa(10.005) -> -(ca>=pa)*prev.askq = -100
        self.assertEqual(_l1_ofi(prev, cur), 200.0 - (-100.0))

    def test_depth_imbalance(self) -> None:
        snap = _snap(0, 10.0, 1500, 500)
        self.assertAlmostEqual(_depth_imbalance(snap, 5), (1500 - 500) / 2000)
        self.assertEqual(_depth_imbalance(_snap(0, 10.0, 0, 0), 5), 0.0)

    def test_micro_price_dev_sign(self) -> None:
        # more bid qty -> micro price tilts toward ask -> positive deviation
        self.assertGreater(_micro_price_dev(_snap(0, 10.0, 2000, 200)), 0.0)
        self.assertLess(_micro_price_dev(_snap(0, 10.0, 200, 2000)), 0.0)


class EvaluateInstrumentTest(unittest.TestCase):
    def test_predictive_depth_imbalance_gives_positive_ic(self) -> None:
        snaps, trades = _synth_instrument()
        res = evaluate_instrument(snaps, trades, horizons_ms=(5000,))
        ic = res["depth_imbalance"][5000]["rank_ic"]
        self.assertIsNotNone(ic)
        self.assertGreater(ic, 0.5)
        # long-short on the (correct-sign) feature should be gross-positive
        self.assertGreater(res["depth_imbalance"][5000]["gross_mean"], 0.0)

    def test_random_feature_no_spurious_ic(self) -> None:
        # flat book imbalance with a drifting mid -> depth imbalance carries no info
        snaps = [_snap(i * 1000, 10.0 * (1.0 + 0.001 * i), 1000, 1000) for i in range(60)]
        res = evaluate_instrument(snaps, [], horizons_ms=(5000,))
        # constant imbalance (=0) -> spearman undefined/None or ~0, never strongly positive
        ic = res["depth_imbalance"].get(5000, {}).get("rank_ic")
        self.assertTrue(ic is None or abs(ic) < 0.3)


def _tr(hhmmss: int, qty: int, side: str) -> TradeEvent:
    return TradeEvent(time_ms=parse_session_time_to_ms(hhmmss), price=10.0, qty=qty,
                      aggressor=side, buy_seq=0, sell_seq=0)


class DailyFlowFeaturesTest(unittest.TestCase):
    def test_aggressive_and_large_ofi(self) -> None:
        from qount.l6_microstructure import daily_flow_features
        trades = [_tr(100000000, 100, "S") for _ in range(9)] + [_tr(100000000, 1000, "B")]
        snaps = [_snap(parse_session_time_to_ms(93000000), 10.0, 100, 100),   # 09:30 open
                 _snap(parse_session_time_to_ms(150000000), 10.5, 100, 100)]  # 15:00 close
        f = daily_flow_features(snaps, trades, [])
        self.assertAlmostEqual(f["aggressive_ofi"], (1000 - 900) / 1900)
        self.assertAlmostEqual(f["large_aggr_ofi"], 1.0)  # only the 1000-lot is >= p90
        self.assertEqual(f["day_open"], 10.0)   # first mid = open
        self.assertEqual(f["day_close"], 10.5)  # last mid = close
        # quoted spread: 0.01 abs at mid 10.0 and 10.5 -> mean relative spread in bps
        self.assertAlmostEqual(f["quoted_spread_bps"], (0.01 / 10.0 + 0.01 / 10.5) / 2 * 1e4, places=3)

    def test_late_minus_early_and_close_auction(self) -> None:
        from qount.l6_microstructure import daily_flow_features
        trades = [_tr(94500000, 200, "S"),   # 09:45 early -> sell
                  _tr(144500000, 200, "B"),  # 14:45 late  -> buy
                  _tr(145800000, 100, "B")]  # 14:58 close auction -> buy
        f = daily_flow_features([], trades, [])
        self.assertAlmostEqual(f["late_minus_early_flow"], 1.0 - (-1.0))
        self.assertAlmostEqual(f["close_auction_imbalance"], 1.0)

    def test_cancel_imbalance_and_empty(self) -> None:
        from qount.l6_microstructure import daily_flow_features
        from qount.l6_microstructure import OrderEvent
        cancels = [OrderEvent(0, "B", 0.0, 300, "cancel", "C"),
                   OrderEvent(0, "S", 0.0, 100, "cancel", "C")]
        f = daily_flow_features([], [_tr(100000000, 100, "B")], cancels)
        self.assertAlmostEqual(f["cancel_imbalance"], (300 - 100) / 400)
        self.assertIsNone(daily_flow_features([], [], []))  # halted/empty -> None

    def test_panel_skips_missing_and_halted(self) -> None:
        from qount.l6_microstructure import compute_daily_feature_panel
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            sd = tmp / "000001.SZ"
            sd.mkdir()
            _write(sd, "行情.csv", [_quote_header(),
                   _quote_row("000001.SZ", 150000000, 105000, 104990, 100, 105010, 100)])
            _write(sd, "逐笔成交.csv", [TRADE_HEADER,
                   "000001.SZ,000001,20260407,100000000,1,0,0,B,105000,300,0,0,",
                   "000001.SZ,000001,20260407,100001000,2,0,0,S,105000,100,0,0,",
                   "000001.SZ,000001,20260407,100002000,3,C,0, ,0,200,0,5,"])  # buy cancel
            _write(sd, "逐笔委托.csv", [ORDER_HEADER])
            panel = compute_daily_feature_panel(tmp, ["000001.SZ", "600999.SH"])  # SH missing
        self.assertIn("000001.SZ", panel)
        self.assertNotIn("600999.SH", panel)
        self.assertAlmostEqual(panel["000001.SZ"]["aggressive_ofi"], (300 - 100) / 400)


class ScanStructureTest(unittest.TestCase):
    def test_scan_returns_grid_and_decision(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            for sym in ("159001.SZ", "159002.SZ"):
                sd = tmp / sym
                sd.mkdir()
                snaps, _ = _synth_instrument()
                # write minimal 行情.csv + empty trade/order files via parsers' format
                rows = [_quote_header()]
                for s in snaps:
                    rows.append(_quote_row(sym, s.time_ms, int(s.last * 10000),
                                           int(s.bid_px[0] * 10000), s.bid_qty[0],
                                           int(s.ask_px[0] * 10000), s.ask_qty[0]))
                (sd / "行情.csv").write_text("\n".join(rows) + "\n", encoding="gbk")
                (sd / "逐笔成交.csv").write_text(TRADE_HEADER + "\n", encoding="gbk")
            res = run_l6_microstructure_ic_scan(tmp, ["159001.SZ", "159002.SZ"], horizons_ms=(5000,))
        self.assertEqual(res["version"], "l6_microstructure_v1")
        self.assertTrue(res["ic_horizon_grid"])
        # 5000ms is sub-minute -> not actionable -> no pass
        self.assertIn(res["decision"], (
            "l6_microstructure_no_actionable_signal",
            "l6_latency_wall_subminute_only",
        ))


class DailyD1Test(unittest.TestCase):
    def _panels(self, n_days: int = 4, n_etf: int = 20, with_stocks: bool = False):
        from qount.l6_microstructure import DAILY_FEATURES
        syms = [f"159{i:03d}.SZ" for i in range(1, n_etf + 1)]
        if with_stocks:
            syms += [f"000{i:03d}.SZ" for i in range(1, 6)]
        panels: dict[str, dict[str, dict]] = {}
        close = {s: 10.0 for s in syms}
        half = len(syms) / 2.0
        for d in range(n_days):
            date = f"2026041{d}"  # 20260410..20260413, lexically sortable
            day = {}
            for idx, s in enumerate(syms):
                day[s] = {fn: (idx - half) / len(syms) for fn in DAILY_FEATURES}
                day[s]["day_close"] = close[s]
                day[s]["day_volume"] = (idx + 1) * 1.0e6  # turnover monotone in idx, stable ranking
                day[s]["n_trades"] = 1000.0
            panels[date] = day
            for idx, s in enumerate(syms):  # next close: return monotone in feature(idx)
                close[s] = close[s] * (1 + 0.002 * (idx - half))
        return panels

    def test_etf_code_detection(self) -> None:
        from qount.l6_microstructure import is_etf_code
        for c in ("159001.SZ", "510300.SH", "588000.SZ", "563000.SH", "512880.SH"):
            self.assertTrue(is_etf_code(c), c)
        for c in ("000001.SZ", "600000.SH", "300750.SZ", "688981.SH"):
            self.assertFalse(is_etf_code(c), c)

    def test_d1_positive_ic_and_etf_universe_filter(self) -> None:
        from qount.l6_microstructure import evaluate_l6_daily_d1
        res = evaluate_l6_daily_d1(self._panels(with_stocks=True), universe="etf", min_cross_section=5)
        self.assertEqual(res["n_cross_sections"], 3)  # 4 days, holding=1
        best = res["best_feature"]
        self.assertGreater(best["mean_rank_ic"], 0.9)       # synthetic monotone -> IC~1
        self.assertEqual(best["ic_sign_stability"], 1.0)
        self.assertGreater(best["ls_decile_mean"], 0.0)
        # etf universe excludes the 5 stocks
        self.assertEqual(res["effective_breadth"]["symbol_count"], 20)

    def test_d1_universe_all_includes_stocks(self) -> None:
        from qount.l6_microstructure import evaluate_l6_daily_d1
        res = evaluate_l6_daily_d1(self._panels(with_stocks=True), universe="all", min_cross_section=5)
        self.assertEqual(res["effective_breadth"]["symbol_count"], 25)

    def test_d1_active_top_n_limits_universe(self) -> None:
        from qount.l6_microstructure import evaluate_l6_daily_d1
        res = evaluate_l6_daily_d1(self._panels(n_etf=20), universe="etf",
                                   active_top_n=8, min_cross_section=5)
        self.assertEqual(res["effective_breadth"]["symbol_count"], 8)


class DailyD2Test(unittest.TestCase):
    def test_partial_corr(self) -> None:
        from qount.l6_microstructure import _partial_corr
        self.assertAlmostEqual(_partial_corr(0.5, 0.0, 0.0), 0.5)   # control unrelated -> unchanged
        self.assertLess(abs(_partial_corr(0.5, 0.9, 0.5)), 0.5)     # control collinear -> shrinks
        self.assertIsNone(_partial_corr(0.5, 1.0, 0.5))             # degenerate denom -> None

    def test_d2_incremental_when_target_independent_of_trailing(self) -> None:
        # close_auction is i.i.d. each day and drives next-day return; trailing return
        # carries the PREVIOUS day's target, so target is independent of trailing -> incremental.
        from qount.l6_microstructure import DAILY_FEATURES, evaluate_l6_daily_d2
        import random
        rng = random.Random(42)
        syms = [f"159{i:03d}.SZ" for i in range(1, 21)]
        panels: dict = {}
        close = {s: 10.0 for s in syms}
        for d in range(8):
            date = f"2026041{d}"
            tgt = {s: rng.uniform(-1.0, 1.0) for s in syms}
            day = {}
            for s in syms:
                day[s] = {fn: 0.0 for fn in DAILY_FEATURES}
                day[s]["close_auction_imbalance"] = tgt[s]
                day[s]["day_close"] = close[s]
                day[s]["day_volume"] = 1.0e6
                day[s]["n_trades"] = 1000.0
            panels[date] = day
            for s in syms:
                close[s] = close[s] * (1 + 0.01 * tgt[s])  # next-day return driven by target[T]
        res = evaluate_l6_daily_d2(panels, target_feature="close_auction_imbalance", universe="etf", min_cross_section=5)
        self.assertEqual(res["decision"], "l6_d2_incremental")
        self.assertGreater(res["partial_ic_controlling_pricevol"]["mean"], 0.7)
        self.assertGreater(res["partial_to_raw_ratio"], 0.7)

    def test_d2_structure_and_degenerate(self) -> None:
        # D1's synthetic panels have target perfectly collinear with trailing return
        # (both monotone in idx) -> partial degenerate (None) -> no_data, but keys present.
        from qount.l6_microstructure import evaluate_l6_daily_d2
        panels = DailyD1Test()._panels(n_days=5, n_etf=20)
        res = evaluate_l6_daily_d2(panels, universe="etf", min_cross_section=5)
        for k in ("raw_ic", "partial_ic_controlling_pricevol", "baseline_pricevol_ic",
                  "feature_vs_baseline_corr", "partial_to_raw_ratio", "decision"):
            self.assertIn(k, res)
        self.assertIsNotNone(res["raw_ic"])


class DailyD4Test(unittest.TestCase):
    def test_d4_composite_beats_requirement_on_synthetic(self) -> None:
        from qount.l6_microstructure import evaluate_l6_daily_d4
        panels = DailyD1Test()._panels(n_days=5, n_etf=20)  # all features monotone in idx -> composite IC~1
        res = evaluate_l6_daily_d4(panels, universe="etf", min_cross_section=5)
        self.assertGreater(res["composite_mean_ic"], 0.9)
        self.assertEqual(res["composite_ic_sign_stability"], 1.0)
        self.assertIsNotNone(res["required_ic_breadth_adjusted"])
        self.assertEqual(res["decision"], "l6_d4_breaks_requirement")

    def test_d4_ic_weighted_mode(self) -> None:
        from qount.l6_microstructure import evaluate_l6_daily_d4
        panels = DailyD1Test()._panels(n_days=5, n_etf=20)
        res = evaluate_l6_daily_d4(panels, universe="etf", weight_mode="ic_weighted", min_cross_section=5)
        self.assertEqual(res["weight_mode"], "ic_weighted")
        self.assertGreater(res["composite_mean_ic"], 0.9)

    def test_d4_purged_cv_oos_holds_on_stable_synthetic(self) -> None:
        # stable monotone signal -> OOS (leave-one-section-out) composite IC also ~1
        from qount.l6_microstructure import evaluate_l6_daily_d4
        panels = DailyD1Test()._panels(n_days=6, n_etf=20)
        res = evaluate_l6_daily_d4(panels, universe="etf", weight_mode="ic_weighted",
                                   purged_cv=True, min_cross_section=5)
        self.assertTrue(res["purged_cv"])
        self.assertGreater(res["oos_composite_ic"], 0.9)
        self.assertGreater(res["oos_to_in_sample_ratio"], 0.7)


class T0ExecTest(unittest.TestCase):
    def _panels(self, fn, n_days: int = 5, n_etf: int = 40, spread_bps: float | None = None):
        """fn(pair_index, x) -> (r_on, r_id); builds ETF panels with day_open/day_close.

        Pair i (dates[i]->dates[i+1]) realizes overnight r_on and intraday r_id for
        each symbol's signal x in [-1, 1]; signal = close_auction_imbalance[dates[i]].
        ``spread_bps`` sets quoted_spread_bps on every (ETF, day) for the empirical
        cost path; left unset, the evaluator falls back to flat cost.
        """
        from qount.l6_microstructure import DAILY_FEATURES
        syms = [f"159{i:03d}.SZ" for i in range(1, n_etf + 1)]
        half = (n_etf - 1) / 2.0
        xval = {s: (i - half) / half for i, s in enumerate(syms)}
        panels: dict = {}
        prev_close = {s: 100.0 for s in syms}
        for d in range(n_days):
            date = f"202604{10 + d:02d}"
            day = {}
            for s in syms:
                if d == 0:
                    op = cl = prev_close[s]
                else:
                    r_on, r_id = fn(d - 1, xval[s])
                    op = prev_close[s] * (1 + r_on)
                    cl = op * (1 + r_id)
                vec = {f: 0.0 for f in DAILY_FEATURES}
                vec["close_auction_imbalance"] = xval[s]
                vec["day_open"] = op
                vec["day_close"] = cl
                vec["day_volume"] = 1.0e6
                vec["n_trades"] = 1000.0
                if spread_bps is not None:
                    vec["quoted_spread_bps"] = spread_bps
                day[s] = vec
                prev_close[s] = cl
            panels[date] = day
        return panels

    def test_capturable_when_reversal_is_intraday(self) -> None:
        from qount.l6_microstructure import evaluate_l6_t0_execution
        ks = [0.02, 0.025, 0.03, 0.035]
        res = evaluate_l6_t0_execution(
            self._panels(lambda i, x: (0.0, -ks[i] * x)),  # reversal lives in the intraday leg
            universe="etf", min_cross_section=5, round_trip_cost_bps=6.0,
        )
        self.assertEqual(res["decision"], "l6_t0_capturable_net_positive")
        self.assertLess(res["ic_by_horizon"]["intraday"]["mean"], 0.0)        # reversal
        self.assertAlmostEqual(res["capturable_intraday_fraction"], 1.0, places=2)
        self.assertGreater(res["intraday_net_of_cost"]["mean"], 0.0)

    def test_dead_when_reversal_is_overnight(self) -> None:
        from qount.l6_microstructure import evaluate_l6_t0_execution
        ks = [0.02, 0.025, 0.03, 0.035]
        res = evaluate_l6_t0_execution(  # reversal in overnight gap; intraday is tiny momentum
            self._panels(lambda i, x: (-ks[i] * x, 0.0002 * x)),
            universe="etf", min_cross_section=5, round_trip_cost_bps=6.0,
        )
        self.assertEqual(res["decision"], "l6_t0_dead_reversal_is_overnight")
        self.assertLess(res["capturable_intraday_fraction"], 0.34)

    def test_empirical_taker_capturable_when_spread_small(self) -> None:
        from qount.l6_microstructure import evaluate_l6_t0_execution
        ks = [0.02, 0.025, 0.03, 0.035]
        res = evaluate_l6_t0_execution(
            self._panels(lambda i, x: (0.0, -ks[i] * x), spread_bps=1.0),  # intraday reversal, 1bp spread
            universe="etf", min_cross_section=5, commission_roundtrip_bps=2.5,
        )
        self.assertEqual(res["decision"], "l6_t0_capturable_taker_net_positive")
        self.assertAlmostEqual(res["traded_tail_spread_bps"], 1.0, places=2)
        self.assertGreater(res["intraday_net_taker_empirical"]["mean"], 0.0)

    def test_empirical_auction_only_when_spread_large(self) -> None:
        from qount.l6_microstructure import evaluate_l6_t0_execution
        ks = [0.02, 0.025, 0.03, 0.035]
        res = evaluate_l6_t0_execution(  # big spread kills taker but auction-fill still nets positive
            self._panels(lambda i, x: (0.0, -ks[i] * x), spread_bps=500.0),
            universe="etf", min_cross_section=5, commission_roundtrip_bps=2.5,
        )
        self.assertEqual(res["decision"], "l6_t0_capturable_auction_fill_only")
        self.assertLess(res["intraday_net_taker_empirical"]["mean"], 0.0)
        self.assertGreater(res["intraday_net_auction_fill"]["mean"], 0.0)


if __name__ == "__main__":
    unittest.main()
