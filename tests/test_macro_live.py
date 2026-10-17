"""Actual-position handover, causal scheduling and durable execution failure cases."""
import copy
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ccxt
from qount.execution.macro_live import MacroLive, MacroBlocked
from qount.research_data.macro_live import MacroLiveInputs, expected_feature_date, parse_proxy, write_json
from qount.strategies.macro_1atr import STRATEGY_ID, is_decision, trailing_update

NOW = int(dt.datetime(2026, 6, 16, 14, tzinfo=dt.timezone.utc).timestamp())
HANDOVER = json.loads(Path('config/macro-1atr.json').read_text())['handover']
RULE = {'symbol':'CLUSDT','status':'TRADING','contractType':'TRADIFI_PERPETUAL','marginAsset':'USDT',
        'filters':[{'filterType':'PRICE_FILTER','tickSize':'.01'}]}


def position():
    return dict(symbol='CLUSDT',quantity=.6,entry_price=100.25,initial_stop=90.,stop=90.,
                notional_usdt=60.15,margin_usdt=12.03,leverage=5,stress_risk_usdt=7.,
                structural_risk_usdt=6.15,risk_budget_usdt=7.5,entry_time=NOW,
                structural_r=10.25,highest_close=100.25,hold_feature='hold_structural',
                max_hold_hours=504,tactical_setup='mean_reversion',funding_reserve_fraction=.002,
                funding_lease_deadline=NOW+168*3600,funding_lease_hours=168,
                funding_cost_cap_usdt=.62,funding_adverse_paid=0.,funding_lease_reviews=[],
                entry_id='qm1-entry-fixture',signal_id='signal:CL:fixture',managed_through=NOW)


class FakeExchange:
    def __init__(self):
        self.q=0.;self.price=100.;self.orders={};self.algos={};self.events=[]
        self.fraction=1.;self.timeout_entry=False;self.fail_protection=False;self.query_timeout=False
        self.isolated=False;self.income=[]
    def fapiPrivateV3GetPositionRisk(self,p):
        return [] if self.q==0 else [dict(symbol='CLUSDT',positionAmt=str(self.q),entryPrice=str(self.price))]
    def fapiPrivateV2GetPositionRisk(self,p):
        return [dict(symbol='CLUSDT',positionAmt=str(self.q),marginType='isolated' if self.isolated else 'cross')]
    def fapiPrivateGetOpenOrders(self,p):return []
    def fapiPrivateGetOpenAlgoOrders(self,p):return [copy.deepcopy(r) for r in self.algos.values() if r['algoStatus'] in {'NEW','WORKING'}]
    def fapiPrivateGetAlgoOrder(self,p):
        if self.query_timeout:raise ccxt.RequestTimeout('signed URL must not escape')
        if p['clientAlgoId'] not in self.algos:raise ccxt.OrderNotFound('unknown algo')
        self.events.append(('query_stop',p['clientAlgoId']))
        return copy.deepcopy(self.algos[p['clientAlgoId']])
    def fapiPrivatePostAlgoOrder(self,p):
        self.events.append(('create_stop',p['clientAlgoId']))
        if self.fail_protection:raise ccxt.ExchangeError('rejected')
        self.algos[p['clientAlgoId']]={**p,'orderType':p['type'],'algoStatus':'NEW','algoId':len(self.algos)+1,'actualOrderId':''}
        return copy.deepcopy(self.algos[p['clientAlgoId']])
    def fapiPrivateDeleteAlgoOrder(self,p):
        self.events.append(('cancel_stop',p['clientAlgoId']))
        self.algos[p['clientAlgoId']]['algoStatus']='CANCELED'
        return copy.deepcopy(self.algos[p['clientAlgoId']])
    def fapiPrivateGetOrder(self,p):
        if 'origClientOrderId' in p:return copy.deepcopy(self.orders[p['origClientOrderId']])
        return copy.deepcopy(next(r for r in self.orders.values() if str(r['orderId'])==str(p['orderId'])))
    def fapiPrivatePostOrder(self,p):
        self.events.append(('create_order',p['side']))
        quantity=float(p['quantity']);q=quantity*self.fraction if p['side']=='BUY' else min(quantity,self.q)
        self.q+=q if p['side']=='BUY' else -q
        row=dict(symbol=p['symbol'],clientOrderId=p['newClientOrderId'],side=p['side'],orderId=len(self.orders)+1,
                 status='FILLED' if q==quantity else 'EXPIRED',origQty=str(quantity),executedQty=str(q),
                 avgPrice=str(self.price),cumQuote=str(q*self.price),updateTime=NOW*1000)
        self.orders[p['newClientOrderId']]=row
        if self.timeout_entry and p['side']=='BUY':raise ccxt.RequestTimeout('post timeout')
        return copy.deepcopy(row)
    def fapiPrivateGetUserTrades(self,p):
        order=next(r for r in self.orders.values() if str(r['orderId'])==str(p['orderId']))
        q=float(order['executedQty'])
        return [] if q==0 else [dict(id=str(order['orderId']),orderId=order['orderId'],qty=str(q),price=order['avgPrice'],
                                    commission=str(q*self.price*.0005),commissionAsset='USDT',time=NOW*1000)]
    def fapiPrivateV3GetAccount(self,p):return {'assets':[dict(asset='USDT',walletBalance='15',marginBalance='15',availableBalance='15')]}
    def fapiPrivateGetMultiAssetsMargin(self,p):return {'multiAssetsMargin':False}
    def fapiPrivateGetPositionSideDual(self,p):return {'dualSidePosition':False}
    def fapiPrivateGetCommissionRate(self,p):return {'takerCommissionRate':'.0005'}
    def fapiPrivateGetLeverageBracket(self,p):return [{'brackets':[dict(notionalFloor=0,notionalCap=10000,maintMarginRatio=.01,initialLeverage=50)]}]
    def fapiPublicGetDepth(self,p):return dict(T=NOW*1000,asks=[['100','100']])
    def fapiPublicGetExchangeInfo(self,p):return {'symbols':[RULE]}
    def fapiPrivatePostMarginType(self,p):self.events.append(('margin',p));self.isolated=True;return {}
    def fapiPrivatePostLeverage(self,p):self.events.append(('leverage',p));return dict(leverage=p['leverage'],maxNotionalValue=10000)
    def fapiPublicGetTime(self,p):return dict(serverTime=(NOW+5)*1000)
    def fapiPrivateGetIncome(self,p):return copy.deepcopy(self.income)
    def fapiPublicGetTickerPrice(self,p):return {'price':str(self.price)}


class LiveExecutionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.ex=FakeExchange()
        self.env=patch.dict(os.environ,{'QOUNT_LIVE_ENABLE':'true','QOUNT_PRIMARY_STRATEGY':STRATEGY_ID});self.env.start()
        self.clock=patch('qount.execution.macro_live.time.time',return_value=NOW+5);self.clock.start()
        self.live=self.make_live()
    def tearDown(self):self.clock.stop();self.env.stop();self.temp.cleanup()
    def make_live(self,execute=True):return MacroLive(self.ex,None,store_path=self.root/'execution.db',state_path=self.root/'state.json',handover=HANDOVER,execute=execute)
    def macro(self):self.live.state['phase']='macro';self.live.save()
    def legacy(self):
        h=HANDOVER;self.ex.q=h['quantity'];self.ex.price=96.1
        self.ex.orders[h['entry_client_id']]=dict(symbol=h['symbol'],status='FILLED',executedQty='.15',avgPrice='96.1')
        self.ex.algos[h['stop_client_id']]=dict(symbol=h['symbol'],side='SELL',orderType='STOP_MARKET',algoStatus='NEW',
                algoId=42,quantity='.15',triggerPrice='90.06',workingType='MARK_PRICE',reduceOnly=True,clientAlgoId=h['stop_client_id'])
    def prepare(self):self.macro();return self.live.prepare_entry(position(),NOW,{'CLUSDT':{'rule':RULE}})
    def test_legacy_holding_keeps_exact_stop_and_never_fetches_strategy_inputs_or_mutates_venue(self):
        self.legacy();result=self.live.cycle(NOW)
        self.assertEqual(result['auto_action'],'HOLD_LEGACY_POSITION')
        self.assertEqual(result['protection_check']['stop_price'],90.06)
        self.assertEqual(self.ex.q,.15)
        self.assertFalse(any(e[0] in {'create_order','create_stop','cancel_stop','margin','leverage'} for e in self.ex.events))
        self.assertFalse((self.root/'state.json').exists())
    def test_changed_legacy_quantity_blocks_without_closing_or_replacing_stop(self):
        self.legacy();self.ex.q=.2
        with self.assertRaisesRegex(MacroBlocked,'legacy_position_changed'):self.live.cycle(NOW)
        self.assertEqual(self.ex.q,.2)
        self.assertEqual(self.ex.algos[HANDOVER['stop_client_id']]['algoStatus'],'NEW')
    def test_flat_handover_cancels_only_legacy_orphan_then_waits_for_new_york_decision(self):
        self.legacy();self.ex.q=0
        result=self.live.cycle(NOW+3600)
        self.assertEqual(result['auto_action'],'WAIT_NY_1000')
        self.assertEqual(self.live.state['phase'],'macro')
        self.assertEqual(self.ex.algos[HANDOVER['stop_client_id']]['algoStatus'],'CANCELED')
    def test_foreign_algo_prevents_handover_and_is_never_canceled(self):
        self.legacy();self.ex.q=0;self.ex.algos['foreign']={**self.ex.algos[HANDOVER['stop_client_id']],'clientAlgoId':'foreign'}
        with self.assertRaisesRegex(MacroBlocked,'foreign_algo'):self.live.cycle(NOW+3600)
        self.assertFalse(any(e[0]=='cancel_stop' for e in self.ex.events))
    def test_partial_ioc_is_protected_at_actual_quantity_and_actual_fill_price(self):
        self.ex.fraction=.5;result=self.prepare();p=self.live.state['position']
        self.assertEqual(result['auto_action'],'ENTRY_FILLED_PROTECTED');self.assertEqual(p['quantity'],.3)
        self.assertEqual(p['entry_price'],100.);self.assertEqual(p['structural_r'],10.)
        stop=self.ex.algos[p['stop_id']]
        self.assertEqual(float(stop['quantity']),.3);self.assertEqual(stop['workingType'],'CONTRACT_PRICE')
        self.assertEqual(stop['reduceOnly'],'true')
        self.assertIsNone(self.live.state['pending_entry'])
        self.assertEqual(len(self.live.store.inflight()),0)
    def test_ioc_no_fill_never_creates_stop_or_retries_entry(self):
        self.ex.fraction=0;result=self.prepare()
        self.assertEqual(result['auto_action'],'ENTRY_IOC_UNFILLED')
        self.assertIsNone(self.live.state['position']);self.assertFalse(self.ex.algos)
        self.assertEqual(self.live.cycle(NOW)['auto_action'],'HOLD_ALREADY_PROCESSED')
    def test_post_timeout_uses_same_order_id_and_does_not_duplicate_entry(self):
        self.ex.timeout_entry=True;result=self.prepare()
        self.assertEqual(result['auto_action'],'ENTRY_FILLED_PROTECTED')
        self.assertEqual(sum(e==('create_order','BUY') for e in self.ex.events),1)
        restarted=self.make_live();self.assertIsNone(restarted.state['pending_entry'])
        self.assertEqual(restarted.state['position']['quantity'],.6)
    def test_stop_replacement_acknowledged_and_queried_before_original_cancel(self):
        self.prepare();p=self.live.state['position'];old=p['stop_id'];self.ex.events=[]
        self.live.protective(p,95.)
        kinds=[e[0] for e in self.ex.events]
        self.assertLess(kinds.index('create_stop'),kinds.index('query_stop'))
        self.assertLess(kinds.index('query_stop'),kinds.index('cancel_stop'))
        self.assertEqual(self.ex.algos[old]['algoStatus'],'CANCELED')
        self.assertEqual(self.ex.algos[p['stop_id']]['algoStatus'],'NEW')
    def test_unknown_replacement_preserves_old_stop_and_restart_queries_without_recreate(self):
        self.prepare();p=self.live.state['position'];old=p['stop_id'];self.ex.query_timeout=True
        with self.assertRaises(ccxt.RequestTimeout):self.live.protective(p,95.)
        self.assertEqual(self.ex.algos[old]['algoStatus'],'NEW');self.assertEqual(p['stop_id'],old)
        self.ex.query_timeout=False;before=sum(e[0]=='create_stop' for e in self.ex.events)
        restarted=self.make_live();restarted.protective(restarted.state['position'],95.)
        self.assertEqual(sum(e[0]=='create_stop' for e in self.ex.events),before)
        self.assertEqual(self.ex.algos[old]['algoStatus'],'CANCELED')
    def test_initial_protection_failure_flattens_only_new_exposure_and_clears_pending_entry(self):
        self.ex.fail_protection=True
        with self.assertRaisesRegex(MacroBlocked,'initial_protection_failed'):self.prepare()
        self.assertEqual(self.ex.q,0);self.assertIsNone(self.live.state['pending_entry'])
        self.assertIsNone(self.live.state['position'])
        self.assertEqual([e[1] for e in self.ex.events if e[0]=='create_order'],['BUY','SELL'])
    def test_restart_finishes_emergency_exit_cleanup_before_recovering_the_old_entry_intent(self):
        self.ex.query_timeout=True
        with self.assertRaises(ccxt.RequestTimeout):self.prepare()
        self.assertEqual(self.ex.q,0)
        self.assertIsNotNone(self.live.state['pending_entry'])
        self.assertEqual(self.live.state['position']['exit_reason'],'initial_protection_failed')
        self.ex.query_timeout=False
        restarted=self.make_live();result=restarted.cycle(NOW+3600)
        self.assertEqual(result['auto_action'],'POSITION_CLOSED')
        self.assertIsNone(restarted.state['pending_entry']);self.assertIsNone(restarted.state['position'])
        self.assertEqual(sum(e==('create_order','BUY') for e in self.ex.events),1)
    def test_funding_budget_counts_debits_and_not_credits_and_records_actual_receipts(self):
        self.prepare();p=self.live.state['position'];p['funding_cost_cap_usdt']=.2
        self.ex.income=[dict(tranId=1,time=(NOW+100)*1000,asset='USDT',income='-.3'),
                        dict(tranId=2,time=(NOW+200)*1000,asset='USDT',income='1')]
        self.live.funding_paid(p,NOW+3600)
        self.assertEqual(p['funding_adverse_paid'],.3);self.assertEqual(p['funding'],.7)
        self.assertEqual(p['funding_exit_due'],NOW+3600)
        self.live.funding_paid(p,NOW+3600) # immutable retry
    def test_read_only_cycle_never_executes_or_changes_handover(self):
        self.legacy();readonly=self.make_live(execute=False)
        self.assertEqual(readonly.cycle(NOW)['auto_action'],'HOLD_LEGACY_POSITION')
        self.assertFalse((self.root/'state.json').exists())
        with self.assertRaisesRegex(MacroBlocked,'not_authorized'):readonly.prepare_entry(position(),NOW,{'CLUSDT':{'rule':RULE}})
    def test_old_strategy_authorization_cannot_enter_corrected_strategy(self):
        with patch.dict(os.environ,{'QOUNT_PRIMARY_STRATEGY':'one_atr_macro_v0_1'}):
            with self.assertRaisesRegex(MacroBlocked,'not_authorized'):self.live.cycle(NOW)
        self.assertFalse(self.ex.events)
    def test_holding_expiry_closes_without_waiting_for_proxy_data_or_a_trading_day(self):
        self.prepare();p=self.live.state['position'];p['max_hold_hours']=168
        result=self.live.manage(p,self.live.positions(),NOW+168*3600)
        self.assertEqual(result['exit_reason'],'time_exit');self.assertEqual(self.ex.q,0)
    def lease_inputs(self, now, eligible=True):
        class Inputs:
            def snapshot(inner,*args,**kwargs):
                return {'CLUSDT':{'trade':[],'rule':RULE,'funding':[
                    dict(fundingTime=t*1000,fundingRate='0') for t in range(now-72*3600,now,8*3600)]}},{}
            def features(inner,*args):return {'CLUSDT':[dict(available=now-3600,hold_structural=eligible)]}
        self.live.inputs=Inputs()
    def test_seven_day_lease_renews_same_quantity_and_never_extends_twenty_one_day_deadline(self):
        self.prepare();p=self.live.state['position'];self.live.protective(p,95.)
        now=NOW+168*3600;self.lease_inputs(now)
        count=sum(e[0]=='create_order' for e in self.ex.events)
        result=self.live.manage(p,self.live.positions(),now)
        self.assertEqual(result['auto_action'],'HOLD_MACRO_POSITION');self.assertEqual(p['quantity'],.6)
        self.assertTrue(p['funding_lease_reviews'][-1]['allowed'])
        self.assertEqual(p['funding_lease_deadline'],NOW+336*3600)
        self.assertEqual(sum(e[0]=='create_order' for e in self.ex.events),count)
    def test_failed_lease_exits_in_full_without_partial_resize(self):
        self.prepare();p=self.live.state['position'];self.live.protective(p,95.)
        p['funding_cost_cap_usdt']=.001;now=NOW+168*3600;self.lease_inputs(now)
        result=self.live.manage(p,self.live.positions(),now)
        self.assertEqual(result['exit_reason'],'lease_cost_budget');self.assertEqual(self.ex.q,0)
        self.assertIsNone(self.live.state['position'])
    def test_triggered_native_stop_links_actual_exit_order_and_fills_before_handover(self):
        self.prepare();p=self.live.state['position'];identity=p['stop_id']
        raw=self.ex.fapiPrivatePostOrder(dict(symbol='CLUSDT',side='SELL',quantity=str(p['quantity']),newClientOrderId='exchange-generated-stop-fill'))
        self.ex.algos[identity].update(algoStatus='FINISHED',actualOrderId=str(raw['orderId']))
        self.live.cycle(NOW+3600)
        actual=self.live.store.get_order('exchange-generated-stop-fill')
        self.assertEqual(actual['strategy_id'],STRATEGY_ID);self.assertEqual(actual['status'],'FILLED')
        self.assertEqual(actual['executed_quantity'],.6);self.assertIsNone(self.live.state['position'])


class SharedRuleTest(unittest.TestCase):
    def test_new_york_decision_clock_follows_dst_and_rejects_weekends(self):
        for date,hour in (('2026-06-16',14),('2026-12-15',15)):
            now=int(dt.datetime.fromisoformat(date).replace(hour=hour,tzinfo=dt.timezone.utc).timestamp())
            self.assertTrue(is_decision(now));self.assertFalse(is_decision(now-3600))
        self.assertFalse(is_decision(int(dt.datetime(2026,10,17,14,tzinfo=dt.timezone.utc).timestamp())))
    def test_trailing_activates_only_after_two_r_and_never_lowers_stop(self):
        p=position();p.update(entry_price=100.,structural_r=5.,highest_close=100.)
        updated,reason=trailing_update(p,109.,2.,.01)
        self.assertEqual(updated['stop'],90.);self.assertIsNone(reason)
        updated,reason=trailing_update(updated,110.,2.,.01)
        self.assertEqual(updated['stop'],106.)
        next_,reason=trailing_update(updated,109.,2.,.01)
        self.assertEqual(next_['stop'],106.)
        crossed,reason=trailing_update(dict(updated,highest_close=120.),110.,2.,.01)
        self.assertEqual(reason,'crossed_trailing_stop');self.assertEqual(p['stop'],90.)
    def test_proxy_parser_matches_original_historical_feature_input(self):
        cache=Path('state/research_cache/binance_macro_attack_20261015/yahoo-SPY-20250101-2026-10-15.json')
        if not cache.exists():self.skipTest('historical public cache absent')
        _,bars,dates,_=parse_proxy('SPY',json.loads(cache.read_text()),1792022400)
        self.assertEqual(dates[-1],'2026-10-14');self.assertTrue(all(b.t<=1792022400 for b in bars))
    def test_completed_feature_session_handles_holiday_and_weekend(self):
        now=int(dt.datetime(2026,7,6,14,tzinfo=dt.timezone.utc).timestamp())
        self.assertEqual(expected_feature_date(now).isoformat(),'2026-07-02')


if __name__=='__main__':unittest.main()
