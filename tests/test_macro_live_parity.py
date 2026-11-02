"""Compare corrected live decisions against the retained selected research, offline only."""
import unittest
import json
from pathlib import Path
from unittest.mock import patch
from qount.research.binance_etf_leverage import load_inputs,replay
from qount.research.binance_macro_attack import macro_features,directional_book
from qount.research.binance_macro_liquidity import load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case
from qount.research_data.archives import timestamp
from qount.strategies.macro_episodes import episode_confirmations
from qount.strategies.macro_gates import mean_reversion_gap_confirmations
from qount.strategies.macro_1atr import entry_candidates,scaled_features


class MacroHistoricalParityTest(unittest.TestCase):
    @unittest.skipUnless(Path("state/research_runs/binance_macro_account_review_20261016/base_account.json").exists(), "retained local research inputs unavailable")
    def test_selected_research_curves_trades_and_live_entry_geometry_match(self):
        root=Path('state/research_runs/binance_macro_account_review_20261016')
        review=json.loads((root/'review.json').read_text())
        cache=Path('state/research_cache/binance_macro_attack_20261015')
        features,_=macro_features(cache,'2026-10-15')
        data,_=load_inputs(cache,timestamp('2026-07-30'),timestamp('2026-10-15'),symbols=tuple(features))
        for folder,start,end,subset in (
         ('binance_macro_earlier_20260611_20260730','2026-06-11','2026-07-30',tuple(s for s in features if s!='SMHUSDT')),
         ('binance_macro_prefix_20260407_20260611','2026-04-07','2026-06-11',('SPYUSDT','QQQUSDT','XAUUSDT','COPPERUSDT','CLUSDT'))):
         prefix,_=load_inputs(Path('state/research_cache')/folder,timestamp(start),timestamp(end),symbols=subset)
         data={s:{**d,**{k:prefix[s][k]+d[k] for k in ('trade','mark','funding')}} if s in prefix else d for s,d in data.items()}
        book,signals=directional_book(data,features,'long',20/3)
        assert signals==scaled_features(features)
        anchors=episode_confirmations(book,signals,'no_chase')
        gap=mean_reversion_gap_confirmations(book,signals,anchors)
        gates={key:{**c,'eligible':c['eligible'] and gap[key]['eligible'],'reason':gap[key]['reason'] if c['eligible'] else c['reason']} for key,c in anchors.items()}
        caps,_,_=load_capacity_contexts(anchors,Path('state/research_cache/binance_macro_liquidity_20261015'))
        def historical_entry_candidates(*args, **kwargs):
            # The retained 50% study remains frozen when the live budget changes.
            with patch('qount.strategies.macro_1atr.RISK_FRACTION', review['parameters']['risk_fraction']):
                return entry_candidates(*args, **kwargs)
        verified=[]
        for scenario,fee,slip in (('base',.0005,.0025),('double_cost',.001,.005)):
         expected=json.loads((root/f'{scenario}_account.json').read_text())
         actual=replay(cost_case(book,scenario),signals,capital=review['replay_capital'],fee=fee,slip=slip,
                       entry_liquidity_caps=caps,entry_confirmations=gates,**review['parameters'])
         closed=[t for t in actual['trades'] if t['exit_reason']!='end_of_sample']
         censored=[t for t in actual['trades'] if t['exit_reason']=='end_of_sample']
         actual['summary'].update(scenario=scenario,closed_trades=len(closed),censored_trades=len(censored),closed_pnl=sum(t['net_pnl'] for t in closed),censored_pnl=sum(t['net_pnl'] for t in censored))
         self.assertEqual(actual,expected,scenario)
         for t in expected['trades']:
          candidates,_=historical_entry_candidates(cost_case(book,scenario),signals,caps,t['entry_time'],t['equity_before_entry'],fee=fee,slip=slip)
          assert candidates and candidates[0]['symbol']==t['symbol'],(scenario,t['entry_time'],'ranking')
          p=candidates[0]
          for key in ('quantity','entry_price','initial_stop','leverage','risk_budget_usdt','stress_risk_usdt','margin_usdt','structural_r','max_hold_hours','hold_feature','gross_target'):
           assert p[key]==t[key],(scenario,key,p[key],t[key])
          # No current-hour high/low/close/volume dependency in the live entry policy.
          altered={s:{**d,'trade':[b for b in d['trade'] if b.t<=t['entry_time']]} for s,d in cost_case(book,scenario).items()}
          causal,_=historical_entry_candidates(altered,signals,caps,t['entry_time'],t['equity_before_entry'],fee=fee,slip=slip)
          assert causal==candidates
         verified.append(dict(scenario=scenario,full_replay_exact=True,live_entries_exact=len(expected['trades']),net_return=actual['summary']['net_return']))

    @unittest.skipUnless(Path('state/research_runs/macro_risk_candidate_20261020/with_policy_parity.json').exists(),
                         'retained risk25 candidate inputs unavailable')
    def test_current_policy_matches_approved_twenty_five_percent_candidate(self):
        from qount.research.lines.macro_1atr import inputs
        from qount.strategies.macro_1atr import RISK_FRACTION
        self.assertEqual(RISK_FRACTION, .25)
        root=Path('state/research_cache')
        book,signals,_,caps,_=inputs(root/'binance_macro_attack_20261015',
            [root/p for p in ('binance_macro_prefix_20260407_20260611','binance_macro_earlier_20260611_20260730',
                             'binance_macro_attack_20261015')],
            root/'binance_macro_liquidity_20261015','2026-04-07','2026-10-15')
        venue=json.loads(Path('state/research_runs/macro_leverage_cash_review_20261019/venue_snapshot.json').read_text())
        for symbol,data in book.items():
            data['rule']=dict(data['rule'],leverage_brackets=venue['symbols'][symbol]['brackets'])
        saved=json.loads(Path('state/research_runs/macro_risk_candidate_20261020/with_policy_parity.json').read_text())
        for scenario in ('base','double_cost'):
            result=saved['results'][f'risk25_all_{scenario}']
            parameters=result['parameters']
            for trade in result['trades']:
                candidates,_=entry_candidates(cost_case(book,scenario),signals,caps,trade['entry_time'],
                    trade['equity_before_entry'],fee=parameters['fee'],slip=parameters['slip'])
                self.assertTrue(candidates)
                self.assertEqual(candidates[0]['symbol'],trade['symbol'])
                for field in ('quantity','entry_price','initial_stop','leverage','risk_budget_usdt',
                              'stress_risk_usdt','margin_usdt','structural_r','funding_cost_cap_usdt'):
                    self.assertEqual(candidates[0].get(field),trade.get(field),(scenario,field))
                truncated={s:dict(d,trade=[b for b in d['trade'] if b.t<=trade['entry_time']])
                           for s,d in cost_case(book,scenario).items()}
                causal,_=entry_candidates(truncated,signals,caps,trade['entry_time'],trade['equity_before_entry'],
                    fee=parameters['fee'],slip=parameters['slip'])
                self.assertEqual(candidates,causal)

