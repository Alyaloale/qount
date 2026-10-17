"""Read-only Fuyao/THS research data, using the central Mac credential store."""
from __future__ import annotations

import datetime as dt
import http.client
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from qount.local_credentials import load_local_credential

BASE_URL = 'https://fuyao.aicubes.cn'
SHANGHAI = ZoneInfo('Asia/Shanghai')
# A named capability cannot redirect an authenticated request to another host.
CAPABILITIES = {
    'calendar': ('/api/a-share/calendar/trading-days', ''),
    'search': ('/api/meta/tickers/search', 'q,exchange,asset_type,limit'),
    'tickers': ('/api/meta/tickers/list', 'asset_type,limit,offset'),
    'snapshot': ('/api/a-share/prices/snapshot', 'thscodes,limit,offset'),
    'historical': ('/api/a-share/prices/historical', 'thscode,interval,start,end,adjust'),
    'income': ('/api/a-share/financials/income-statements', 'thscode,period,limit,start,end'),
    'balance': ('/api/a-share/financials/balance-sheets', 'thscode,period,limit,start,end'),
    'cashflow': ('/api/a-share/financials/cash-flow-statements', 'thscode,period,limit,start,end'),
    'actions': ('/api/a-share/corporate-actions/adjustment-factors', 'thscode,from,to'),
    'valuations': ('/api/a-share/valuations/snapshot', 'thscodes'),
    'constituents': ('/api/a-share-index/constituents/ths-stock-list', 'thscode'),
    'index_catalog': ('/api/a-share-index/catalog/ths-index-list', 'tag'),
    'index_snapshot': ('/api/a-share-index/prices/snapshot', 'thscodes'),
    'index_historical': ('/api/a-share-index/prices/historical', 'thscode,interval,start,end'),
    'fund_snapshot': ('/api/fund/market/snapshot', 'thscode'),
    'fund_historical': ('/api/fund/market/historical', 'thscode,interval,start,end'),
}


class FuyaoError(ValueError):
    """Value-free error: never include provider messages or request headers."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FuyaoError('fuyao_credential_redirect_refused')


def date_ms(value, *, end_of_day=False):
    """Convert an ISO date to Shanghai midnight, or the inclusive end of day."""
    if isinstance(value, str) and len(value) == 10 and value[4] == '-' and value[7] == '-':
        day = dt.date.fromisoformat(value)
        result = int(dt.datetime.combine(day, dt.time(), SHANGHAI).timestamp() * 1000)
        return result + (86_400_000 - 1 if end_of_day else 0)
    if isinstance(value, bool):
        raise FuyaoError('fuyao_invalid_timestamp')
    result = int(value)
    if result < 0 or (not isinstance(value, str) and result != value):
        raise FuyaoError('fuyao_invalid_timestamp')
    return result


def prepare_params(capability, params):
    if capability not in CAPABILITIES:
        raise FuyaoError('fuyao_unknown_capability')
    allowed = set(CAPABILITIES[capability][1].split(',')) - {''}
    if set(params) - allowed:
        raise FuyaoError('fuyao_unknown_parameter')
    result = {key: value for key, value in params.items() if value is not None}
    for key, value in result.items():
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise FuyaoError('fuyao_invalid_parameter')
    if 'thscode' in result:
        result['thscode'] = str(result['thscode']).strip().upper()
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ|TI)', result['thscode']):
            raise FuyaoError('fuyao_single_full_thscode_required')
    if 'thscodes' in result:
        symbols = [symbol.strip().upper() for symbol in str(result['thscodes']).split(',')]
        if any(not re.fullmatch(r'\d{6}\.(SH|SZ|BJ|TI)', symbol) for symbol in symbols):
            raise FuyaoError('fuyao_full_thscodes_required')
        if capability == 'valuations' and len(symbols) > 100:
            raise FuyaoError('fuyao_valuation_symbol_limit')
        result['thscodes'] = ','.join(dict.fromkeys(symbols))
    for key in ('start', 'end'):
        if key in result:
            result[key] = date_ms(result[key], end_of_day=key == 'end')
    if ('start' in result) != ('end' in result):
        raise FuyaoError('fuyao_date_range_requires_both_ends')
    if 'start' in result:
        start, end = result['start'], result['end']
        years = 5 if capability in ('fund_historical', 'index_historical') else 10
        start_day = dt.datetime.fromtimestamp(start / 1000, SHANGHAI).date()
        # Allow leap-day starts; the provider remains the authority on its exact window cap.
        try:
            latest_day = start_day.replace(year=start_day.year + years)
        except ValueError:
            latest_day = start_day.replace(year=start_day.year + years, day=28)
        if end < start or dt.datetime.fromtimestamp(end / 1000, SHANGHAI).date() > latest_day:
            raise FuyaoError('fuyao_date_range_out_of_bounds')
    if capability in ('historical', 'fund_historical', 'index_historical'):
        if not all(key in result for key in ('thscode', 'start', 'end')):
            raise FuyaoError('fuyao_history_requires_symbol_and_range')
        result.setdefault('interval', '1d')
        if result['interval'] != '1d':
            raise FuyaoError('fuyao_only_daily_history_supported')
    if capability == 'historical':
        result.setdefault('adjust', 'none')
        if result['adjust'] not in ('none', 'forward', 'backward'):
            raise FuyaoError('fuyao_invalid_adjustment')
    if capability in ('income', 'balance', 'cashflow'):
        if 'limit' in result and 'start' in result:
            raise FuyaoError('fuyao_financial_limit_range_conflict')
        result.setdefault('period', 'annual')
        if result['period'] not in ('annual', 'quarterly'):
            raise FuyaoError('fuyao_invalid_financial_period')
    return result


def _validate_data(capability, params, data):
    if not isinstance(data, dict) or not isinstance(data.get('item'), list):
        raise FuyaoError('fuyao_response_schema')
    rows = data['item']
    if any(not isinstance(row, dict) for row in rows):
        raise FuyaoError('fuyao_response_item_schema')
    symbol = params.get('thscode')
    # Constituents contain member identities rather than the index identity.
    if symbol and capability != 'constituents':
        if data.get('thscode', symbol) != symbol:
            raise FuyaoError('fuyao_response_identity')
        if any(row.get('thscode', symbol) != symbol for row in rows):
            raise FuyaoError('fuyao_response_identity')
    if capability in ('historical', 'fund_historical', 'index_historical'):
        dates = [row.get('date_ms') for row in rows]
        if any(type(day) is not int or not params['start'] <= day <= params['end'] for day in dates):
            raise FuyaoError('fuyao_history_outside_requested_range')
        if len(set(dates)) != len(dates):
            raise FuyaoError('fuyao_history_duplicate_date')
        for row in rows:
            if not {'open_price', 'high_price', 'low_price', 'close_price', 'volume', 'turnover'} <= row.keys():
                raise FuyaoError('fuyao_history_missing_fields')
            for key in ('open_price', 'high_price', 'low_price', 'close_price', 'volume', 'turnover'):
                value = row.get(key)
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                    raise FuyaoError('fuyao_history_invalid_number')
    if capability in ('income', 'balance', 'cashflow'):
        required = {'thscode', 'period_end_ms', 'report_date_ms', 'currency'}
        if any(not required <= row.keys() for row in rows):
            raise FuyaoError('fuyao_financial_missing_metadata')


def _semantics(capability, params):
    result = {'point_in_time_verified': False, 'missing_values': 'preserved_as_null'}
    if capability == 'historical':
        result['price_adjustment'] = params['adjust']
    if capability == 'fund_historical':
        result['price_adjustment'] = 'forward_vendor_defined'
    if capability in ('search', 'snapshot', 'valuations', 'constituents', 'tickers', 'index_catalog', 'index_snapshot', 'fund_snapshot'):
        result['history_scope'] = 'current_snapshot_not_historical_membership_or_valuation'
    if capability in ('income', 'balance', 'cashflow'):
        result['availability'] = 'report_date_ms_is_disclosure_date_not_verified_intraday_publication_time'
        result['timestamp_meaning'] = 'latest_period_end_not_fetch_or_publication_time'
    if capability == 'calendar':
        result['history_scope'] = 'rolling_one_year_not_full_historical_calendar'
    if capability == 'actions':
        result['event_scope'] = 'ex_date_cash_and_bonus_not_payment_dates_or_total_return'
    return result


class FuyaoClient:
    """Serial HTTPS queries, no retries, fixed host, bounded response/request sizes."""
    def __init__(self, *, credential_path=None, timeout=30, minimum_spacing=1.0, max_requests=20):
        self._key = load_local_credential('fuyao', path=credential_path)
        self._opener = urllib.request.build_opener(_NoRedirect())
        self._timeout = timeout
        self._minimum_spacing = minimum_spacing
        self._max_requests = max_requests
        self._requests = 0
        self._last = None

    def query(self, capability, **params):
        params = prepare_params(capability, params)
        endpoint = CAPABILITIES[capability][0]
        query = urllib.parse.urlencode(params)
        if self._key in query or self._key in str(params):
            raise FuyaoError('fuyao_credential_in_query_refused')
        if self._requests >= self._max_requests:
            raise FuyaoError('fuyao_request_budget_exhausted')
        if self._last is not None:
            time.sleep(max(0, self._minimum_spacing - (time.monotonic() - self._last)))
        self._last = time.monotonic()
        self._requests += 1
        request = urllib.request.Request(BASE_URL + endpoint + ('?' + query if query else ''),
            headers={'X-api-key': self._key, 'Accept': 'application/json', 'User-Agent': 'qount-research/1'}, method='GET')
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200:
                    raise FuyaoError('fuyao_http_status_' + str(response.status))
                raw = response.read(16 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise FuyaoError('fuyao_rate_limited' if status == 429 else 'fuyao_http_status_' + str(status)) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise FuyaoError('fuyao_network_error') from None
        if len(raw) > 16 * 1024 * 1024:
            raise FuyaoError('fuyao_response_size_limit')
        if self._key.encode() in raw:
            raise FuyaoError('fuyao_credential_in_response_refused')
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise FuyaoError('fuyao_invalid_json') from None
        if self._key in json.dumps(value, ensure_ascii=False):
            raise FuyaoError('fuyao_credential_in_response_refused')
        if not isinstance(value, dict) or type(value.get('code')) is not int:
            raise FuyaoError('fuyao_response_envelope_schema')
        if value['code'] != 0:
            raise FuyaoError('fuyao_rate_limited' if value['code'] == 4001 else 'fuyao_provider_code_' + str(value['code']))
        _validate_data(capability, params, value.get('data'))
        semantics = _semantics(capability, params)
        if capability == 'tickers' or (capability == 'snapshot' and 'thscodes' not in params):
            semantics['pagination_scope'] = 'one_page_only_use_limit_offset_to_continue'
        return {'source': 'ths_fuyao', 'endpoint': endpoint, 'params': params,
            'retrieved_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'research_only': True, 'orders_authorized': False,
            'semantics': semantics, 'response': value}


def probe(client, *, today=None):
    """Ten small read-only requests; failed capabilities are reported separately."""
    today = today or dt.datetime.now(SHANGHAI).date()
    start = (today - dt.timedelta(days=14)).isoformat()
    end = (today - dt.timedelta(days=1)).isoformat()
    specs = [
        ('calendar', {}),
        ('search', {'q': '600519.SH', 'limit': 1}),
        ('historical', {'thscode': '600519.SH', 'start': start, 'end': end}),
        ('income', {'thscode': '600519.SH', 'period': 'annual', 'limit': 1}),
        ('balance', {'thscode': '600519.SH', 'period': 'annual', 'limit': 1}),
        ('cashflow', {'thscode': '600519.SH', 'period': 'annual', 'limit': 1}),
        ('actions', {'thscode': '600519.SH', 'from': str(today.year - 1) + '-01-01', 'to': end}),
        ('valuations', {'thscodes': '600519.SH'}),
        ('constituents', {'thscode': '000300.SH'}),
        ('fund_historical', {'thscode': '510300.SH', 'start': start, 'end': end}),
    ]
    results = []
    for capability, params in specs:
        try:
            record = client.query(capability, **params)
            value = record['response']
            rows = value['data']['item']
            results.append({'capability': capability, 'status': 'available' if rows else 'empty',
                'rows': len(rows), 'request_id': value.get('request_id'),
                'source_timestamp_ms': value['data'].get('timestamp'),
                'fields': sorted(set().union(*(row.keys() for row in rows))),
                'semantics': record['semantics']})
        except FuyaoError as exc:
            results.append({'capability': capability, 'status': 'failed', 'error': str(exc)})
            # Stop for authentication, rate limits or transport failures; no automatic retries.
            if str(exc) in ('fuyao_provider_code_2001', 'fuyao_rate_limited', 'fuyao_network_error'):
                break
    return {'source': 'ths_fuyao', 'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'research_only': True, 'orders_authorized': False, 'planned_requests': len(specs),
        'checks': results, 'ok': len(results) == len(specs) and all(r['status'] == 'available' for r in results)}
