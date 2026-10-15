"""Key causal, risk, accounting and deterministic-paper regressions."""
import json
import unittest
from pathlib import Path

from qount.research.binance_micro_breakout import PaperEngine, UnitLedger, common_step, features, size
from qount.research.small_account_breakout import Bar


class MicroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = json.loads(Path('config/binance-micro-regime-breakout-v01.json').read_text())
        cls.rules = {r['symbol']:r for r in json.loads(Path('state/research_runs/binance_micro_design_20261013/public-feasibility.json').read_text())['symbols']}

    def engine(self, gated=False):
        rows = [{'fundingTime':t*1000,'fundingRate':'0.00001','markPrice':'100'} for t in (-86400,-57600,-28800)]
        return PaperEngine(self.cfg,self.rules,{s:rows for s in self.cfg['universe']},gated=gated)

    def bars(self,t,price=100,low=100):
        return {s:Bar(t,price,max(100,price),low,price,1000) for s in self.cfg['universe']}

    def test_transfer_preserves_drawdown(self):
        l = UnitLedger(9,10)
        l.transfer(10)
        self.assertAlmostEqual(l.nav,0.9)
        self.assertEqual(l.peak_nav,1)
        self.assertAlmostEqual(l.deposits,10)
        l.transfer(-5)
        self.assertAlmostEqual(l.nav,0.9)

    def test_common_decimal_grid(self):
        self.assertEqual(str(common_step([{'stepSize':'0.002'},{'stepSize':'0.003'}])),'0.006')

    def test_risk_and_minimum_no_inflation(self):
        for volatility in (1,2,4):
            contract,reason = size(self.cfg,self.rules['SOLUSDT'],107.17,107.17,volatility,10,0.3,0.0006,.0005,.0005,100)
            if contract:
                self.assertLessEqual(contract['stress_risk_usdt'],.3)
                self.assertLessEqual(contract['notional_usdt'],20)
                self.assertLessEqual(contract['margin_usdt'],4)
            else:
                self.assertEqual(reason,'minimum_order')
        contract,reason = size(self.cfg,self.rules['BTCUSDT'],83448,83448,1000,10,.3,.0006,.0005,.0005,100)
        self.assertIsNone(contract)
        self.assertEqual(reason,'minimum_order')

    def test_entry_strictly_after_signal_and_restart(self):
        e = self.engine()
        bars = self.bars(0)
        update = {'SOLUSDT':{'close':100,'atr':2,'breakout':True}}
        e.step(0,bars,bars,self.bars(-60),update)
        self.assertIsNone(e.pos)
        restarted = self.engine()
        restarted.restore(json.loads(json.dumps(e.snapshot())))
        for engine in (e,restarted):
            engine.step(60,self.bars(60),self.bars(60),bars)
        self.assertEqual(e.snapshot(),restarted.snapshot())
        self.assertEqual(e.pos['entry_time'],60)
        self.assertEqual(e.pos['decision_time'],0)

    def test_funding_forecast_cannot_read_future(self):
        e = self.engine()
        before = e.reserve('SOLUSDT',0,72)
        e.funding['SOLUSDT'].append({'fundingTime':60000,'fundingRate':'9','markPrice':'100'})
        self.assertEqual(e.reserve('SOLUSDT',0,72),before)

    def test_unknown_gate_blocks_and_risk_off_flattens(self):
        e = self.engine(True)
        update = {'SOLUSDT':{'close':100,'atr':2,'breakout':True}}
        e.step(0,self.bars(0),self.bars(0),self.bars(-60),update)
        e.step(60,self.bars(60),self.bars(60),self.bars(0))
        self.assertIsNone(e.pos)
        self.assertEqual(e.rejections['regime_off_or_unknown'],1)
        e.step(120,self.bars(120),self.bars(120),self.bars(60),update,True)
        e.step(180,self.bars(180),self.bars(180),self.bars(120))
        self.assertIsNotNone(e.pos)
        e.step(240,self.bars(240),self.bars(240),self.bars(180),gate=False)
        self.assertIsNotNone(e.pos)
        e.step(300,self.bars(300),self.bars(300),self.bars(240))
        self.assertEqual(e.trades[-1]['exit_reason'],'regime_off')

    def test_stop_before_ordinary_exit_and_gap(self):
        e = self.engine()
        e.fill_gap = .01
        e.step(0,self.bars(0),self.bars(0),self.bars(-60),{'SOLUSDT':{'close':100,'atr':2,'breakout':True}})
        e.step(60,self.bars(60),self.bars(60),self.bars(0))
        e.exit_pending = (120,'regime_off')
        e.step(120,self.bars(120,96,96),self.bars(120,96,96),self.bars(60))
        t = e.trades[0]
        self.assertEqual(t['exit_reason'],'stop')
        self.assertLess(t['exit_price'],96)
        self.assertAlmostEqual(t['net_pnl_usdt'],t['quantity']*(t['exit_price']-t['entry_price'])-t['fees_usdt']+t['funding_net_usdt'])

    def test_completed_feature_uses_prior_channel(self):
        rows = [Bar(t*3600,100,101,99,100) for t in range(101)]
        rows[99] = Bar(99*3600,100,110,99,105)
        u,_ = features({'SOLUSDT':rows},[],3600)
        self.assertTrue(u[100*3600]['SOLUSDT']['breakout'])
        self.assertNotIn(99*3600,u)
        changed = rows+[Bar(101*3600,100,10000,1,9999)]
        v,_ = features({'SOLUSDT':changed},[],3600)
        self.assertEqual(u[100*3600],v[100*3600])

    def test_halt_and_downshift_latched(self):
        e = self.engine()
        e.ledger.equity = 7.9
        e.step(0,self.bars(0),self.bars(0),self.bars(-60))
        self.assertEqual(e.halt,'nav_drawdown')
        self.assertTrue(e.downshift)
        e.transfer(10)
        e.step(60,self.bars(60),self.bars(60),self.bars(0))
        self.assertEqual(e.halt,'nav_drawdown')
        self.assertTrue(e.downshift)

    def test_rolling_loss_is_invariant_to_cash_flows(self):
        def run(amount, loss):
            e = self.engine()
            e.step(0, self.bars(0), self.bars(0), self.bars(-60))
            e.transfer(amount)
            e.ledger.equity += loss
            e.step(60, self.bars(60), self.bars(60), self.bars(0))
            return e

        # A withdrawal must not look like a trading loss.
        withdrawn = run(-5, 0)
        self.assertIsNone(withdrawn.halt)
        self.assertAlmostEqual(withdrawn.ledger.nav, 1.0)
        # After a deposit, the same 7% NAV loss still breaches the 6% limit.
        deposited = run(10, -1.4)
        self.assertEqual(deposited.halt, 'rolling_loss')
        self.assertAlmostEqual(deposited.ledger.nav, 0.93)

    def test_cashflow_adjusts_remaining_risk_budget_and_resume(self):
        e = self.engine()
        e.step(0, self.bars(0), self.bars(0), self.bars(-60))
        # Unit NAV 0.95 leaves just one percentage point above the rolling
        # floor. New equity is 19; remaining stress budget must be 0.20 USDT.
        e.ledger.equity = 9.5
        e.step(60, self.bars(60), self.bars(60), self.bars(0), cashflow_usdt=9.5)
        restored = self.engine()
        restored.restore(json.loads(json.dumps(e.snapshot())))
        update = {'SOLUSDT': {'close': 100, 'atr': 1, 'breakout': True}}
        for engine in (e, restored):
            engine.step(120, self.bars(120), self.bars(120), self.bars(60), update)
            engine.step(180, self.bars(180), self.bars(180), self.bars(120))
            self.assertAlmostEqual(engine.pos['risk_budget_usdt'], 0.2)
            self.assertEqual(engine.journal[0]['type'], 'CASHFLOW')
        self.assertEqual(e.snapshot(), restored.snapshot())
        with self.assertRaisesRegex(ValueError, 'flat_reconciled'):
            e.transfer(1)

    def test_legacy_checkpoint_history_migration(self):
        e = self.engine()
        e.step(0, self.bars(0), self.bars(0), self.bars(-60))
        state = json.loads(json.dumps(e.snapshot()))
        state.pop('history_basis')
        state['history'] = [[0, 10.0]]
        restored = self.engine()
        restored.restore(state)
        self.assertEqual(list(restored.history), [(0, 1.0)])
        restored.step(60, self.bars(60), self.bars(60), self.bars(0))
        self.assertIsNone(restored.halt)
        state['ledger']['deposits'] = 1
        with self.assertRaisesRegex(ValueError, 'requires_replay'):
            restored.restore(state)

    def test_daily_gate_only_at_completed_close(self):
        daily = [Bar(i*86400,100,102,99,100) for i in range(201)]
        daily[199] = Bar(199*86400,100,202,99,200)
        _,gates = features({},daily,3600)
        self.assertNotIn(199*86400,gates)
        self.assertTrue(gates[200*86400])
        daily[200] = Bar(200*86400,100,100,1,2)
        _,changed = features({},daily,3600)
        self.assertEqual(gates[200*86400],changed[200*86400])

    def test_missing_minute_fails_closed(self):
        e = self.engine()
        with self.assertRaisesRegex(ValueError,'missing_minute'):
            e.step(0,{},self.bars(0),{})
        self.assertIsNone(e.pos)


if __name__ == '__main__': unittest.main()
