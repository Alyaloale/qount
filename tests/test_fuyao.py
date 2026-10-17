from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from qount.config_contract import check_environment
from qount.local_credentials import load_local_credential
from qount.research.q_div_acquisition import saved_token
from qount.research_data.fuyao import FuyaoClient, FuyaoError, _NoRedirect, date_ms, prepare_params, probe


TEST_KEY = 'test-only-fuyao-secret'


def envelope(rows=None, **data):
    return {'code': 0, 'message': 'success', 'data': {'item': [] if rows is None else rows, **data}}


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'credential.env'
        self.path.write_text('FUYAO_API_KEY=' + TEST_KEY + '\n')
        self.path.chmod(0o600)
        self.platform = patch('qount.local_credentials.sys.platform', 'darwin')
        self.platform.start()
        self.addCleanup(self.platform.stop)

    def test_private_file_read_and_tushare_uses_same_reader(self):
        self.assertEqual(load_local_credential('fuyao', path=self.path), TEST_KEY)
        self.path.write_text('TUSHARE_TOKEN=example123\n')
        self.assertEqual(saved_token(self.path), 'example123')

    def test_non_private_file_refused_without_value(self):
        self.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'owned_regular_0600') as caught:
            load_local_credential('fuyao', path=self.path)
        self.assertNotIn(TEST_KEY, str(caught.exception))

    def test_symlink_refused(self):
        link = self.path.with_name('link.env')
        link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            load_local_credential('fuyao', path=link)

    def test_credential_read_only_on_mac(self):
        with patch('qount.local_credentials.sys.platform', 'linux'):
            with self.assertRaisesRegex(ValueError, 'Mac_only'):
                load_local_credential('fuyao', path=self.path)

    def test_multiple_assignments_not_evaluated_or_exported(self):
        before = dict(os.environ)
        self.path.write_text('FUYAO_API_KEY=' + TEST_KEY + '\nOTHER=$(never-run)\n')
        with self.assertRaisesRegex(ValueError, 'credential_format'):
            load_local_credential('fuyao', path=self.path)
        self.assertEqual(dict(os.environ), before)

    def test_contract_redacts_value_and_enforces_host(self):
        mac = check_environment(profile='mac', env_file=self.path)
        self.assertTrue(mac['ok'])
        self.assertNotIn(TEST_KEY, json.dumps(mac))
        wsl = check_environment(profile='wsl', environ={'FUYAO_API_KEY': TEST_KEY})
        self.assertEqual(wsl['host_not_allowed'], ['FUYAO_API_KEY'])


class FuyaoTests(unittest.TestCase):
    def setUp(self):
        self.loader = patch('qount.research_data.fuyao.load_local_credential', return_value=TEST_KEY)
        self.loader.start()
        self.addCleanup(self.loader.stop)
        self.client = FuyaoClient(minimum_spacing=0)

    def respond(self, value):
        response = io.BytesIO(value if isinstance(value, bytes) else json.dumps(value).encode())
        response.status = 200
        return patch.object(self.client._opener, 'open', return_value=response)

    def test_auth_only_in_header_and_missing_values_preserved(self):
        with self.respond(envelope([{'thscode': '600519.SH', 'pe_ttm': None}])) as opened:
            result = self.client.query('valuations', thscodes='600519.SH')
        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.get_header('X-api-key'), TEST_KEY)
        self.assertNotIn(TEST_KEY, request.full_url)
        self.assertNotIn(TEST_KEY, json.dumps(result))
        self.assertIsNone(result['response']['data']['item'][0]['pe_ttm'])
        self.assertFalse(result['semantics']['point_in_time_verified'])
        self.assertFalse(result['orders_authorized'])

    def test_provider_error_at_http_200_is_failure_without_echo(self):
        with self.respond({'code': 2003, 'message': TEST_KEY, 'data': None}):
            with self.assertRaisesRegex(FuyaoError, 'credential_in_response'):
                self.client.query('calendar')
        with self.respond({'code': 2003, 'message': 'not authorized', 'data': None}):
            with self.assertRaisesRegex(FuyaoError, 'provider_code_2003'):
                self.client.query('calendar')

    def test_literal_and_json_escaped_secret_cannot_be_exported(self):
        raw = json.dumps(envelope([{'name': TEST_KEY}]))
        escaped = raw.replace(TEST_KEY, ''.join('\\u%04x' % ord(c) for c in TEST_KEY))
        for content in (raw.encode(), escaped.encode()):
            with self.subTest(content_length=len(content)), self.respond(content):
                with self.assertRaisesRegex(FuyaoError, 'credential_in_response') as caught:
                    self.client.query('calendar')
                self.assertNotIn(TEST_KEY, str(caught.exception))

    def test_http_429_and_business_rate_limit_never_retry(self):
        error = urllib.error.HTTPError('https://fuyao.aicubes.cn', 429, TEST_KEY, {}, io.BytesIO())
        with patch.object(self.client._opener, 'open', side_effect=error) as opened:
            with self.assertRaisesRegex(FuyaoError, 'rate_limited'):
                self.client.query('calendar')
            self.assertEqual(opened.call_count, 1)
        with self.respond({'code': 4001, 'data': None}) as opened:
            with self.assertRaisesRegex(FuyaoError, 'rate_limited'):
                self.client.query('calendar')
            self.assertEqual(opened.call_count, 1)

    def test_redirect_to_another_host_is_refused(self):
        with self.assertRaisesRegex(FuyaoError, 'redirect_refused'):
            _NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid')

    def test_transport_error_does_not_expose_request_details(self):
        with patch.object(self.client._opener, 'open', side_effect=urllib.error.URLError(TEST_KEY)):
            with self.assertRaisesRegex(FuyaoError, 'network_error') as caught:
                self.client.query('calendar')
            self.assertNotIn(TEST_KEY, str(caught.exception))

    def test_request_budget_stops_before_network(self):
        self.client._max_requests = 0
        with patch.object(self.client._opener, 'open') as opened:
            with self.assertRaisesRegex(FuyaoError, 'budget_exhausted'):
                self.client.query('calendar')
            opened.assert_not_called()

    def test_malformed_and_non_json_success_fail(self):
        for content in (b'not json', {'code': 0, 'data': None}, {'code': 0, 'data': {'item': {}}}):
            with self.subTest(content=content), self.respond(content):
                with self.assertRaises(FuyaoError):
                    self.client.query('calendar')

    def test_history_defaults_to_unadjusted_and_checks_dates(self):
        day = date_ms('2026-09-30')
        row = dict(date_ms=day, open_price=1, high_price=2, low_price=1, close_price=2, volume=0, turnover=None)
        with self.respond(envelope([row])):
            result = self.client.query('historical', thscode='600519.sh', start='2026-09-30', end='2026-09-30')
        self.assertEqual(result['params']['adjust'], 'none')
        self.assertEqual(result['params']['thscode'], '600519.SH')
        for rows in ([row, row], [{**row, 'date_ms': day - 1}], [{'date_ms': day}]):
            with self.subTest(rows=rows), self.respond(envelope(rows)):
                with self.assertRaises(FuyaoError):
                    self.client.query('historical', thscode='600519.SH', start='2026-09-30', end='2026-09-30')

    def test_wrong_identity_rejected_and_constituent_identity_allowed(self):
        with self.respond(envelope([{'thscode': '000001.SZ'}])):
            with self.assertRaisesRegex(FuyaoError, 'identity'):
                self.client.query('fund_snapshot', thscode='510300.SH')
        with self.respond(envelope([{'thscode': '600519.SH'}])):
            record = self.client.query('constituents', thscode='000300.SH')
            self.assertIn('current_snapshot', record['semantics']['history_scope'])

    def test_shanghai_date_conversion_and_inclusive_end(self):
        self.assertEqual(date_ms('1970-01-01'), -28_800_000)
        self.assertEqual(date_ms('2026-10-01', end_of_day=True) - date_ms('2026-10-01'), 86_399_999)

    def test_bad_parameters_conflicts_and_history_windows_rejected(self):
        for capability, params in [
            ('calendar', {'url': 'https://other.invalid'}),
            ('historical', {'thscode': '600519', 'start': '2025-01-01', 'end': '2026-01-01'}),
            ('historical', {'thscode': '600519.SH', 'start': '2026-01-01'}),
            ('historical', {'thscode': '600519.SH', 'start': '2010-01-01', 'end': '2026-01-01'}),
            ('income', {'thscode': '600519.SH', 'start': '2025-01-01', 'end': '2026-01-01', 'limit': 1}),
        ]:
            with self.subTest(capability=capability, params=params):
                with self.assertRaises(FuyaoError):
                    prepare_params(capability, params)

    def test_single_page_explicit_and_empty_data_not_fabricated(self):
        with self.respond(envelope([])):
            record = self.client.query('tickers', asset_type='a-share', limit=2)
        self.assertIn('one_page_only', record['semantics']['pagination_scope'])
        self.assertEqual(record['response']['data']['item'], [])

    def test_probe_stops_at_authentication_failure(self):
        with self.respond({'code': 2001, 'data': None}) as opened:
            report = probe(self.client)
        self.assertFalse(report['ok'])
        self.assertEqual(len(report['checks']), 1)
        self.assertEqual(opened.call_count, 1)


if __name__ == '__main__':
    unittest.main()
