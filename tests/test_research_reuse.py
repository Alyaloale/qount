"""Reuse and selected-run isolation across files, SQLite and HTTP."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qount.research.engine.runs import run_identity, cached_run, save_run, cached_features
from qount.api.ingest import run_ingest
from qount.api.db import get_paper_trades
from qount.api.routes.research import router


class ResearchReuseTest(unittest.TestCase):
    def test_moving_identical_inputs_between_hosts_reuses_but_changed_dependency_does_not(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);codes=[]
            for host in ("mac","wsl"):
                p=root/host/"src/qount/strategies/perpetual.py";p.parent.mkdir(parents=True);p.write_text("v1");codes.append(p)
            a=run_identity("line",{},[{"path":"/mac/data/hourly.json","sha256":"same"}],[codes[0]])[0]
            b=run_identity("line",{},[{"path":"/wsl/data/hourly.json","sha256":"same"}],[codes[1]])[0]
            self.assertEqual(a,b)
            codes[1].write_text("v2")
            self.assertNotEqual(a,run_identity("line",{},[{"path":"/wsl/data/hourly.json","sha256":"same"}],[codes[1]])[0])

    def test_feature_reuse_and_failed_result_write_never_publish_partial_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);code=root/"feature.py";code.write_text("v1");calls=[]
            def build():calls.append(1);return {"atr":[1,2,3]}
            for _ in range(2):self.assertEqual(cached_features("atr",{"span":14},[],[code],build,root),{"atr":[1,2,3]})
            self.assertEqual(len(calls),1)
            cached_features("atr",{"span":20},[],[code],build,root)
            self.assertEqual(len(calls),2)
            digest,identity=run_identity("line",{},[],[code]);path=root/"line"/digest
            with self.assertRaises(ValueError):save_run(path,digest,identity,dict(nav=[float('nan')],trades=[],summary={}))
            self.assertFalse(path.exists())

    def test_selected_run_is_explicit_and_trade_view_never_accumulates_other_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);code=root/"rule.py";code.write_text("v1");ids=[]
            for index in (1,2):
                digest,identity=run_identity("example",{"fee":.001,"slip":.001,"case":index},[],[code]);ids.append(digest)
                result=dict(nav=[{"t":1700000000,"nav":1.0},{"t":1700003600,"nav":1+index/100}],
                    trades=[dict(symbol="SPYUSDT",quantity=index,entry_time=1700000100,entry_price=100,entry_fee=.1,
                                 exit_time=1700003500,exit_price=101,exit_fee=.1)],
                    summary=dict(total_return_pct=index,max_drawdown_pct=0,cagr_pct=None,calmar=None,trade_count=1,days=1))
                save_run(root/"example"/digest[:20],digest,identity,result)
            registry=root/"registry.json";db=root/"query.db"
            def select(index):
                registry.write_text(json.dumps({"lines":[dict(id="example",name="实验",adapter="experiment",enabled=False,
                    config=dict(root=str(root/"example"),run_id=ids[index][:20]))]}))
                self.assertTrue(run_ingest(str(registry),str(db))["ok"])
            select(0)
            self.assertEqual([r.quantity for r in get_paper_trades("example",db_path=str(db),forward_only=False)],[1,1])
            # Touching another experiment cannot silently select its result.
            (root/"example"/ids[1][:20]/"summary.json").touch()
            select(0)
            self.assertEqual([r.quantity for r in get_paper_trades("example",db_path=str(db),forward_only=False)],[1,1])
            select(1)
            self.assertEqual([r.quantity for r in get_paper_trades("example",db_path=str(db),forward_only=False)],[2,2])
            app=FastAPI();app.include_router(router)
            with patch.dict(os.environ,{"QOUNT_DB_PATH":str(db),"QOUNT_PAPER_LINES_REGISTRY":str(registry)}),TestClient(app) as client:
                self.assertEqual(client.get('/research/lines/example').json()['run_id'],ids[1])
                old=client.get('/research/lines/example',params={'run_id':ids[0]}).json()
                self.assertEqual(old['metrics']['total_return_pct'],1)
                trades=client.get('/research/trades',params={'line_id':'example','run_id':ids[0]}).json()
                self.assertEqual([r['quantity'] for r in trades],[1,1])
                self.assertEqual(len(client.get('/research/lines/example/runs').json()['runs']),2)
                self.assertEqual(client.get('/research/lines/example/runs/bad').status_code,404)
            # The input result remains untouched by changing the query selection.
            self.assertIsNotNone(cached_run(root/'example'/ids[0][:20],ids[0]))
