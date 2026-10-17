"""Regression checks for account completeness, research isolation and reuse."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qount.api.adapters import register_adapter
from qount.api.db import get_paper_line, get_paper_lines_summary
from qount.api.ingest import run_ingest
from qount.api.routes.account import _annotate_asset_positions, load_live_account_snapshot
from qount.api.routes.research import router as research_router
from qount.api.routes.paper import router as paper_router
from qount.api.schemas import PaperLine, LineSource, NavPoint
from qount.execution.binance_usdm import BinanceExecutionStore
from qount.execution.protection import inspect_protection
from qount.operations.account_assets import collect_asset_overview
from qount.operations.account_trades import collect_trade_records, persist_trade_records, read_trade_records, strategy_accounting
from qount.research.engine.runs import run_identity, cached_run, save_run
from qount.research.engine.evaluation import nav_metrics
from qount.research.lines.one_atr import replay
from qount.research_data.bars import Bar
from qount.research_data.binance_history import load_cached_history
from tests.test_account_assets import Exchange as AssetExchange
from tests.test_account_trades import Exchange as TradeExchange, NOW


class PersonalAccountTest(unittest.TestCase):
    def test_non_strategy_positions_survive_collector_and_api(self):
        ex = AssetExchange()
        ex.usdm["positions"][0]["symbol"] = "XRPUSDT"
        result = _annotate_asset_positions(collect_asset_overview(ex))
        self.assertTrue(result["futures_positions_complete"])
        self.assertEqual(result["futures_positions"][0]["symbol"], "XRPUSDT")
        self.assertFalse(result["futures_positions"][0]["strategy_asset"])
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/"account.json"
            p.write_text(json.dumps({"account_observation":dict(observed_at=datetime.now(timezone.utc).isoformat(),wallet_balance=20,available_balance=22,
                positions=[dict(symbol="XRPUSDT",quantity=1,notional=3,side="long")])}))
            with patch.dict(os.environ,{"QOUNT_ACCOUNT_OBSERVATION_PATH":str(p)}):
                account = load_live_account_snapshot()
            self.assertEqual(account.positions[0].symbol,"XRPUSDT")
            self.assertEqual(account.cash,22)

    def test_non_strategy_income_discovers_fills_and_exact_order_ownership(self):
        ex = TradeExchange()
        ex.fills[0]["symbol"] = ex.income[0]["symbol"] = "XRPUSDT"
        snapshot = collect_trade_records(ex,now_ms=NOW,symbols=())
        self.assertEqual(snapshot["status"],"AVAILABLE")
        self.assertEqual(snapshot["requested_symbols"],["XRPUSDT"])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = BinanceExecutionStore(root/"execution.db")
            store.create_order(client_order_id="entry",symbol="XRPUSDT",side="buy",quantity=.1,
                               payload={"strategy_id":"one_atr_macro_v0_1","signal_id":"s","order_intent_id":"i"})
            store.apply_response("entry",dict(status="FILLED",exchange_order_id="99",executed_quantity=.1,average_price=100,fills=[]))
            persist_trade_records(root/"trades.db",snapshot)
            read = read_trade_records(root/"trades.db",execution_path=store.path)
            self.assertEqual(read["fills"][0]["strategy_id"],"one_atr_macro_v0_1")
            self.assertIsNone(read["income"][0]["strategy_id"])
            accounting = strategy_accounting(root/"trades.db",store.path,"one_atr_macro_v0_1")
            self.assertEqual(accounting["assigned_fill_count"],1)
            self.assertEqual(accounting["commission_by_asset"],{"USDT":.005})
            self.assertIsNone(accounting["net_pnl_usdt"])
            # Attribution is a projection; immutable raw account records stay unchanged.
            self.assertIsNone(read_trade_records(root/"trades.db")["fills"][0]["strategy_id"])


class ResearchSeparationTest(unittest.TestCase):
    def test_disabled_paper_is_still_queryable_research(self):
        @register_adapter("test_historical_personal")
        def historical(line_id,name,config):
            return PaperLine(line_id=line_id,name=name,as_of="2024-01-02",adjudication="保留失败结果",
                             nav_series=[NavPoint(date="2024-01-01",nav=1),NavPoint(date="2024-01-02",nav=.9)],
                             source=LineSource(path="fixture"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            registry = root/"registry.json"
            registry.write_text(json.dumps({"lines":[dict(id="historical",name="历史研究",adapter="test_historical_personal",enabled=False)]}))
            db = str(root/"query.db")
            self.assertTrue(run_ingest(str(registry),db)["ok"])
            self.assertEqual(get_paper_lines_summary(db),[])
            self.assertEqual(len(get_paper_lines_summary(db,forward_only=False)),1)
            self.assertEqual(get_paper_line("historical",db,forward_only=False).nav_series[-1].nav,.9)
            app = FastAPI();app.include_router(research_router);app.include_router(paper_router)
            with patch.dict(os.environ,{"QOUNT_DB_PATH":db}),TestClient(app) as client:
                self.assertEqual(len(client.get("/research/lines").json()),1)
                self.assertEqual(client.get("/paper/lines").json(),[])
                self.assertEqual(client.get("/research/lines/historical").status_code,200)
                self.assertEqual(client.get("/paper/lines/historical").status_code,404)

    def test_results_reuse_requires_same_line_code_parameters_and_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);code = root/"strategy.py";code.write_text("v1")
            args = ("one_atr",{"fee":.001},[{"path":"market","sha256":"source"}],[code])
            digest, identity = run_identity(*args)
            path = root/"one_atr"/digest[:20]
            save_run(path,digest,identity,{"summary":{"total_return_pct":0},"nav":[],"trades":[]})
            self.assertEqual(cached_run(path,digest)["line_id"],"one_atr")
            self.assertNotEqual(run_identity("another_line",*args[1:])[0],digest)
            self.assertNotEqual(run_identity("one_atr",{"fee":.002},*args[2:])[0],digest)
            code.write_text("v2");self.assertNotEqual(run_identity(*args)[0],digest)
            (path/"nav.json").write_text("[1]")
            with self.assertRaisesRegex(ValueError,"changed_or_incomplete"):
                cached_run(path,digest)
            with self.assertRaisesRegex(ValueError,"line_id"):
                run_identity("../live",{},[],[code])


def native_fixture():
    start = int(datetime(2025,1,1,tzinfo=timezone.utc).timestamp())
    bars = [Bar(start+i*3600,100+i/240,101+i/240,99+i/240,100+i/240,1000,100000) for i in range(135*24)]
    return {"SPYUSDT":dict(trade=bars,mark=bars,
        funding=[{"fundingTime":b.t*1000,"fundingRate":".0001","markPrice":str(b.o)} for i,b in enumerate(bars) if i%8==0],
        rule={"filters":[{"filterType":"PRICE_FILTER","tickSize":".01"},
            {"filterType":"LOT_SIZE","minQty":".01","maxQty":"1000","stepSize":".01"},
            {"filterType":"MIN_NOTIONAL","notional":"5"}]})}


class NativeReplayTest(unittest.TestCase):
    def test_existing_hourly_partitions_merge_without_download_and_reject_conflicts(self):
        data=native_fixture()["SPYUSDT"]
        bars=data["trade"][:48];start=bars[0].t;end=start+48*3600
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);a=root/"a";b=root/"b";a.mkdir();b.mkdir()
            rules=root/"rules.json";rules.write_text(json.dumps({"symbols":[dict(symbol="SPYUSDT",**data["rule"])]}))
            rows=[[p.t*1000,p.o,p.h,p.l,p.c,p.v,0,p.q] for p in bars]
            for kind in ("trade","mark"):
                (a/f"SPYUSDT-{kind}-{start}-{start+24*3600}.json").write_text(json.dumps(rows[:24]))
                (b/f"SPYUSDT-{kind}-{start+24*3600}-{end}.json").write_text(json.dumps(rows[24:]))
            funding=[r for r in data["funding"] if start*1000<=r["fundingTime"]<end*1000]
            (a/f"SPYUSDT-funding-{start}-{end}.json").write_text(json.dumps(funding))
            actual,sources,excluded=load_cached_history([a,b],["SPYUSDT","ETHUSDT"],start,end,rules)
            self.assertEqual(actual["SPYUSDT"]["trade"],bars)
            self.assertEqual(excluded,{"ETHUSDT":"missing_rule_trade_mark_or_funding"})
            self.assertEqual(len(sources),6)
            corrupted=copy.deepcopy(rows[:24]);corrupted[0][4]+=1
            (b/f"SPYUSDT-trade-{start}-{start+24*3600}.json").write_text(json.dumps(corrupted))
            with self.assertRaisesRegex(ValueError,"conflicting_cached_observation"):
                load_cached_history([a,b],["SPYUSDT"],start,end,rules)

    def test_native_replay_costs_causality_and_open_position_cash_identity(self):
        data = native_fixture();start = data["SPYUSDT"]["trade"][0].t
        result = replay(data,start=start,end=start+135*86400)
        self.assertEqual(result["summary"]["entry_count"],1)
        self.assertIsNotNone(result["summary"]["open_position"])
        self.assertGreater(result["summary"]["open_position"]["entry_time"],result["summary"]["open_position"]["signal_time"])
        self.assertIsNone(result["summary"]["cagr_pct"])
        free = replay(data,start=start,end=start+135*86400,fee=0,slip=0)
        self.assertGreater(free["nav"][-1]["nav"],result["nav"][-1]["nav"])
        changed = copy.deepcopy(data)
        cutoff = start+130*86400
        for kind in ("trade","mark"):
            changed["SPYUSDT"][kind] = [Bar(b.t,b.o*2,b.h*2,b.l*2,b.c*2,b.v,b.q) if b.t>=cutoff else b for b in changed["SPYUSDT"][kind]]
        future = replay(changed,start=start,end=start+135*86400)
        self.assertEqual([p for p in result["nav"] if p["t"]<=cutoff],[p for p in future["nav"] if p["t"]<=cutoff])

    def test_standard_calmar_uses_annualized_return_and_short_runs_suppress_it(self):
        points=[dict(t=0,nav=1),dict(t=365.25*86400/2,nav=.8),dict(t=365.25*86400,nav=1.1)]
        result=nav_metrics(points)
        self.assertAlmostEqual(result["cagr_pct"],10)
        self.assertAlmostEqual(result["max_drawdown_pct"],20)
        self.assertAlmostEqual(result["calmar"],.5)
        self.assertIsNone(nav_metrics([dict(t=0,nav=1),dict(t=86400,nav=1.1)])["calmar"])


class AutoCycleTest(unittest.TestCase):
    def test_retired_auto_authorization_blocks_entry_and_legacy_inspector_stays_read_only(self):
        from scripts.operations import run_1atr_auto as auto
        class Exchange:
            def fetch_positions(self):return [{"symbol":"CL/USDT:USDT","contracts":1,"side":"long"}]
            def fetch_open_orders(self,symbol):return [{"symbol":symbol,"clientOrderId":"stop","type":"STOP_MARKET","side":"sell","remaining":1,"reduceOnly":True,"stopPrice":90}]
            def create_order(self,*args,**kwargs):raise AssertionError("must never send an entry")
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=BinanceExecutionStore(root/"execution.db")
            store.create_order(client_order_id="stop",symbol="CLUSDT",side="sell",quantity=1,payload={"strategy_id":"one_atr_macro_v0_1","signal_id":"s","order_intent_id":"protective"})
            plan={"strategy_id":"one_atr_macro_v0_1","selected":{"symbol":"QQQUSDT"},"created_at":"2026-10-16T12:00:00Z"}
            with patch.dict(os.environ,{"QOUNT_LIVE_ENABLE":"true","QOUNT_PRIMARY_STRATEGY":"one_atr_macro_v0_1"}):
                result=auto.run_cycle(Exchange(),output=root/"result.json",store_path=store.path,arm_path=root/"arm.json",halt_path=root/"HALT",execute=True)
            self.assertEqual(result["auto_action"],"BLOCKED")
            self.assertEqual(result["execution_blocker"],"macro_orders_not_authorized")
            self.assertEqual(inspect_protection(Exchange(),Exchange().fetch_positions(),store)["status"],"PROTECTED")
            self.assertFalse((root/"arm.json").exists())
            self.assertFalse((root/"HALT").exists())
            self.assertEqual(inspect_protection(Exchange(),[{"symbol":"CLUSDT","contracts":2,"side":"long"}],store)["status"],"UNPROTECTED")
            class LimitStop(Exchange):
                def fetch_open_orders(self,symbol):
                    return [dict(super().fetch_open_orders(symbol)[0],type="STOP_LIMIT")]
            self.assertEqual(inspect_protection(LimitStop(),Exchange().fetch_positions(),store)["status"],"UNPROTECTED")


if __name__ == "__main__":
    unittest.main()
