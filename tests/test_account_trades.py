import copy,json,tempfile,unittest,os
from unittest.mock import patch
from pathlib import Path
from qount.operations.account_trades import collect_trade_records,persist_trade_records,read_trade_records
NOW=1_800_000_000_000
def fill(stamp=NOW-10,trade_id=1):
    return dict(symbol="SPYUSDT",id=trade_id,orderId=99,time=stamp,side="BUY",positionSide="BOTH",price="100",qty=".1",realizedPnl="0",commission=".005",commissionAsset="USDT")
def income(stamp=NOW-10,tran=1,kind="FUNDING_FEE",amount="-.01"):
    return dict(symbol="SPYUSDT",incomeType=kind,tranId=tran,time=stamp,income=amount,asset="USDT")
class Exchange:
    def __init__(self):self.fills=[fill()];self.income=[income()];self.calls=[]
    def fapiPrivateGetIncome(self,p):
        self.calls.append(('income',p));return [copy.deepcopy(r) for r in self.income if p['startTime']<=r['time']<=p['endTime']][:p['limit']]
    def fapiPrivateGetUserTrades(self,p):
        self.calls.append(('fills',p));return [copy.deepcopy(r) for r in self.fills if r['symbol']==p['symbol'] and p['startTime']<=r['time']<=p['endTime']][:p['limit']]
class TestAccountTrades(unittest.TestCase):
    def test_get_only_records_and_unknown_strategy_ownership(self):
        ex=Exchange();s=collect_trade_records(ex,now_ms=NOW,symbols=('SPYUSDT',))
        self.assertEqual(s['status'],'AVAILABLE');self.assertEqual(len(s['fills']),1)
        self.assertIsNone(s['fills'][0]['strategy_id']);self.assertFalse(s['orders_authorized'])
        self.assertEqual(s['fills'][0]['trade_id'],'1');self.assertEqual(s['fills'][0]['commission'],.005)
        self.assertEqual([c[0] for c in ex.calls],['income','fills'])
        self.assertTrue(all('fromId' not in p for _,p in ex.calls))
    def test_saturated_windows_split_without_losing_tied_timestamps(self):
        ex=Exchange();ex.income=[];ex.fills=[fill(NOW-100,1),fill(NOW-100,2),fill(NOW-5,3)]
        s=collect_trade_records(ex,now_ms=NOW,symbols=('SPYUSDT',),limit=3,max_calls=32)
        self.assertEqual(s['status'],'AVAILABLE');self.assertEqual({r['trade_id'] for r in s['fills']},{'1','2','3'})
        self.assertGreater(s['request_count'],2)
    def test_budget_or_dense_millisecond_does_not_claim_complete(self):
        ex=Exchange();ex.income=[];ex.fills=[fill(NOW-10,i) for i in range(3)]
        s=collect_trade_records(ex,now_ms=NOW,symbols=('SPYUSDT',),limit=3,max_calls=3)
        self.assertNotEqual(s['status'],'AVAILABLE');self.assertIn('SPYUSDT',s['errors']);self.assertEqual(s['request_count'],3)
    def test_errors_do_not_persist_signed_request_details(self):
        ex=Exchange()
        def fail(_):raise RuntimeError('https://signed?apiKey=SECRET&signature=SECRET')
        ex.fapiPrivateGetUserTrades=fail;s=collect_trade_records(ex,now_ms=NOW,symbols=('SPYUSDT',))
        self.assertEqual(s['status'],'PARTIAL');self.assertNotIn('SECRET',json.dumps(s))
    def test_income_symbols_extend_explicit_fill_scope(self):
        ex=Exchange();ex.income[0]['symbol']='BTCUSDT';ex.fills=[]
        s=collect_trade_records(ex,now_ms=NOW,symbols=('SPYUSDT',));self.assertEqual(s['requested_symbols'],['BTCUSDT','SPYUSDT'])
    def test_exact_deduplication_and_immutable_conflict(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'records.db';s=collect_trade_records(Exchange(),now_ms=NOW,symbols=('SPYUSDT',))
            persist_trade_records(p,s);persist_trade_records(p,s);r=read_trade_records(p)
            self.assertEqual(r['fill_count'],1);self.assertEqual(r['income_count'],1);self.assertEqual(p.stat().st_mode&0o777,0o600)
            s['fills'][0]['quantity']=999
            with self.assertRaisesRegex(ValueError,'immutable_account_record_conflict'):persist_trade_records(p,s)
            self.assertEqual(read_trade_records(p)['fills'][0]['quantity'],.1)
    def test_new_failed_poll_keeps_records_but_reports_partial(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'records.db';s=collect_trade_records(Exchange(),now_ms=NOW,symbols=('SPYUSDT',));persist_trade_records(p,s)
            persist_trade_records(p,{**s,'fills':[],'income':[],'status':'ERROR','errors':{'income':'TimeoutError'}})
            r=read_trade_records(p);self.assertEqual(r['status'],'ERROR');self.assertEqual(r['fill_count'],1)
    def test_income_is_separate_and_transfers_are_not_added_to_fill_pnl(self):
        ex=Exchange();ex.income=[income(kind='TRANSFER',amount='20')]
        s=collect_trade_records(ex,now_ms=NOW,symbols=('SPYUSDT',))
        self.assertEqual(s['fills'][0]['realized_pnl'],0);self.assertEqual(s['income'][0]['amount'],20)
    def test_missing_database_read_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'absent.db';self.assertEqual(read_trade_records(p)['status'],'MISSING');self.assertFalse(p.exists())
    def test_http_route_reads_sibling_ledger_without_exchange_requests(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from qount.api.routes.account import router
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'QOUNT_ACCOUNT_OBSERVATION_PATH':str(Path(root)/'observation.json')}):
            app=FastAPI();app.include_router(router)
            with TestClient(app) as client:
                self.assertEqual(client.get('/account/trades').json()['status'],'MISSING')
                s=collect_trade_records(Exchange(),now_ms=NOW,symbols=('SPYUSDT',))
                persist_trade_records(Path(root)/'account-trades.sqlite3',s)
                self.assertEqual(client.get('/account/trades?limit=1').json()['fill_count'],1)
                self.assertEqual(client.get('/account/trades?limit=999').status_code,422)
