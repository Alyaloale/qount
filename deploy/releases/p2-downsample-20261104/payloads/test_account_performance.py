"""Real return accounting: contributions, missing coverage and immutable inputs."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from qount.operations.account_assets import append_asset_history
from qount.operations.account_performance import build_performance, read_account_performance
from qount.operations.account_trades import persist_trade_records, strategy_accounting, read_trade_records
from qount.execution.binance_usdm import BinanceExecutionStore
from tests.test_account_trades import Exchange, collect_trade_records, NOW, fill, income

START = int(datetime(2026,10,16,10,tzinfo=timezone.utc).timestamp()*1000)


def observation(minutes, wallet, equity=None):
    stamp = datetime.fromtimestamp((START+minutes*60_000)/1000, timezone.utc).isoformat()
    return stamp, dict(observed_at=stamp, started_at=stamp, read_only=True, status="AVAILABLE", errors={},
                       usdm_wallet_balance_usdt=wallet, usdm_margin_balance_usdt=wallet if equity is None else equity)


def entry(minutes, amount, kind="TRANSFER"):
    return dict(time=START+minutes*60_000, amount=amount, income_type=kind, asset="USDT", symbol="")


class AccountPerformanceTest(unittest.TestCase):
    def test_downsampling_thins_chart_points_but_never_summary_or_anchors(self):
        # 4h of 5-min observations with one deposit: full computation stays exact.
        obs = [observation(m, 100 if m <= 120 else 150) for m in range(0, 241, 5)]
        income = [entry(122, 50)]  # strictly between observations to avoid the sampling-race gap rule
        raw = build_performance(obs, income, [(START, START + 241 * 60_000)])
        self.assertEqual(raw["summary"]["net_external_flow_usdt"], 50)
        self.assertEqual(len(raw["points"]), 49)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); history = root / "history.db"; trades = root / "trades.db"
            for _, row in obs:
                append_asset_history(history, row)
            snapshot = collect_trade_records(Exchange(), now_ms=START + 240 * 60_000, symbols=("SPYUSDT",))
            deposit = dict(account_record_id="income:TRANSFER:1", symbol="", income_type="TRANSFER",
                           transaction_id=1, time=START + 122 * 60_000, amount=50.0, asset="USDT",
                           strategy_id=None, signal_id=None, order_intent_id=None,
                           attribution="unassigned_account_income")
            snapshot.update(income=[deposit], fills=[])
            persist_trade_records(trades, snapshot)
            result = read_account_performance(history, trades)
            self.assertEqual(result["resolution"], "1h")
            self.assertTrue(result["downsampled"])
            self.assertLess(len(result["points"]), 49)
            self.assertGreaterEqual(len(result["points"]), 5)  # hour anchors + final point
            # summary identical to the raw computation
            self.assertEqual(result["summary"], raw["summary"])
            self.assertEqual(result["segment_count"], raw["segment_count"])
            # first and last chart points survive
            self.assertEqual(result["points"][0]["observed_at"], raw["points"][0]["observed_at"])
            self.assertEqual(result["points"][-1]["observed_at"], raw["points"][-1]["observed_at"])
            self.assertEqual(result["points"][-1]["return_pct"], raw["points"][-1]["return_pct"])

    def test_deposit_and_withdrawal_never_create_profit(self):
        result = build_performance([observation(0,100),observation(5,200),observation(10,150)],
                                   [entry(2,100),entry(7,-50)], [(START,START+600_000)])
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["summary"]["net_external_flow_usdt"],50)
        self.assertEqual(result["summary"]["return_pct"],0)
        self.assertEqual(result["summary"]["net_pnl_usdt"],0)

    def test_profit_fees_funding_and_unrealized_are_counted_once(self):
        rows = [entry(1,5,"REALIZED_PNL"),entry(2,-1,"COMMISSION"),entry(3,-.5,"FUNDING_FEE")]
        result = build_performance([observation(0,100),observation(5,103.5,105.5)],rows,[(START,START+300_000)])
        self.assertAlmostEqual(result["summary"]["net_pnl_usdt"],5.5)
        self.assertAlmostEqual(result["summary"]["return_pct"],5.5)

    def test_missing_coverage_does_not_bridge_segments(self):
        obs = [observation(n,100) for n in (0,5,10,15)]
        result = build_performance(obs,[],[(START,START+300_000),(START+600_000,START+900_000)])
        self.assertEqual(result["segment_count"],2)
        self.assertEqual(result["gaps"][0]["reason"],"income_coverage_missing")
        self.assertEqual(result["summary"]["observation_count"],2)

    def test_microsecond_snapshot_does_not_require_a_future_millisecond(self):
        stamp,row=observation(5,100)
        stamp=stamp.replace("+00:00",".000716+00:00")
        row.update(observed_at=stamp,started_at=stamp)
        result=build_performance([observation(0,100),(stamp,row)],[],[(START,START+300_000)])
        self.assertEqual(result["status"],"AVAILABLE")
        self.assertTrue(result["summary"]["includes_latest_observation"])

    def test_missing_transfer_unknown_income_and_sampling_races_are_not_returns(self):
        obs=[observation(0,100),observation(5,200)]
        for rows,reason in (([],"wallet_income_mismatch"),([entry(2,100,"UNKNOWN")],"unsupported_income_type")):
            result=build_performance(obs,rows,[(START,START+300_000)])
            self.assertEqual(result["points"],[])
            self.assertEqual(result["gaps"][0]["reason"],reason)
        stamp,row=observation(5,200);row["started_at"]=observation(4,0)[0]
        result=build_performance([obs[0],(stamp,row)],[entry(4.5,100)],[(START,START+300_000)])
        self.assertEqual(result["gaps"][0]["reason"],"income_during_observation")

    def test_long_outage_zero_capital_and_missing_files_remain_unknown(self):
        for obs in ([observation(0,100),observation(20,100)],[observation(0,0),observation(5,100)]):
            self.assertFalse(build_performance(obs,[],[(START,START+1_200_000)])["points"])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"missing.db"
            self.assertEqual(read_account_performance(path,path)["status"],"MISSING")
            self.assertFalse(path.exists())

    def test_income_coverage_survives_a_later_failed_collection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);history=root/"history.db";trades=root/"trades.db"
            for _,row in [observation(0,100),observation(5,100)]:append_asset_history(history,row)
            snapshot=collect_trade_records(Exchange(),now_ms=START+400_000,symbols=("SPYUSDT",))
            snapshot.update(income=[],fills=[])
            persist_trade_records(trades,snapshot)
            persist_trade_records(trades,{**snapshot,"observed_at":observation(10,100)[0],"status":"ERROR","errors":{"income":"TimeoutError"}})
            result=read_account_performance(history,trades)
            self.assertEqual(result["status"],"AVAILABLE")
            self.assertEqual(result["summary"]["return_pct"],0)

    def test_old_record_metadata_does_not_block_new_exchange_records_or_rewrite_raw(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"trades.db"
            snapshot=collect_trade_records(Exchange(),now_ms=NOW,symbols=("SPYUSDT",))
            persist_trade_records(path,snapshot)
            with sqlite3.connect(path) as conn:
                old=conn.execute("SELECT record_key,payload FROM account_records WHERE kind='fill'").fetchone()
                raw=json.loads(old[1])
                for key in ("account_record_id","signal_id","order_intent_id"):raw.pop(key,None)
                encoded=json.dumps(raw)
                conn.execute("UPDATE account_records SET payload=? WHERE kind='fill' AND record_key=?",(encoded,old[0]))
            persist_trade_records(path,snapshot)
            with sqlite3.connect(path) as conn:self.assertEqual(conn.execute("SELECT payload FROM account_records WHERE kind='fill'").fetchone()[0],encoded)
            self.assertEqual(read_trade_records(path)["fills"][0]["account_record_id"],"fill:SPYUSDT:1")
            snapshot["fills"][0]["price"]+=1
            with self.assertRaisesRegex(ValueError,"immutable"):persist_trade_records(path,snapshot)

    def test_closed_strategy_net_pnl_includes_only_exact_owned_fills_and_funding(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=BinanceExecutionStore(root/"execution.db")
            strategy="rolling7_risk_no_chase_mr_signal_gap_1atr"
            exchange=Exchange();opening=fill(NOW-3000);closing=fill(NOW-1000,2)
            closing.update(side="SELL",orderId=100,realizedPnl="2",commission=".006")
            exchange.fills=[opening,closing];exchange.income=[income(NOW-2000)]
            snapshot=collect_trade_records(exchange,now_ms=NOW,symbols=("SPYUSDT",))
            persist_trade_records(root/"trades.db",snapshot)
            for name,side,order in (("open","buy",99),("close","sell",100)):
                store.create_order(client_order_id=name,symbol="SPYUSDT",side=side,quantity=.1,
                    payload={"strategy_id":strategy,"signal_id":"s","order_intent_id":name})
                store.apply_response(name,dict(status="FILLED",exchange_order_id=str(order),executed_quantity=.1,average_price=100,fills=[]))
            result=strategy_accounting(root/"trades.db",store.path,strategy)
            self.assertEqual(result["status"],"AVAILABLE")
            self.assertAlmostEqual(result["net_pnl_usdt"],2-.011-.01)
            closing["orderId"]=101
            snapshot=collect_trade_records(exchange,now_ms=NOW,symbols=("SPYUSDT",))
            other=root/"other.db";persist_trade_records(other,snapshot)
            self.assertIsNone(strategy_accounting(other,store.path,strategy)["net_pnl_usdt"])
