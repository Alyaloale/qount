"""Independent v3 receipt observation, incident dedupe and store isolation."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from qount.contracts import canonical_hash
from qount.notifications.contracts import AlertEvent
from qount.notifications.store import NotificationStore
from qount.operations.v3_notifications import CHANNEL, collect_v3_runtime
from qount.execution.g20_v3_live import STRATEGY_ID


class V3NotificationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.result, self.halt = self.root/'result.json', self.root/'HALT'
        self.store_path = self.root/'notifications'/'store.sqlite3'
        self.now = datetime(2026, 11, 4, 0, 1, tzinfo=timezone.utc)
        self.receipt()

    def receipt(self, action='RESIZE', blocker=None, **updates):
        data = dict(strategy_id=STRATEGY_ID, execution_mode='auto_live', orders_authorized=True,
                    created_at=self.now.isoformat(), auto_action=action, execution_blocker=blocker,
                    signal_date='2026-11-03', capital_usdt=43.87,
                    order_counts={'submitted': 11, 'skipped_rule': 0, 'planned_only': 0},
                    cycle_count=0, scheduled_resize=True)
        self.result.write_text(json.dumps({**data, **updates}))

    def observe(self, **kwargs):
        return collect_v3_runtime(self.result, self.halt, notification_store=self.store_path,
                                  now=self.now, **kwargs)

    def rows(self):
        return NotificationStore(self.store_path).verified_rows()

    def channel_jobs(self):
        return [job for job in self.rows()['jobs'] if job['channel'] == CHANNEL]

    def category_events(self):
        return [event for event in self.rows()['events'].values()]

    def test_healthy_cycle_enqueues_one_daily_summary(self):
        result = self.observe()
        self.assertEqual(result['state'], 'AUTO')
        self.assertEqual(result['notification_enqueue_status'], 'SUMMARY_RECORDED')
        events = self.category_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['severity'], 'INFO')
        self.assertEqual(events[0]['dedupe_key'], 'v3:summary:2026-11-03')
        self.assertIn('信号 2026-11-03', events[0]['summary'])
        self.assertEqual(len(self.channel_jobs()), 1)
        # A re-run of the same signal day does not duplicate the push.
        self.now += timedelta(minutes=6)
        self.observe()
        self.assertEqual(len(self.category_events()), 1)
        self.assertEqual(len(self.channel_jobs()), 1)

    def test_no_action_cycle_still_summarizes(self):
        self.receipt('NO_ACTION', order_counts=None)
        result = self.observe()
        self.assertEqual(result['state'], 'AUTO')
        self.assertEqual(result['notification_enqueue_status'], 'SUMMARY_RECORDED')
        self.assertIn('动作 NO_ACTION', self.category_events()[0]['summary'])

    def test_blocked_cycle_is_an_exception_alert_not_a_summary(self):
        self.receipt('BLOCKED', 'managed_position_quantity_mismatch')
        result = self.observe()
        self.assertEqual(result['state'], 'BLOCKED')
        self.assertEqual(result['reason'], 'managed_position_quantity_mismatch')
        self.assertEqual(result['notification_enqueue_status'], 'INCIDENT_RECORDED')
        events = self.category_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['severity'], 'CRITICAL')
        self.assertIn('managed_position_quantity_mismatch', events[0]['summary'])
        self.now += timedelta(minutes=5)
        self.observe()
        self.assertEqual(len(self.category_events()), 1)

    def test_warning_severity_for_non_critical_blocker(self):
        self.receipt('BLOCKED', 'klines_insufficient')
        self.observe()
        self.assertEqual(self.category_events()[0]['severity'], 'WARNING')

    def test_unsafe_blocker_text_is_not_copied(self):
        self.receipt('BLOCKED', 'https://signed.invalid/?secret=private')
        self.assertEqual(self.observe()['reason'], 'execution_blocked')
        self.assertNotIn('private', json.dumps(self.rows()))

    def test_halt_is_an_explicit_alert_once(self):
        self.halt.touch()
        result = self.observe()
        self.assertEqual(result['state'], 'HALTED')
        self.assertEqual(result['notification_enqueue_status'], 'HALT_RECORDED')
        events = self.category_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['severity'], 'HALT')
        self.now += timedelta(hours=1)
        self.observe()
        self.assertEqual(len(self.category_events()), 1)

    def test_healthy_day_resolves_yesterday_alerts(self):
        self.receipt('BLOCKED', 'klines_insufficient')
        self.observe()
        blocked_id = self.category_events()[0]['alert_id']
        self.now += timedelta(days=1)
        self.receipt(signal_date='2026-11-04')
        self.observe()
        states = self.rows()['states']
        self.assertEqual(states[blocked_id]['status'], 'RESOLVED')
        open_events = [e for e in self.category_events()
                       if self.rows()['states'][e['alert_id']]['status'] == 'OPEN']
        self.assertEqual(len(open_events), 1)
        self.assertEqual(open_events[0]['dedupe_key'], 'v3:summary:2026-11-04')

    def test_other_producers_are_left_alone(self):
        store = NotificationStore(self.store_path)
        other = AlertEvent.create(severity='WARNING', category='system_health', title='Other',
                                  summary='Other incident', occurred_at=self.now.isoformat(),
                                  source_type='system', source_id=canonical_hash('other'),
                                  source_hash=canonical_hash('other'), dedupe_key='other')
        store.enqueue(other, channels=('dashboard',), recorded_at=self.now.isoformat())
        self.observe()
        self.assertEqual(self.rows()['states'][other.alert_id]['status'], 'OPEN')

    def test_bad_receipt_is_unknown_and_never_escapes(self):
        self.result.write_text('not json')
        result = self.observe()
        self.assertEqual(result['state'], 'UNKNOWN')
        self.assertEqual(result['observation_error'], 'JSONDecodeError')
        self.assertEqual(result['notification_enqueue_status'], 'INCIDENT_RECORDED')
        self.assertEqual(self.category_events()[0]['severity'], 'WARNING')

    def test_notification_store_failure_is_diagnostic(self):
        self.store_path.parent.write_text('not a directory')
        result = self.observe()
        self.assertEqual(result['state'], 'AUTO')
        self.assertTrue(result['notification_enqueue_status'].startswith('ERROR:'))

    def test_wrong_identity_receipt_is_rejected(self):
        self.receipt(strategy_id='something_else')
        result = self.observe()
        self.assertEqual(result['state'], 'WAITING')
        self.assertEqual(result['notification_enqueue_status'], 'WAITING_SILENT')
        self.assertEqual(self.category_events(), [])

    def test_fresh_plan_only_receipt_waits_silently(self):
        self.receipt(execution_mode='plan_only')
        result = self.observe()
        self.assertEqual(result['state'], 'WAITING')
        self.assertEqual(result['notification_enqueue_status'], 'WAITING_SILENT')
        self.assertFalse(self.store_path.exists())

    def test_waiting_leaves_existing_alerts_untouched(self):
        self.receipt('BLOCKED', 'klines_insufficient')
        self.observe()
        blocked_id = self.category_events()[0]['alert_id']
        self.now += timedelta(hours=1)
        self.receipt('NO_ACTION', execution_mode='plan_only')
        result = self.observe()
        self.assertEqual(result['state'], 'WAITING')
        self.assertEqual(self.rows()['states'][blocked_id]['status'], 'OPEN')

    def test_stale_live_receipt_is_an_alert(self):
        self.receipt(created_at=(self.now - timedelta(hours=31)).isoformat())
        result = self.observe()
        self.assertEqual(result['state'], 'STALE')
        self.assertEqual(result['reason'], 'auto_receipt_stale')
        self.assertEqual(result['notification_enqueue_status'], 'INCIDENT_RECORDED')
        events = self.category_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['severity'], 'WARNING')
        # The watchdog re-observing does not duplicate the alert.
        self.now += timedelta(hours=1)
        self.observe()
        self.assertEqual(len(self.category_events()), 1)

    def test_stale_non_live_receipt_alerts_first_cycle_missing(self):
        self.receipt(execution_mode='plan_only',
                     created_at=(self.now - timedelta(hours=31)).isoformat())
        result = self.observe()
        self.assertEqual(result['state'], 'STALE')
        self.assertEqual(result['reason'], 'auto_receipt_stale_or_non_live')
        self.assertEqual(result['notification_enqueue_status'], 'INCIDENT_RECORDED')

    def test_missing_receipt_file_is_an_alert(self):
        self.result.unlink()
        result = self.observe()
        self.assertEqual(result['state'], 'UNKNOWN')
        self.assertEqual(result['observation_error'], 'ValueError')
        self.assertEqual(result['notification_enqueue_status'], 'INCIDENT_RECORDED')

    def test_halt_suppresses_stale_alerts(self):
        self.halt.touch()
        self.receipt(created_at=(self.now - timedelta(hours=31)).isoformat())
        result = self.observe()
        self.assertEqual(result['state'], 'HALTED')
        self.assertEqual(result['notification_enqueue_status'], 'HALT_RECORDED')


if __name__ == '__main__':
    unittest.main()
