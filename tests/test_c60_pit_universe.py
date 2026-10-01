import datetime as dt
import io
import math
import random
import unittest
import zipfile

from qount.dual_engine.contracts import C60_SYMBOLS
from qount.research import c60_cost_study as study
from qount.research import c60_pit_universe as pit

START = dt.date(2020, 8, 28)  # index 99 == FIRST_DECISION, same as the frozen panel


def _raw(extra=None, seed=5):
    rng = random.Random(seed)
    days = (dt.date.fromisoformat(pit.EVAL_END) - START).days + 1
    out = {}
    for offset, symbol in enumerate(list(C60_SYMBOLS) + list(extra or ())):
        price, drift = 40.0 + offset, (offset - 4) * 0.0008
        rows = {}
        for day in range(days):
            price *= math.exp(drift + rng.gauss(0.0, 0.03))
            rows[(START + dt.timedelta(days=day)).isoformat()] = (price, 1e6 * (1 + offset))
        out[symbol] = rows
    return out


class ParsingTests(unittest.TestCase):
    def test_ms_and_us_timestamps_and_header(self):
        text = ("open_time,o,h,l,c,v,ct,qv,n,tb,tq,i\n"
                "1577836800000,1,1,1,7200.5,1,0,123.0,0,0,0,0\n"
                "1740787200000000,1,1,1,84000,1,0,9.5,0,0,0,0\n")
        rows = pit.parse_kline_csv(text)
        self.assertEqual(rows, {"2020-01-01": (7200.5, 123.0), "2025-03-01": (84000.0, 9.5)})

    def test_eligibility_excludes_stables_fiat_and_leveraged(self):
        names = ["BTCUSDT", "BTCUPUSDT", "USDCUSDT", "EURUSDT", "JUPUSDT", "SOLUSDT", "USDTTRY"]
        kept = [s for s in names if pit.eligible_symbol(s, names)]
        self.assertEqual(kept, ["BTCUSDT", "JUPUSDT", "SOLUSDT"])  # JUP has no JUSDT → not leveraged

    def test_fetch_symbol_hashes_files(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("X-1d-2021-01.csv", "1609459200000,1,1,1,2.0,1,0,5.0,0,0,0,0\n")
        blob = buf.getvalue()

        def getter(url):
            if "s3" in url:
                return (b"<ListBucketResult><Key>data/spot/monthly/klines/XUSDT/1d/XUSDT-1d-2021-01.zip</Key>"
                        b"<Key>data/spot/monthly/klines/XUSDT/1d/XUSDT-1d-2021-01.zip.CHECKSUM</Key>"
                        b"<IsTruncated>false</IsTruncated></ListBucketResult>")
            return blob

        data = pit.fetch_symbol("XUSDT", getter)
        self.assertEqual(data["rows"], {"2021-01-01": [2.0, 5.0]})
        self.assertEqual(list(data["files"]), ["2021-01"])


class EngineTests(unittest.TestCase):
    def test_gap_splits_reused_ticker(self):
        raw = _raw(["LUNAUSDT"])
        luna = raw["LUNAUSDT"]
        for day in [d for d in luna if "2022-05-14" <= d <= "2022-05-30"]:
            del luna[day]
        _, assets = pit.build_assets(raw)
        ids = sorted(a for a in assets if a.startswith("LUNAUSDT"))
        self.assertEqual(ids, ["LUNAUSDT@2020-08-28", "LUNAUSDT@2022-05-31"])

    def test_survivor_mode_matches_frozen_engine(self):
        raw = _raw()
        axis, assets = pit.build_assets(raw)
        mine = pit.simulate(axis, assets, pit.target_path(axis, assets, pit.survivor_universe)[0])
        panel, _ = study.build_panel({s: {d: v[0] for d, v in rows.items()} for s, rows in raw.items()})
        ref = study.simulate(panel, study.target_path(panel, mode="research_monthly"), cost_bps=pit.COST_BPS,
                             start_date=pit.FIRST_DECISION)
        self.assertEqual(tuple(mine["dates"]), ref.dates)
        for a, b in zip(mine["returns"], ref.returns):
            self.assertAlmostEqual(a, b, places=12)
        self.assertAlmostEqual(mine["turnover"], ref.turnover, places=9)

    def test_delisted_asset_is_sold_at_last_close(self):
        raw = _raw(["DEADUSDT"])
        dead = raw["DEADUSDT"]
        price = 1.0
        for i, day in enumerate(sorted(dead)):  # strong uptrend, top volume, then disappears
            price *= 1.02
            dead[day] = (price, 1e12)
            raw["BTCUSDT"][day] = (100.0 * 1.01 ** i, 1e9)  # BTC gate open
        last = "2022-06-15"
        for day in [d for d in dead if d > last]:
            del dead[day]
        axis, assets = pit.build_assets(raw)
        targets, universes = pit.target_path(axis, assets, pit.pit_universe)
        t_last = axis.index(last)
        self.assertTrue(any("DEADUSDT" in targets[t] for t in range(t_last - 20, t_last)))
        self.assertNotIn("DEADUSDT", targets[t_last])
        self.assertTrue(all("DEADUSDT" not in w for t, w in targets.items() if t >= t_last))
        sim = pit.simulate(axis, assets, targets)  # must not index past the asset's last close
        self.assertEqual(len(sim["dates"]), len(targets))
        self.assertTrue(all(len(m) <= pit.TOP_N + 2 for m in universes.values()))

    def test_pit_universe_ranks_by_volume_and_keeps_anchors(self):
        raw = _raw(["AAAUSDT", "BBBUSDT"])
        axis, assets = pit.build_assets(raw)
        members = pit.pit_universe(assets, axis.index("2023-01-31"))
        self.assertIn("BTCUSDT", members)
        self.assertIn("PAXGUSDT", members)
        self.assertEqual(len(members), 10)
        self.assertIn("BBBUSDT", members)  # highest synthetic volume
        self.assertNotIn("ETHUSDT", members)  # lowest non-anchor volume drops out

    def test_run_guards_and_windows(self):
        out = pit.run(_raw(["AAAUSDT"]))
        self.assertFalse(out["guards"]["orders_authorized"])
        self.assertEqual(set(out["variants"]), {"pit_c60_v2", "survivor_c60_v2", "btc_static_vol_matched",
                                                "btc_only_c60_gate"})
        self.assertEqual(out["variants"]["pit_c60_v2"]["first"], "2020-12-06")


if __name__ == "__main__":
    unittest.main()
