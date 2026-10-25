import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qount.api.paper_filter import is_forward_paper_line
from qount.api.adapters.research_paper import adapt_research_paper
from qount.dual_engine import run_paper_cycle
from qount.legacy.universal_regime.engine import run_regime_backtest
from scripts.operations.run_research_paper import REGIME, etf_step, run_account
from tests.test_dual_engine import _cycle


class ForwardPaperTest(unittest.TestCase):
    def test_restart_begins_in_cash_without_historical_fills(self):
        with tempfile.TemporaryDirectory() as folder:
            first=run_paper_cycle(folder,_cycle(3),initialize_cash=True)
            for p in first.portfolios:
                self.assertEqual(p['holdings'],[])
                self.assertEqual(p['nav']['points'][-1]['executable'],1.)
                self.assertEqual(p['rebalances']['events'],[])
            second=run_paper_cycle(folder,_cycle(4),initialize_cash=True)
            self.assertTrue(second.portfolios[1]['holdings'])
            self.assertEqual(second.portfolios[0]['holdings'],[])

    def test_regime_resume_matches_uninterrupted_account(self):
        params=dict(REGIME,symbols=['SPY','GLD'],start_date='2025-01-01',return_state=True)
        full=run_regime_backtest(end_date='2025-06-30',**params)
        first=run_regime_backtest(end_date='2025-03-31',**params)
        second=run_regime_backtest(end_date='2025-06-30',**dict(params,start_date='2025-04-01',opening_state=first['paper_state']))
        self.assertAlmostEqual(full['final_equity'],second['final_equity'])
        self.assertEqual(full['paper_state'],second['paper_state'])
        self.assertEqual(full['trades'],first['trades']+second['trades'])

    def test_etf_close_signal_cannot_fill_same_close(self):
        rows=[dict(date=(dt.date(2025,1,1)+dt.timedelta(days=i)).isoformat(),open=10.,close=10.,adjClose=10.) for i in range(250)]
        for row in rows[-3:]:row.update(close=11.,adjClose=11.)
        state,equity,positions,trades=etf_step(None,rows,genesis=True)
        self.assertEqual(trades,[]);self.assertEqual(positions,[])
        next_row=dict(date='2025-09-08',open=12.,close=12.5,adjClose=12.5)
        state,equity,positions,trades=etf_step(state,rows+[next_row],genesis=False)
        self.assertEqual(trades[0]['date'],'2025-09-08')
        self.assertAlmostEqual(trades[0]['price'],12*1.0005)
        self.assertEqual(trades[0]['quantity']%100,0)

    def test_gap_rows_are_reconstruction_and_restart_is_idempotent(self):
        observed=dt.datetime.now(dt.timezone.utc)
        today=observed.date()
        rows=[dict(date=(today-dt.timedelta(days=253-i)).isoformat(),open=10.,close=10.,adjClose=10.) for i in range(250)]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch('scripts.operations.run_research_paper.tencent_etf_rows',return_value=(rows,'a'*64)):
                run_account('etf',root,observed)
                run_account('etf',root,observed)
            self.assertEqual(len(json.loads((root/'forward.json').read_text())['observations']),1)
            for i in range(2):rows.append(dict(rows[-1],date=(today-dt.timedelta(days=3-i)).isoformat()))
            with patch('scripts.operations.run_research_paper.tencent_etf_rows',return_value=(rows,'b'*64)):
                run_account('etf',root,observed)
            data=json.loads((root/'forward.json').read_text())
            self.assertEqual([o['sample_kind'] for o in data['observations']],['genesis','reconstructed','reconstructed'])
            line=adapt_research_paper('etf','ETF',{'root':folder}).model_copy(update={'paper_enabled':True,'sample_kind':'forward'})
            self.assertTrue(is_forward_paper_line(line))
            self.assertFalse(is_forward_paper_line(line.model_copy(update={'sample_kind':'historical'})))
            self.assertFalse(is_forward_paper_line(line.model_copy(update={'safety':line.safety.model_copy(update={'orders_authorized':True})})))

    def test_restart_after_open_never_backfills_an_entry_at_that_open(self):
        rows=[dict(date='2026-10-21',open=10.,close=10.,adjClose=10.) for _ in range(250)]
        state=dict(cash=100000.,quantity=0.,machine=dict(current_target=1.,executed_state=0.,pending_target=1.,confirm_count=0))
        rows.append(dict(date='2026-10-22',open=10.,close=10.,adjClose=10.))
        result=etf_step(state,rows,genesis=False,decision_available_at='2026-10-22T05:00:00+00:00')
        self.assertEqual(result[3],[])
        self.assertEqual(result[0]['quantity'],0.)

    def test_etf_history_resume_keeps_equity_and_share_state(self):
        from scripts.operations.merge_paper_history import resume_etf
        today=dt.date(2026,10,21)
        rows=[dict(date=(today-dt.timedelta(days=251-i)).isoformat(),open=20.,close=20.,adjClose=20.) for i in range(252)]
        # A rising signal at the boundary; two new sessions are marked with the same old shares.
        for row in rows[-5:]:row.update(close=22.,adjClose=22.)
        cutoff=rows[-3]['date'];compact=lambda d:d.replace('-','')
        old_nav=[[compact(rows[-4]['date']),2100.],[compact(cutoff),2227.5]]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'account';history=Path(folder)/'history'
            (root/'cache').mkdir(parents=True);history.mkdir()
            (root/'cache/513100.json').write_text(json.dumps(dict(rows=rows,source_hash='a'*64)))
            (history/'summary.json').write_text(json.dumps(dict(generated_at='2026-10-19T10:00:00+00:00')))
            prior=dict(metrics=dict(initial_equity=1000.,terminal_equity=2227.5),nav=old_nav)
            (history/'baseline-replay.json').write_text(json.dumps({'513100.SH':{'MA120_Band1.5pct':prior,'Buy_and_Hold':prior}}))
            (history/'trades.json').write_text(json.dumps({'513100.SH':{'MA120_Band1.5pct':[
                dict(date=compact(cutoff),action='BUY',shares=101.25,cash_rem=0.,price=22.,commission=1.)]}}))
            result=resume_etf(root,history,'2026-10-22T06:00:00+00:00')
            data=json.loads((root/'forward.json').read_text())
            self.assertEqual([r['equity'] for r in data['observations'][:2]],[2100.,2227.5])
            self.assertEqual(data['state']['quantity'],101.25)
            self.assertEqual(result['reconstructed'],2)
            self.assertEqual(data['rules']['lot_size'],0)
            line=adapt_research_paper('personal_assistant','ETF',{'root':str(root)}).model_copy(update={'sample_kind':'mixed'})
            self.assertTrue(is_forward_paper_line(line))
            self.assertEqual([s['kind'] for s in line.source.segments],['historical','reconstructed'])
            self.assertAlmostEqual(line.nav_series[-1].nav,2.2275)
            self.assertFalse(is_forward_paper_line(line.model_copy(update={'source':line.source.model_copy(update={'segments':[]})})))

    def test_continuous_late_fill_is_reconstruction_and_uses_original_fractional_rules(self):
        observed=dt.datetime(2026,10,22,6,tzinfo=dt.timezone.utc)
        rows=[dict(date=(dt.date(2026,10,22)-dt.timedelta(days=250-i)).isoformat(),open=10.,close=10.,adjClose=10.) for i in range(251)]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            data=dict(kind='etf',initial_equity=1234.,created_at=observed.isoformat(),
                state=dict(cash=1234.,quantity=0.,machine=dict(current_target=1.,executed_state=0.,pending_target=1.,confirm_count=0)),
                observations=[dict(date='2026-10-21',equity=1234.,positions=[],recorded_at=observed.isoformat(),sample_kind='historical')],
                trades=[],rules=dict(lot_size=0,cash_apr=.02),source='tencent_public_raw_and_qfq',continuous=True,orders_authorized=False,research_only=True)
            (root/'forward.json').write_text(json.dumps(data))
            with patch('scripts.operations.run_research_paper.tencent_etf_rows',return_value=(rows,'b'*64)):
                run_account('etf',root,observed)
                run_account('etf',root,observed)
            result=json.loads((root/'forward.json').read_text())
            self.assertEqual(len(result['observations']),2)
            self.assertEqual(result['observations'][-1]['sample_kind'],'reconstructed')
            self.assertEqual(result['trades'][0]['sample_kind'],'reconstructed')
            self.assertAlmostEqual(result['state']['cash'],0.)
            self.assertNotEqual(result['state']['quantity']%100,0)

    def test_null_daily_close_requires_a_timestamped_regular_close(self):
        from qount.research_data.paper_daily import yahoo_rows,NY
        day=dt.date(2026,10,21)
        stamps=[int(dt.datetime.combine(day-dt.timedelta(days=3-i),dt.time(9,30),NY).timestamp()) for i in range(4)]
        close_at=int(dt.datetime.combine(day,dt.time(16),NY).timestamp())
        q=dict(open=[100.]*4,high=[102.]*4,low=[99.]*4,close=[100.]*3+[None],volume=[1000.]*4)
        node=dict(timestamp=stamps,indicators=dict(quote=[q],adjclose=[dict(adjclose=[100.]*3+[None])]),
                  meta=dict(regularMarketPrice=101.,regularMarketTime=close_at))
        observed=dt.datetime(2026,10,22,5,tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            with patch('qount.research_data.paper_daily.get_json',side_effect=lambda url: {'chart':{'result':[copy.deepcopy(node)]}}):
                rows,_=yahoo_rows('TEST',observed,Path(folder)/'valid')
                self.assertEqual(rows[-1]['close'],101.)
                self.assertEqual(rows[-1]['close_basis'],'timestamped_regular_market_close')
            node['meta']['regularMarketTime']=close_at+3600
            with patch('qount.research_data.paper_daily.get_json',side_effect=lambda url: {'chart':{'result':[copy.deepcopy(node)]}}):
                with self.assertRaises(ValueError):yahoo_rows('TEST',observed,Path(folder)/'invalid')

    def test_cta_reuses_the_same_settled_session_without_network(self):
        from scripts.research.cta_r_forward_builder import _refresh_seed
        from qount.research.cta_r_forward import write_seed,CONTRACT
        observed=dt.datetime(2026,10,22,5,tzinfo=dt.timezone.utc)
        series={s:{'2015-01-05':100.,'2026-10-21':110.} for s in CONTRACT['universe']}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'seed.zip';write_seed(path,series,fetched_at=observed)
            with patch('scripts.research.cta_r_forward_builder.fetch_tencent_series',side_effect=AssertionError('duplicate request')):
                self.assertEqual(_refresh_seed(path,observed+dt.timedelta(minutes=3),'2026-10-21'),[])

    def test_yahoo_invalid_ohlc_tries_other_node_without_relaxing_validation(self):
        from qount.research_data.paper_daily import yahoo_rows, NY
        observed=dt.datetime(2026,10,23,6,tzinfo=dt.timezone.utc)
        stamp=int(dt.datetime(2026,10,22,9,30,tzinfo=NY).timestamp())
        valid={'chart':{'result':[dict(timestamp=[stamp], indicators=dict(
            quote=[dict(open=[100.],high=[102.],low=[99.],close=[101.],volume=[1000.])],
            adjclose=[dict(adjclose=[101.])]))]}}
        invalid=copy.deepcopy(valid)
        invalid['chart']['result'][0]['indicators']['quote'][0]['close']=[110.]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch('qount.research_data.paper_daily.get_json',side_effect=[invalid,valid]) as get:
                rows,_=yahoo_rows('FAS',observed,root)
            self.assertEqual(rows[-1]['close'],101.)
            self.assertIn('query2.finance.yahoo.com',get.call_args.args[0])
            # A later session with both nodes invalid must preserve the good cache.
            before=(root/'FAS-1d.json').read_bytes()
            with patch('qount.research_data.paper_daily.get_json',side_effect=[invalid,invalid]):
                with self.assertRaisesRegex(ValueError,'yahoo_unavailable'):
                    yahoo_rows('FAS',observed+dt.timedelta(days=1),root)
            self.assertEqual((root/'FAS-1d.json').read_bytes(),before)

    def test_tencent_http_failure_tries_backup_and_caches_only_valid_pair(self):
        from urllib.error import HTTPError
        from qount.research_data.paper_daily import tencent_etf_rows
        observed=dt.datetime(2026,10,23,11,tzinfo=dt.timezone.utc)
        rows=[[(observed.date()-dt.timedelta(days=249-i)).isoformat(), '10','11','12','9','1000']
              for i in range(250)]
        adjusted={'data':{'sh513100':{'qfqday':rows}}}
        raw={'data':{'sh513100':{'day':rows}}}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch('qount.research_data.paper_daily.get_json',side_effect=[
                HTTPError('https://web.ifzq.gtimg.cn',501,'Not Implemented',None,None),adjusted,raw]) as get:
                actual,_=tencent_etf_rows(observed,root)
            self.assertEqual(actual[-1]['date'],'2026-10-23')
            self.assertIn('proxy.finance.qq.com/ifzqgtimg',get.call_args.args[0])
            self.assertEqual(get.call_count,3)
            before=(root/'513100.json').read_bytes()
            with patch('qount.research_data.paper_daily.get_json',return_value={'data':{}}) as get:
                with self.assertRaisesRegex(ValueError,'tencent_etf_unavailable'):
                    tencent_etf_rows(observed+dt.timedelta(hours=2),root)
            self.assertEqual(get.call_count,2)
            self.assertEqual((root/'513100.json').read_bytes(),before)

    def test_tencent_invalid_raw_pair_is_retried_as_a_whole(self):
        from qount.research_data.paper_daily import tencent_etf_rows
        observed=dt.datetime(2026,10,23,11,tzinfo=dt.timezone.utc)
        rows=[[(observed.date()-dt.timedelta(days=249-i)).isoformat(), '10','11','12','9','1000']
              for i in range(250)]
        adjusted={'data':{'sh513100':{'qfqday':rows}}}
        raw={'data':{'sh513100':{'day':rows}}}
        invalid=copy.deepcopy(raw)
        invalid['data']['sh513100']['day'][-1][2]='20'
        with tempfile.TemporaryDirectory() as folder:
            with patch('qount.research_data.paper_daily.get_json',side_effect=[adjusted,invalid,adjusted,raw]) as get:
                actual,_=tencent_etf_rows(observed,folder)
            self.assertEqual(actual[-1]['close'],11.)
            self.assertEqual(get.call_count,4)

    def test_tencent_requests_settled_history_and_invalidates_open_ended_cache(self):
        from qount.research_data.paper_daily import tencent_etf_rows
        observed=dt.datetime(2026,10,23,11,tzinfo=dt.timezone.utc)
        rows=[[(observed.date()-dt.timedelta(days=249-i)).isoformat(), '2.200','2.243','2.246','2.196','1000']
              for i in range(250)]
        def get(url):
            self.assertIn(',day,,2026-10-23,500,',url)
            return {'data':{'sh513100':{'qfqday' if url.endswith(',qfq') else 'day':rows}}}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'513100.json').write_text(json.dumps(dict(fetched_at=observed.isoformat(),
                rows=[dict(date='2026-10-23',adjClose=2.24,close=2.243)],source_hash='old')))
            with patch('qount.research_data.paper_daily.get_json',side_effect=get) as fetch:
                actual,digest=tencent_etf_rows(observed,root)
                self.assertEqual(fetch.call_count,2)
            self.assertEqual(actual[-1]['adjClose'],2.243)
            self.assertEqual(actual[-1]['close'],2.243)
            with patch('qount.research_data.paper_daily.get_json',side_effect=AssertionError('duplicate request')):
                self.assertEqual(tencent_etf_rows(observed,root),(actual,digest))

    def test_successful_retry_clears_paper_error_without_duplicate_history(self):
        observed=dt.datetime(2026,10,23,11,tzinfo=dt.timezone.utc)
        rows=[dict(date=(observed.date()-dt.timedelta(days=249-i)).isoformat(),
                   open=10.,close=10.,adjClose=10.) for i in range(250)]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'forward.json'
            with patch('scripts.operations.run_research_paper.tencent_etf_rows',return_value=(rows,'a'*64)):
                run_account('etf',folder,observed)
            original=json.loads(path.read_text())
            with patch('scripts.operations.run_research_paper.tencent_etf_rows',side_effect=ValueError('unavailable')):
                with self.assertRaises(ValueError):run_account('etf',folder,observed)
            self.assertIsNotNone(json.loads(path.read_text())['last_error'])
            with patch('scripts.operations.run_research_paper.tencent_etf_rows',return_value=(rows,'a'*64)):
                result=run_account('etf',folder,observed)
            recovered=json.loads(path.read_text())
            self.assertEqual(result['appended'],0)
            self.assertIsNone(recovered['last_error'])
            self.assertEqual(recovered['observations'],original['observations'])
            self.assertEqual(recovered['trades'],original['trades'])


if __name__=='__main__':unittest.main()
