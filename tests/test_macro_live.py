"""Actual-position handover, causal scheduling and durable execution failure cases."""
import copy
import datetime as dt
import json
import os
import tempfile
import io
import urllib.error
import urllib.response
import unittest
from pathlib import Path
from unittest.mock import patch

import ccxt
from qount.execution.macro_live import MacroLive, MacroBlocked
from qount.research_data.bars import Bar
from qount.research_data.macro_live import MacroInputError, MacroLiveInputs, expected_feature_date, fetch_proxy_payload, parse_proxy, write_json
from qount.strategies.macro_1atr import STRATEGY_ID, SIGNAL_MAPPING, is_decision, trailing_update

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
        self.brackets=[dict(notionalFloor=0,notionalCap=10000,maintMarginRatio=.01,initialLeverage=50)]
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
    def fapiPrivateGetLeverageBracket(self,p):
        return [dict(symbol=s,brackets=copy.deepcopy(self.brackets))
                for s in ([p['symbol']] if p.get('symbol') else SIGNAL_MAPPING)]
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
    def test_higher_maintenance_rate_can_open_when_liquidation_cushion_is_sufficient(self):
        self.ex.brackets[0].update(maintMarginRatio=.025,initialLeverage=20)
        result=self.prepare()
        self.assertEqual(result['auto_action'],'ENTRY_FILLED_PROTECTED')
        self.assertEqual(self.live.state['position']['maintenance_margin_ratio'],.025)
        self.assertAlmostEqual(self.live.state['position']['buffer'],.04)
    def test_changed_venue_margin_rechecks_distance_before_mutating_exchange(self):
        self.ex.brackets[0]['maintMarginRatio']=.1
        with self.assertRaisesRegex(MacroBlocked,'live_liquidation_distance'):
            self.prepare()
        self.assertFalse(self.ex.events)
    def test_exchange_leverage_limit_remains_binding(self):
        self.ex.brackets[0]['initialLeverage']=3
        with self.assertRaisesRegex(MacroBlocked,'live_leverage_or_notional_limit'):
            self.prepare()
        self.assertFalse(self.ex.events)
    def test_candidate_sizing_receives_account_brackets_in_read_only_mode(self):
        self.macro();self.lease_inputs(NOW)
        self.ex.brackets[0].update(maintMarginRatio=.025,initialLeverage=20)
        self.live.execute=False
        with patch('qount.execution.macro_live.entry_candidates',return_value=([],{})) as candidates:
            result=self.live.cycle(NOW)
        rule=candidates.call_args.args[0]['CLUSDT']['rule']
        self.assertEqual(rule['leverage_brackets'][0]['maintMarginRatio'],.025)
        self.assertEqual(result['auto_action'],'HOLD_NO_SIGNAL')
        self.assertFalse(self.ex.events)
    def test_missing_account_brackets_cannot_fall_back_to_one_percent(self):
        self.macro();self.lease_inputs(NOW)
        with patch.object(self.ex,'fapiPrivateGetLeverageBracket',return_value=[]):
            with self.assertRaisesRegex(MacroBlocked,'live_brackets_incomplete'):
                self.live.cycle(NOW)
        self.assertFalse(self.ex.events)
    def test_nine_am_flat_cycle_warms_completed_features_without_venue_mutations(self):
        self.macro();self.lease_inputs(NOW-3600)
        with patch.object(self.live.inputs,'features',wraps=self.live.inputs.features) as fetch:
            result=self.live.cycle(NOW-3600)
        fetch.assert_called_once_with(NOW-3600)
        self.assertEqual(result['auto_action'],'WAIT_NY_1000')
        self.assertEqual(result['input_warmup']['status'],'READY')
        self.assertFalse(self.ex.events);self.assertIsNone(self.live.state['last_entry_decision'])
    def test_failed_early_warmup_leaves_decision_available_and_hides_error_message(self):
        self.macro();self.lease_inputs(NOW-3600)
        with patch.object(self.live.inputs,'features',side_effect=urllib.error.URLError('sensitive diagnostic')):
            result=self.live.cycle(NOW-3600)
        self.assertEqual(result['input_warmup'],{'status':'FAILED','error_type':'URLError'})
        self.assertEqual(result['auto_action'],'WAIT_NY_1000')
        self.assertNotIn('sensitive',json.dumps(result));self.assertFalse(self.ex.events)
        self.assertIsNone(self.live.state['last_entry_decision'])
    def test_other_flat_hours_do_not_download_proxy_inputs(self):
        self.macro();self.lease_inputs(NOW-7200)
        with patch.object(self.live.inputs,'features') as fetch:
            result=self.live.cycle(NOW-7200)
        fetch.assert_not_called();self.assertEqual(result['auto_action'],'WAIT_NY_1000')
    def test_after_close_and_early_morning_warmup_do_not_consume_entry_or_submit_orders(self):
        self.macro();self.lease_inputs(NOW)
        for hour in (NOW-4*3600, NOW+7*3600):  # New York 06:00 and 17:00
            with self.subTest(hour=hour), patch.object(self.live.inputs,'features') as fetch:
                result=self.live.cycle(hour)
                fetch.assert_called_once_with(hour)
                self.assertEqual(result['input_warmup']['status'],'READY')
                self.assertEqual(result['auto_action'],'WAIT_NY_1000')
        self.assertFalse(self.ex.events);self.assertIsNone(self.live.state['last_entry_decision'])
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
    def test_unpublished_year_blocks_flat_entry_before_fetching_inputs_or_submitting(self):
        self.macro();self.ex.events=[]
        now=int(dt.datetime(2029,1,2,15,tzinfo=dt.timezone.utc).timestamp())
        with self.assertRaisesRegex(MacroBlocked,'entry_calendar_unknown'):
            self.live.cycle(now)
        self.assertFalse(self.ex.events)
    def test_cross_year_expiry_works_on_new_year_holiday_without_inputs(self):
        self.prepare();p=self.live.state['position']
        now=int(dt.datetime(2027,1,1,15,tzinfo=dt.timezone.utc).timestamp())
        p['entry_time']=now-168*3600;p['max_hold_hours']=168
        result=self.live.cycle(now)
        self.assertEqual(result['exit_reason'],'time_exit');self.assertEqual(self.ex.q,0)
    def test_new_year_holiday_waits_and_first_regular_session_reaches_entry_decision(self):
        self.macro()
        holiday=int(dt.datetime(2027,1,1,15,tzinfo=dt.timezone.utc).timestamp())
        self.assertEqual(self.live.cycle(holiday)['auto_action'],'WAIT_NY_1000')
        now=int(dt.datetime(2027,1,4,15,tzinfo=dt.timezone.utc).timestamp())
        self.lease_inputs(now)
        with patch('qount.execution.macro_live.time.time',return_value=now+5), \
             patch('qount.execution.macro_live.entry_candidates',return_value=([],{'regime_off':1})) as candidates:
            result=self.live.cycle(now)
        self.assertEqual(result['auto_action'],'HOLD_NO_SIGNAL')
        self.assertEqual(candidates.call_args.args[3],now)
        self.assertEqual(self.live.state['last_entry_decision'],now)
    def test_unpublished_year_does_not_block_known_risk_exits(self):
        for reason in ('time_exit','funding_cost_exit','lease_income_unknown'):
            with self.subTest(reason=reason):
                # Fresh independent state/venue for each exit scenario.
                with tempfile.TemporaryDirectory() as temporary:
                    live=MacroLive(FakeExchange(),None,store_path=Path(temporary)/'execution.db',
                                   state_path=Path(temporary)/'state.json',handover=HANDOVER,execute=True)
                    live.state['phase']='macro';live.save()
                    live.prepare_entry(position(),NOW,{'CLUSDT':{'rule':RULE}})
                    p=live.state['position']
                    now=int(dt.datetime(2029,1,2,15,tzinfo=dt.timezone.utc).timestamp())
                    p.update(entry_time=now-168*3600,max_hold_hours=504,funding_lease_deadline=now)
                    if reason=='time_exit':p['max_hold_hours']=168
                    if reason=='funding_cost_exit':p['funding_exit_due']=now
                    with patch.object(live.exchange,'fapiPrivateGetIncome',side_effect=ccxt.RequestTimeout('injected')):
                        result=live.cycle(now)
                    self.assertEqual(result['exit_reason'],reason)
                    self.assertEqual(live.exchange.q,0)
    def test_unpublished_calendar_cannot_renew_a_due_lease(self):
        self.prepare();p=self.live.state['position'];self.live.protective(p,95.)
        now=int(dt.datetime(2029,1,2,15,tzinfo=dt.timezone.utc).timestamp())
        p.update(entry_time=now-168*3600,funding_lease_deadline=now,managed_through=now)
        self.lease_inputs(now)
        result=self.live.cycle(now)
        self.assertEqual(result['exit_reason'],'lease_calendar_unknown');self.assertEqual(self.ex.q,0)
        self.assertFalse(p['funding_lease_reviews'])
    def test_unpublished_calendar_reports_partial_management_and_keeps_native_stop(self):
        self.prepare();p=self.live.state['position']
        now=int(dt.datetime(2029,1,2,15,tzinfo=dt.timezone.utc).timestamp())
        p.update(entry_time=now-3600,funding_lease_deadline=now+167*3600,managed_through=now-3600)
        self.lease_inputs(now);self.ex.events=[];self.ex.price=130.
        data={'CLUSDT':{'trade':[Bar(now-3600,129.,132.,128.,130.)],'rule':RULE,'funding':[]}}
        with patch.object(self.live.inputs,'snapshot',return_value=(data,{})), \
             patch('qount.execution.macro_live.known_atr',return_value=5.):
            with self.assertRaisesRegex(MacroBlocked,'calendar_unknown_after_risk_management'):
                self.live.cycle(now)
        self.assertEqual(self.ex.q,.6)
        self.assertEqual(p['stop'],120.)
        self.assertEqual(p['managed_through'],now)
        self.assertEqual(self.ex.algos[p['stop_id']]['algoStatus'],'NEW')
        self.assertFalse(any(e[0]=='create_order' for e in self.ex.events))
    def test_due_exit_bypasses_income_failure_and_pending_stop_replacement(self):
        self.prepare();p=self.live.state['position'];p['max_hold_hours']=168
        self.live.state['pending_stop']={'client_id':'unknown-replacement','stop':95.}
        with patch.object(self.ex,'fapiPrivateGetIncome',side_effect=ccxt.RequestTimeout('injected')) as income:
            result=self.live.manage(p,self.live.positions(),NOW+168*3600)
        income.assert_not_called()
        self.assertEqual(result['exit_reason'],'time_exit');self.assertEqual(self.ex.q,0)
        self.assertIsNone(self.live.state['pending_stop'])
    def test_known_funding_exit_does_not_require_another_income_query(self):
        self.prepare();p=self.live.state['position'];p['funding_exit_due']=NOW+3600
        with patch.object(self.ex,'fapiPrivateGetIncome',side_effect=ccxt.RequestTimeout('injected')) as income:
            result=self.live.manage(p,self.live.positions(),NOW+3600)
        income.assert_not_called()
        self.assertEqual(result['exit_reason'],'funding_cost_exit');self.assertEqual(self.ex.q,0)
    def test_exit_and_stop_cleanup_do_not_depend_on_trade_history(self):
        self.prepare();p=self.live.state['position'];p['max_hold_hours']=168
        with patch.object(self.ex,'fapiPrivateGetUserTrades',side_effect=ccxt.RequestTimeout('injected')):
            result=self.live.manage(p,self.live.positions(),NOW+168*3600)
        self.assertEqual(result['auto_action'],'POSITION_CLOSED');self.assertEqual(self.ex.q,0)
        self.assertEqual(result['accounting_errors'],['RequestTimeout'])
        self.assertIsNone(self.live.state['position']);self.assertIsNone(self.live.state['pending_entry'])
        self.assertFalse(self.ex.fapiPrivateGetOpenAlgoOrders({}))
        self.assertEqual(sum(e==('create_order','SELL') for e in self.ex.events),1)
        self.assertEqual(self.make_live().cycle(NOW+3600)['auto_action'],'WAIT_NY_1000')
        self.assertEqual(sum(e==('create_order','SELL') for e in self.ex.events),1)
    def test_unknown_external_partial_reduction_still_blocks_without_orders(self):
        self.prepare();self.ex.q=.3;self.ex.events=[]
        with self.assertRaisesRegex(MacroBlocked,'managed_position_quantity_mismatch'):
            self.live.cycle(NOW+3600)
        self.assertFalse(any(e[0]=='create_order' for e in self.ex.events))
    def test_income_unknown_at_lease_deadline_flattens_without_renewing(self):
        self.prepare();p=self.live.state['position']
        with patch.object(self.ex,'fapiPrivateGetIncome',side_effect=ccxt.RequestTimeout('injected')):
            result=self.live.manage(p,self.live.positions(),p['funding_lease_deadline'])
        self.assertEqual(result['exit_reason'],'lease_income_unknown');self.assertEqual(self.ex.q,0)
    def test_partial_exit_retains_native_stop_and_restart_finishes_with_a_new_exit_id(self):
        self.prepare();p=self.live.state['position'];p['max_hold_hours']=168
        post=self.ex.fapiPrivatePostOrder
        def partial(params):
            raw=post({**params,'quantity':str(float(params['quantity'])/2)})
            raw.update(status='EXPIRED',origQty=params['quantity'])
            self.ex.orders[raw['clientOrderId']]=copy.deepcopy(raw)
            return raw
        with patch.object(self.ex,'fapiPrivatePostOrder',side_effect=partial):
            with self.assertRaisesRegex(MacroBlocked,'exit_partial_native_stop_retained'):
                self.live.manage(p,self.live.positions(),NOW+168*3600)
        self.assertEqual(self.ex.q,.3)
        self.assertEqual(self.ex.algos[p['stop_id']]['algoStatus'],'NEW')
        result=self.make_live().cycle(NOW+169*3600)
        self.assertEqual(result['auto_action'],'POSITION_CLOSED');self.assertEqual(self.ex.q,0)
        sells=[r['clientOrderId'] for r in self.ex.orders.values() if r.get('side')=='SELL']
        self.assertEqual(len(sells),2);self.assertEqual(len(set(sells)),2)
    def test_exit_post_timeout_reconciles_same_identity_without_another_sell(self):
        self.prepare();p=self.live.state['position'];p['max_hold_hours']=168
        post=self.ex.fapiPrivatePostOrder
        def timeout(params):
            post(params)
            raise ccxt.RequestTimeout('injected')
        with patch.object(self.ex,'fapiPrivatePostOrder',side_effect=timeout):
            result=self.live.manage(p,self.live.positions(),NOW+168*3600)
        self.assertEqual(result['auto_action'],'POSITION_CLOSED');self.assertEqual(self.ex.q,0)
        self.assertEqual(sum(e==('create_order','SELL') for e in self.ex.events),1)
    def test_restart_reconciles_uncertain_exit_query_before_clearing_protection(self):
        self.prepare();p=self.live.state['position'];p['max_hold_hours']=168
        with patch.object(self.ex,'fapiPrivateGetOrder',side_effect=ccxt.RequestTimeout('injected')):
            with self.assertRaises(ccxt.RequestTimeout):
                self.live.manage(p,self.live.positions(),NOW+168*3600)
        self.assertEqual(self.ex.q,0);self.assertIsNotNone(p['pending_exit'])
        result=self.make_live().cycle(NOW+169*3600)
        self.assertEqual(result['auto_action'],'POSITION_CLOSED')
        self.assertEqual(sum(e==('create_order','SELL') for e in self.ex.events),1)
        self.assertFalse(self.ex.fapiPrivateGetOpenAlgoOrders({}))
    def lease_inputs(self, now, eligible=True):
        class Inputs:
            def snapshot(inner,*args,**kwargs):
                return {'CLUSDT':{'trade':[],'rule':RULE,'funding':[
                    dict(fundingTime=t*1000,fundingRate='0') for t in range(now-72*3600,now,8*3600)]}},{}
            def features(inner,*args):return {'CLUSDT':[dict(available=now-3600,hold_structural=eligible)]}
        self.live.inputs=Inputs()
    def test_seven_day_lease_renews_same_quantity_and_never_extends_twenty_one_day_deadline(self):
        self.prepare();p=self.live.state['position'];self.live.protective(p,98.)
        now=NOW+168*3600;self.lease_inputs(now)
        count=sum(e[0]=='create_order' for e in self.ex.events)
        result=self.live.manage(p,self.live.positions(),now)
        self.assertEqual(result['auto_action'],'HOLD_MACRO_POSITION');self.assertEqual(p['quantity'],.6)
        self.assertTrue(p['funding_lease_reviews'][-1]['allowed'])
        self.assertEqual(p['funding_lease_deadline'],NOW+336*3600)
        self.assertEqual(sum(e[0]=='create_order' for e in self.ex.events),count)
    def test_lease_uses_reduced_current_budget_even_for_a_larger_inherited_position(self):
        self.prepare();p=self.live.state['position'];self.live.protective(p,95.)
        now=NOW+168*3600;self.lease_inputs(now)
        result=self.live.manage(p,self.live.positions(),now)
        self.assertEqual(result['exit_reason'],'lease_risk_budget')
        self.assertEqual(p['funding_lease_reviews'][-1]['risk_budget'],15*.25)
        self.assertEqual(self.ex.q,0)
        self.assertIsNone(self.live.state['position'])
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
    def proxy_payload(self):
        timestamps=[NOW-i*86400 for i in range(260,0,-1)]
        quote={k:[100.]*260 for k in ('open','high','low','close','volume')}
        return {'chart':{'result':[{'timestamp':timestamps,'indicators':{
            'quote':[quote],'adjclose':[{'adjclose':[100.]*260}]}}]}}
    def test_null_completed_daily_bar_reports_exact_ticker_and_date(self):
        payload=self.proxy_payload();payload['chart']['result'][0]['indicators']['quote'][0]['close'][-1]=None
        with self.assertRaises(MacroInputError) as caught:parse_proxy('SPY',payload,NOW)
        self.assertEqual(caught.exception.details,dict(code='proxy_invalid_prices',ticker='SPY',date='2026-06-15'))
    def test_invalid_daily_response_retries_alternate_before_accepting_and_caching(self):
        good=self.proxy_payload();bad=copy.deepcopy(good)
        bad['chart']['result'][0]['indicators']['adjclose'][0]['adjclose'][-1]=None
        with tempfile.TemporaryDirectory() as tmp, patch('qount.research_data.macro_live.MACRO_TEN',{'SPY'}), \
             patch('qount.strategies.macro_features.MACRO_TEN',{'SPY'}), \
             patch('qount.research_data.macro_live.SIGNAL_MAPPING',{'SPYUSDT':'SPY'}), \
             patch('qount.research_data.macro_live.urllib.request.OpenerDirector.open',side_effect=[
                 io.StringIO(json.dumps(bad)),io.StringIO(json.dumps(good))]) as fetch:
            MacroLiveInputs(None,tmp).features(NOW)
            self.assertEqual(fetch.call_count,2)
            self.assertIn('query2.finance.yahoo.com',fetch.call_args.args[0].full_url)
            self.assertEqual(json.loads((Path(tmp)/'yahoo-SPY-2026-06-15.json').read_text()),good)
    def test_both_nodes_missing_latest_session_never_accept_or_cache_old_data(self):
        stale=self.proxy_payload();node=stale['chart']['result'][0]
        node['timestamp'].pop()
        for values in node['indicators']['quote'][0].values():values.pop()
        node['indicators']['adjclose'][0]['adjclose'].pop()
        with tempfile.TemporaryDirectory() as tmp, patch('qount.research_data.macro_live.MACRO_TEN',{'SPY'}), \
             patch('qount.strategies.macro_features.MACRO_TEN',{'SPY'}), \
             patch('qount.research_data.macro_live.SIGNAL_MAPPING',{'SPYUSDT':'SPY'}), \
             patch('qount.research_data.macro_live.urllib.request.OpenerDirector.open',side_effect=[
                 io.StringIO(json.dumps(stale)),io.StringIO(json.dumps(stale))]) as fetch:
            with self.assertRaisesRegex(MacroInputError,'proxy_latest_completed_session_missing'):
                MacroLiveInputs(None,tmp).features(NOW)
            self.assertEqual(fetch.call_count,2);self.assertEqual(list(Path(tmp).iterdir()),[])
    def test_corrupt_same_date_cache_is_refetched_and_good_cache_needs_no_network(self):
        good=self.proxy_payload()
        with tempfile.TemporaryDirectory() as tmp, patch('qount.research_data.macro_live.MACRO_TEN',{'SPY'}), \
             patch('qount.strategies.macro_features.MACRO_TEN',{'SPY'}), \
             patch('qount.research_data.macro_live.SIGNAL_MAPPING',{'SPYUSDT':'SPY'}), \
             patch('qount.research_data.macro_live.urllib.request.OpenerDirector.open',return_value=io.StringIO(json.dumps(good))) as fetch:
            path=Path(tmp)/'yahoo-SPY-2026-06-15.json';path.write_text('bad json')
            inputs=MacroLiveInputs(None,tmp);first=inputs.features(NOW);second=inputs.features(NOW)
            self.assertEqual(first,second);self.assertEqual(fetch.call_count,1)
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
    def test_proxy_network_failure_uses_one_bounded_alternate_attempt(self):
        payload={'chart':{'result':[]}}
        with patch('qount.research_data.macro_live.urllib.request.OpenerDirector.open',side_effect=[
                urllib.error.URLError('temporary'),io.StringIO(json.dumps(payload))]) as fetch:
            self.assertEqual(fetch_proxy_payload('SPY',NOW),payload)
        self.assertEqual(fetch.call_count,2)
        self.assertIn('query2.finance.yahoo.com',fetch.call_args.args[0].full_url)
        self.assertTrue(all(c.kwargs['timeout']==5 for c in fetch.call_args_list))
    def test_prefetch_can_retry_both_nodes_after_backoff(self):
        payload=self.proxy_payload()
        with patch('qount.research_data.macro_live.urllib.request.OpenerDirector.open',side_effect=[
                urllib.error.URLError('temporary'),urllib.error.URLError('temporary'),
                io.StringIO(json.dumps(payload))]) as fetch, \
             patch('qount.research_data.macro_live.time.sleep') as sleep:
            self.assertEqual(fetch_proxy_payload('SPY',NOW-4*3600,max_attempts=4),payload)
        self.assertEqual(fetch.call_count,3);sleep.assert_called_once_with(1)
        self.assertIn('query1.finance.yahoo.com',fetch.call_args.args[0].full_url)
    def test_proxy_exhausted_attempts_raise_instead_of_using_old_data(self):
        with patch('qount.research_data.macro_live.urllib.request.OpenerDirector.open',side_effect=urllib.error.URLError('temporary')) as fetch:
            with self.assertRaises(urllib.error.URLError):fetch_proxy_payload('SPY',NOW)
        self.assertEqual(fetch.call_count,2)
    def test_invalid_proxy_json_is_not_treated_as_a_network_retry(self):
        with patch('qount.research_data.macro_live.urllib.request.OpenerDirector.open',return_value=io.StringIO('bad json')) as fetch:
            with self.assertRaises(json.JSONDecodeError):fetch_proxy_payload('SPY',NOW)
        self.assertEqual(fetch.call_count,1)
    def test_public_daily_download_bypasses_inherited_proxies_without_changing_environment(self):
        payload={'chart':{'result':[]}}
        proxy='http://unreachable-proxy.invalid:3128'
        environment={key:proxy for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy')}
        environment.update(NO_PROXY='',no_proxy='')
        requests=[]
        def https_open(request):
            requests.append(request)
            self.assertEqual(request.host,'query1.finance.yahoo.com')
            self.assertFalse(request.has_proxy())
            self.assertIsNone(request.get_header('Proxy-authorization'))
            response=urllib.response.addinfourl(io.BytesIO(json.dumps(payload).encode()),{},request.full_url,200)
            response.msg='OK'
            return response
        with patch.dict(os.environ,environment), patch('urllib.request.HTTPSHandler.https_open',side_effect=https_open):
            before=dict(os.environ)
            self.assertEqual(fetch_proxy_payload('SPY',NOW),payload)
            self.assertEqual(dict(os.environ),before)
        self.assertEqual(len(requests),1)


if __name__=='__main__':unittest.main()
