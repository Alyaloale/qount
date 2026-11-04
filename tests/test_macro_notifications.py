"""Independent local observation; the macro alert path is retired (2026-11-04)."""
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from qount.operations.macro_notifications import collect_macro_runtime, UNITS
from qount.strategies.macro_1atr import STRATEGY_ID


class MacroNotificationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.result, self.halt = self.root/'result.json', self.root/'HALT'
        self.store_path = self.root/'notifications'/'store.sqlite3'
        self.now = datetime(2026, 10, 17, 14, 5, tzinfo=timezone.utc)
        self.timer_active = True
        self.receipt()

    def receipt(self, action='WAIT_NY_1000', blocker=None, **updates):
        data = dict(strategy_id=STRATEGY_ID, execution_mode='auto_live', orders_authorized=True,
                    created_at=self.now.isoformat(), auto_action=action, execution_blocker=blocker)
        self.result.write_text(json.dumps({**data, **updates}))

    def systemd(self, command, **kwargs):
        self.assertEqual(command[2:5], list(UNITS))
        blocks = []
        for unit in UNITS:
            active = 'active' if unit.endswith('.timer') and self.timer_active else 'inactive'
            blocks.append(f'ActiveState={active}\nResult=success\nId={unit}\nSubState=waiting\nUnitFileState=enabled')
        return subprocess.CompletedProcess(command, 0, '\n\n'.join(blocks), '')

    def observe(self, **kwargs):
        return collect_macro_runtime(self.result, self.halt,
                                     now=self.now, runner=self.systemd, **kwargs)

    def test_oneshot_inactive_success_is_healthy_and_observation_only(self):
        result = self.observe()
        self.assertEqual(result['state'], 'AUTO')
        self.assertEqual(result['notification_enqueue_status'], 'RETIRED')
        self.assertEqual(result['notification_delivery']['status'], 'RETIRED')
        self.assertFalse(self.store_path.exists())

    def test_alerting_states_never_enqueue_or_resolve_events(self):
        for action, blocker in (('BLOCKED', 'managed_position_quantity_mismatch'),
                                ('BLOCKED', 'https://signed.invalid/?secret=private')):
            with self.subTest(action=action, blocker=blocker):
                self.receipt(action, blocker)
                self.now += timedelta(minutes=5)
                result = self.observe()
                self.assertEqual(result['state'], 'BLOCKED')
                self.assertEqual(result['notification_enqueue_status'], 'RETIRED')
                self.assertFalse(self.store_path.exists())
        self.assertNotIn('private', json.dumps(self.observe()))

    def test_inactive_timer_is_detected_even_with_a_fresh_successful_receipt(self):
        self.timer_active = False
        result = self.observe()
        self.assertEqual(result['state'], 'DISABLED')
        self.assertEqual(result['reason'], 'auto_timer_not_active')
        self.assertEqual(result['notification_enqueue_status'], 'RETIRED')
        self.assertFalse(self.store_path.exists())

    def test_missed_period_and_future_receipt_are_not_healthy(self):
        for seconds in (-3901, 61):
            with self.subTest(seconds=seconds):
                self.receipt(created_at=(self.now+timedelta(seconds=seconds)).isoformat())
                self.assertEqual(self.observe()['state'], 'STALE')

    def test_halt_is_explicit_and_does_not_send(self):
        self.halt.touch()
        result = self.observe()
        self.assertEqual(result['state'], 'HALTED')
        self.assertEqual(result['notification_enqueue_status'], 'RETIRED')
        self.assertFalse(self.store_path.exists())

    def test_bad_receipt_and_probe_failures_are_unknown_and_do_not_escape(self):
        self.result.write_text('not json')
        self.assertEqual(self.observe()['state'], 'UNKNOWN')
        def failed(*args, **kwargs):
            raise subprocess.TimeoutExpired('systemctl', 3)
        result = collect_macro_runtime(self.result, self.halt, now=self.now, runner=failed)
        self.assertEqual(result['state'], 'UNKNOWN')
        self.assertEqual(result['observation_error'], 'TimeoutExpired')

    def test_api_reads_runtime_from_existing_assets_and_marks_old_observations_stale(self):
        from qount.api.routes.account import get_one_atr_status
        assets = self.root/'assets.json'
        runtime = self.observe()
        for minutes, stale in ((0, False), (-16, True)):
            runtime['observed_at'] = (datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat()
            assets.write_text(json.dumps(dict(read_only=True, strategy_runtime=runtime)))
            with patch.dict(os.environ, {'QOUNT_1ATR_RESULT_PATH':str(self.result),
                                         'QOUNT_ACCOUNT_ASSETS_PATH':str(assets)}):
                result = get_one_atr_status()
            self.assertEqual(result['runtime']['state'], 'AUTO')
            self.assertEqual(result['runtime']['stale'], stale)

    def test_runner_keeps_last_formal_decision_across_normal_wait_cycles(self):
        from scripts.operations.run_macro_1atr import run_cycle
        decision = dict(auto_action='HOLD_NO_SIGNAL', candidate_count=0,
                        rejections={'friction_budget':1}, capital_usdt=15.0)
        with patch('scripts.operations.run_macro_1atr.MacroLive') as live:
            live.return_value.cycle.return_value = decision
            args = dict(output=self.result, store_path=self.root/'unused.db', halt_path=self.halt,
                        now=int(self.now.timestamp()))
            first = run_cycle(None, **args)
            live.return_value.cycle.return_value = dict(auto_action='WAIT_NY_1000')
            args['now'] += 3600
            second = run_cycle(None, **args)
        self.assertEqual(second['last_decision'], first['last_decision'])
        self.assertEqual(first['risk_fraction'], .25)
        self.assertEqual(second['risk_fraction'], .25)
        self.assertEqual(second['last_decision']['rejections'], {'friction_budget':1})
        self.assertNotEqual(second['created_at'], second['last_decision']['created_at'])

    def test_runner_records_safe_public_input_reason_without_serializing_other_errors(self):
        from scripts.operations.run_macro_1atr import run_cycle
        from qount.research_data.macro_live import MacroInputError
        args=dict(output=self.result,store_path=self.root/'unused.db',halt_path=self.halt,
                  now=int(self.now.timestamp()))
        with patch('scripts.operations.run_macro_1atr.MacroLive') as live:
            live.return_value.cycle.side_effect=MacroInputError('proxy_invalid_prices',ticker='SPY',date='2026-10-21')
            result=run_cycle(None,**args)
            self.assertEqual(result['execution_blocker'],'input_unavailable:proxy_invalid_prices')
            self.assertEqual(result['input_error'],dict(code='proxy_invalid_prices',ticker='SPY',date='2026-10-21'))
            live.return_value.cycle.side_effect=ValueError('https://signed.invalid/?secret=private')
            result=run_cycle(None,**args)
            self.assertEqual(result['execution_blocker'],'input_or_exchange_error:ValueError')
            self.assertNotIn('private',json.dumps(result));self.assertNotIn('input_error',result)


if __name__ == '__main__':
    unittest.main()
