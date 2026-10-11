"""Immutable WSL/E runner for one conditional A-share information study.

This module has no API, account, order, portfolio or model-training interface.
It reads prices only after scoped same-provider qualification and hash checks.
"""
from __future__ import annotations

import collections
import concurrent.futures
import csv
import dataclasses
import gzip
import hashlib
import io
import json
import math
import os
import statistics
import sys
import zipfile
from array import array
from pathlib import Path

from qount.research.ashare_information import (
    InformationDate, OpenObservation, SourceQualification, aggregate_information_gate,
    freeze_membership, member_label_statistic, open_proxy_label, require_qualified_source,
)
from qount.research.ashare_selection import (
    ARTIFACTS, DATASETS, fixed_price_strata, official_calendar, prefix_locator, verify_manifest,
)
from qount.research.ashare_statistics import decision_mask
from qount.research_data.equity_archive import FIELDS, sha256, write_json

ROOT = Path(__file__).resolve().parents[3]
REQUIRED_SOURCE_FILES = (
    'src/qount/__init__.py', 'src/qount/research/__init__.py',
    'src/qount/research_data/__init__.py', 'src/qount/research_data/equity_archive.py',
    'src/qount/research/ashare_selection.py', 'src/qount/research/ashare_statistics.py',
    'src/qount/research/ashare_information.py', 'src/qount/research/ashare_information_run.py',
    'src/qount/research/ashare_source_reconcile.py',
)
DIAGNOSTIC_DEFINITIONS = {
    'rank_IC': 'within_stratum_Spearman_average_ties_conditional_known_pairs_equal_stratum_weight',
    'recent5': 'adjusted_close_t_over_t_minus_5_minus_1',
    'vol20': 'population_std_of_last_20_close_to_close_log_changes_not_annualized',
    'amount60': 'mean_raw_amount_t_minus_59_through_t_times_1000_CNY',
    'PIT_industry_and_float_cap': 'not_implemented_unavailable',
}


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _positive(value):
    return value is not None and value > 0


@dataclasses.dataclass
class SecuritySeries:
    symbol: str
    closes: array
    opens: array
    amounts: array
    history: array
    window_status: bytearray
    open_status: bytearray
    M: array
    A: array
    pre_calendar_valid_observations: int
    source_kind: str


def _rows_to_series(symbol, rows, sessions, *, source_kind, factors=None):
    """Exact-session arrays; pre-calendar rows count only past raw maturity."""
    n, index = len(sessions), {day: i for i, day in enumerate(sessions)}
    closes, opens, amounts = (array('d', [math.nan]) * n for _ in range(3))
    history = array('I', [0]) * n
    present, valid, open_status = (bytearray(n) for _ in range(3))
    count = pre_calendar = 0
    previous = ''
    for row in rows:
        day = row['trade_date']
        if (row['ts_code'] != symbol or not isinstance(day, str) or len(day) != 8
                or not day.isdigit() or day <= previous):
            raise ValueError('information_source_identity_or_date_order')
        previous = day
        raw = [_number(row[key]) for key in ('open', 'high', 'low', 'close')]
        raw_valid = (all(_positive(value) for value in raw)
                     and raw[2] <= min(raw[0], raw[3]) <= max(raw[0], raw[3]) <= raw[1])
        count += raw_valid
        if day < sessions[0]:
            pre_calendar += raw_valid
            continue
        if day not in index:
            raise ValueError('information_source_date_outside_frozen_calendar:' + day)
        j = index[day]
        present[j], history[j] = 1, count
        amount = _number(row.get('amount'))
        if source_kind == 'original_zip':
            factor = _number(row.get('adj_factor'))
            adjusted = [_number(row.get('adj_' + key)) for key in ('open', 'high', 'low', 'close')]
        else:
            factor = factors.get(day)
            adjusted = [value * factor if _positive(value) and _positive(factor) else None for value in raw]
            adjusted = [value if value is not None and math.isfinite(value) else None for value in adjusted]
        if _positive(adjusted[0]) and _positive(factor):
            opens[j] = adjusted[0]
            open_status[j] = 1 if _positive(amount) else 2 if amount == 0 else 0
        if _positive(adjusted[3]):
            closes[j] = adjusted[3]
        if amount is not None:
            amounts[j] = amount
        valid[j] = raw_valid and _positive(factor) and all(_positive(value) for value in adjusted) and _positive(amount)
    last, running = pre_calendar, 0
    status = bytearray(n)
    momentum, activity = array('d', [math.nan]) * n, array('d', [math.nan]) * n
    for j in range(n):
        if present[j]:
            last = history[j]
        else:
            history[j] = last
        running += valid[j]
        if j >= 65:
            running -= valid[j-65]
        if history[j] < 252:
            status[j] = 1
        elif j < 64 or running != 65:
            status[j] = 2
        else:
            try:
                m = math.log(closes[j-5] / closes[j-60])
                a = math.log(statistics.fmean(amounts[j-4:j+1]) / statistics.fmean(amounts[j-64:j-4]))
            except (OverflowError, ValueError, ZeroDivisionError):
                status[j] = 3
                continue
            if not math.isfinite(m) or not math.isfinite(a):
                status[j] = 3
            else:
                momentum[j], activity[j] = m, a
    return SecuritySeries(symbol, closes, opens, amounts, history, status, open_status,
                          momentum, activity, pre_calendar, source_kind)


def _original_batch(archive, entries, sessions):
    result = []
    with zipfile.ZipFile(archive) as source:
        for entry in entries:
            with source.open(entry['member']) as member:
                reader = csv.DictReader(io.TextIOWrapper(member, encoding='utf-8-sig', newline=''))
                if tuple(reader.fieldnames or ()) != FIELDS:
                    raise ValueError('information_original_schema')
                result.append(_rows_to_series(entry['symbol'], reader, sessions, source_kind='original_zip'))
    return result


def _response_rows(root, request):
    target = (root / request['file']).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('information_response_path_escape')
    raw = gzip.decompress(target.read_bytes())
    if hashlib.sha256(raw).hexdigest() != request['raw_response_sha256']:
        raise ValueError('information_response_raw_hash')
    body = json.loads(raw)
    data = body.get('data')
    if body.get('code') != 0 or not isinstance(data, dict) or data.get('has_more') is not False:
        raise ValueError('information_response_not_complete')
    fields = data['fields']
    if len(fields) != len(set(fields)):
        raise ValueError('information_response_duplicate_fields')
    rows = [dict(zip(fields, row, strict=True)) for row in data['items']]
    if len(rows) != request['rows'] or (request['api_name'] == 'daily' and len(rows) >= 6000):
        raise ValueError('information_response_count_or_unproven_pagination')
    if any(row.get('ts_code') != request['params']['ts_code'] for row in rows):
        raise ValueError('information_response_security_mismatch')
    return rows


def _preflight(contract_path, qualification_root, source_root, calendar_path):
    """Metadata first; a false scoped receipt fails before any raw hashing/read."""
    contract = json.loads(contract_path.read_text())
    authorization = contract.get('authorization', {})
    if (contract.get('phase') != 'ashare_information_price_proxy'
            or contract.get('research_only') is not True or contract.get('orders_authorized') is not False
            or contract.get('promotion_evidence') is not False or contract.get('holdout_role') != 'discovery'
            or authorization.get('information_study_run') is not True
            or authorization.get('automatic_restart') is not False
            or authorization.get('production_or_account_access') is not False
            or contract.get('workers') != 4):
        raise ValueError('information_run_contract_not_authorized')
    inputs = {}
    for key in ('proposal', 'stage', 'original_qualification'):
        binding = contract['inputs'][key]
        path = Path(binding['path'])
        if not path.is_absolute():
            path = ROOT / path
        if sha256(path) != binding['sha256']:
            raise ValueError('information_input_binding:' + key)
        inputs[key] = json.loads(path.read_text())
    if (inputs['stage']['original_proposal_sha256'] != contract['inputs']['proposal']['sha256']
            or inputs['proposal']['holdout_role'] != 'discovery'):
        raise ValueError('information_original_protocol_binding')
    manifest_path = qualification_root / 'manifest.json'
    if sha256(manifest_path) != contract['qualification_manifest_sha256']:
        raise ValueError('information_qualification_manifest_binding')
    qmanifest = json.loads(manifest_path.read_text())
    summary_path = qualification_root / 'summary.json'
    summary_hash = sha256(summary_path)
    if summary_hash != contract['qualification_summary_sha256'] or qmanifest.get('summary.json') != summary_hash:
        raise ValueError('information_qualification_summary_binding')
    summary = json.loads(summary_path.read_text())
    qualification = SourceQualification(
        summary.get('source_vendor_verified') is True,
        summary.get('adjustment_semantics_verified_for_information_proxy') is True,
        summary.get('independent_calendar_verified') is True,
        summary.get('source_manifest_sha256', ''), summary.get('calendar_review_sha256', ''),
        summary.get('adjustment_semantics_review_sha256', ''), summary_hash,
        summary.get('adjustment_semantics_scope', ''))
    require_qualified_source(qualification)
    if (contract.get('diagnostic_definitions') != DIAGNOSTIC_DEFINITIONS
            or contract.get('python_version') != sys.version.split()[0]):
        raise ValueError('information_diagnostic_or_python_freeze')
    if (summary.get('status') != 'vendor_price_proxy_field_application_qualified'
            or summary.get('research_only') is not True or summary.get('orders_authorized') is not False
            or summary.get('corporate_action_economic_accuracy_verified') is not False
            or summary.get('cash_total_return_verified') is not False
            or summary.get('source_manifest_sha256') != contract['source_manifest_sha256']
            or summary.get('calendar_review_sha256') != contract['calendar_review_sha256']
            or sha256(calendar_path) != contract['calendar_review_sha256']):
        raise ValueError('information_scoped_receipt_binding')
    implementations = contract['implementation_sha256']
    if not set(REQUIRED_SOURCE_FILES) <= set(implementations):
        raise ValueError('information_implementation_dependency_not_bound')
    for relative, digest in implementations.items():
        target = (ROOT / relative).resolve()
        if not target.is_relative_to(ROOT) or sha256(target) != digest:
            raise ValueError('information_implementation_binding:' + relative)
    # Raw/source hashing is deliberately below the typed affirmative guard.
    verify_manifest(qualification_root, contract['qualification_manifest_sha256'])
    verify_manifest(source_root, contract['source_manifest_sha256'])
    q = inputs['original_qualification']
    archive = Path(q['source']['archive'])
    if (sha256(archive) != q['source']['sha256']
            or summary['source_archive_sha256'] != q['source']['sha256']):
        raise ValueError('information_original_archive_binding')
    audit_root = Path(q['source']['audit_root'])
    verify_manifest(audit_root, q['source']['audit_manifest_sha256'])
    inventory = json.loads((audit_root / 'members.json').read_text())
    prefixes = q['qualification']['prefix_locator_not_historical_identity']
    entries = [row for row in inventory if prefix_locator(row['symbol'], prefixes)]
    if len(entries) != contract['expected_original_securities'] or len({row['symbol'] for row in entries}) != len(entries):
        raise ValueError('information_original_inventory')
    calendar = json.loads(calendar_path.read_text())
    sessions, _ = official_calendar(calendar, '2014-01-01', '2026-09-30')
    second, _ = official_calendar(calendar, '2014-01-01', '2026-09-30', 'SZSE')
    if sessions != second:
        raise ValueError('information_exchange_calendar_difference')
    acquisition = json.loads((source_root / 'acquisition.json').read_text())
    if acquisition.get('status') != 'completed' or acquisition.get('completed_requests') != 807:
        raise ValueError('information_source_acquisition_incomplete')
    return contract, inputs, qualification, entries, sessions, archive, acquisition


class _SeriesOpens:
    def __init__(self, series, sessions, qualification):
        self.series = series
        self.index = {day: i for i, day in enumerate(sessions)}
        self.qualification = qualification

    def get(self, key):
        symbol, day = key
        series, j = self.series[symbol], self.index[day]
        status = series.open_status[j]
        if status == 0:
            return None
        return OpenObservation(series.opens[j], 'observed' if status == 1 else 'synthetic_suspension',
                               self.qualification.source_manifest_sha256,
                               self.qualification.adjustment_semantics_sha256)


def _ranks(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        for position in order[i:j]:
            result[position] = (i + j - 1) / 2
        i = j
    return result


def _rank_ic(activity, outcomes):
    if len(activity) < 2:
        return None
    a, b = _ranks(activity), _ranks(outcomes)
    am, bm = statistics.fmean(a), statistics.fmean(b)
    numerator = math.fsum((x-am)*(y-bm) for x, y in zip(a, b))
    denominator = math.sqrt(math.fsum((x-am)**2 for x in a) * math.fsum((y-bm)**2 for y in b))
    return numerator / denominator if denominator else None


def _exposures(membership, series, j):
    result = []
    for layer in membership.strata:
        values = {}
        for name in layer.full:
            item = series[name]
            changes = [math.log(item.closes[k]/item.closes[k-1]) for k in range(j-19, j+1)]
            values[name] = {'recent_5_session_return': item.closes[j]/item.closes[j-5]-1,
                            '20_session_volatility': statistics.pstdev(changes),
                            '60_session_amount_level_cny': statistics.fmean(item.amounts[j-59:j+1])*1000}
        result.append({key: {'top_mean': statistics.fmean(values[name][key] for name in layer.top),
                             'full_mean': statistics.fmean(values[name][key] for name in layer.full)}
                       for key in next(iter(values.values()))})
    return result


def _emit(stream, value):
    stream.write(json.dumps(value, separators=(',', ':'), allow_nan=False) + '\n')


def run(*, contract_path, qualification_root, source_root, calendar_path, out):
    if (sys.platform != 'linux' or not os.path.ismount('/mnt/e')
            or not out.resolve().is_relative_to(ARTIFACTS) or out.exists()
            or not source_root.resolve().is_relative_to(DATASETS)
            or not qualification_root.resolve().is_relative_to(ARTIFACTS)):
        raise ValueError('information_requires_WSL_and_new_E_artifact_root')
    contract, inputs, qualification, entries, sessions, archive, acquisition = _preflight(
        contract_path, qualification_root, source_root, calendar_path)
    out.mkdir(parents=True, exist_ok=False)
    write_json(out/'contract.json', contract)
    write_json(out/'run-state.json', {'status': 'running', 'research_only': True, 'orders_authorized': False})
    try:
        all_series = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_original_batch, archive, entries[i:i+32], sessions)
                       for i in range(0, len(entries), 32)]
            for future in concurrent.futures.as_completed(futures):
                all_series.extend(future.result())
        retired = {}
        for request in acquisition['responses']:
            if request['role'] != 'missing_retired_same_provider_source_supplement':
                continue
            symbol, api = request['params']['ts_code'], request['api_name']
            parts = retired.setdefault(symbol, {})
            if api not in ('daily', 'adj_factor') or api in parts:
                raise ValueError('information_retired_duplicate_or_unknown_api')
            parts[api] = _response_rows(source_root, request)
        if len(retired) != contract['expected_retired_securities']:
            raise ValueError('information_retired_inventory')
        for symbol, parts in sorted(retired.items()):
            if set(parts) != {'daily', 'adj_factor'}:
                raise ValueError('information_retired_missing_api')
            factors = {row['trade_date']: _number(row['adj_factor']) for row in parts['adj_factor']}
            if len(factors) != len(parts['adj_factor']) or any(not _positive(value) for value in factors.values()):
                raise ValueError('information_retired_factor_identity_or_value')
            rows = sorted(parts['daily'], key=lambda row: row['trade_date'])
            all_series.append(_rows_to_series(symbol, rows, sessions, source_kind='tushare_retired', factors=factors))
        series = {item.symbol: item for item in all_series}
        if len(series) != len(all_series):
            raise ValueError('information_original_and_retired_overlap')
        boundaries = tuple(next(i for i, day in enumerate(sessions) if day >= border)
                           for border in ('20190101', '20230101'))
        full_mask = decision_mask(len(sessions), boundaries)
        indices = [i for i, day in enumerate(sessions) if '20150101' <= day <= '20260930']
        dates = tuple(sessions[i] for i in indices)
        mask = [full_mask[i] for i in indices]
        if (len(dates) != 2855 or sum(mask) != inputs['stage']['analysis_calendar']['planned_decision_dates_before_security_label_gates']):
            raise ValueError('information_planned_calendar_count')
        opens = _SeriesOpens(series, sessions, qualification)
        primary, reasons = [], ('eligible', 'fewer_than_252_past_valid_raw_prices', 'incomplete_positive_recent_65_sessions', 'invalid_feature_arithmetic')
        names = sorted(series)
        paths = ('daily-eligibility.jsonl.gz', 'memberships.jsonl.gz', 'labels-four-cells.jsonl.gz',
                 'date-statistics-four-cells.jsonl.gz', 'diagnostics.jsonl.gz')
        with (gzip.open(out/paths[0], 'wt', encoding='utf-8', compresslevel=6) as eligibility_out,
              gzip.open(out/paths[1], 'wt', encoding='utf-8', compresslevel=6) as membership_out,
              gzip.open(out/paths[2], 'wt', encoding='utf-8', compresslevel=6) as label_out,
              gzip.open(out/paths[3], 'wt', encoding='utf-8', compresslevel=6) as statistics_out,
              gzip.open(out/paths[4], 'wt', encoding='utf-8', compresslevel=6) as diagnostic_out):
            for j, day, retain in zip(indices, dates, mask):
                eligible = [name for name in names if series[name].window_status[j] == 0]
                excluded = {reason: [name for name in names if series[name].window_status[j] == code]
                            for code, reason in enumerate(reasons) if code}
                _emit(eligibility_out, {'date': day, 'analysis_mask': retain, 'eligible': eligible, 'excluded': excluded})
                if not retain:
                    primary.append(InformationDate(day, 'masked', reason='frozen_maturity_purge_or_embargo'))
                    _emit(statistics_out, {'date': day, 'status': 'masked', 'cells_computed': 0})
                    continue
                rows = [{'symbol': name, 'M': series[name].M[j], 'A': series[name].A[j]} for name in eligible]
                strata = fixed_price_strata(rows)
                if strata is None:
                    primary.append(InformationDate(day, 'predecision_ineligible', reason='fewer_than_500_or_20_per_stratum'))
                    _emit(statistics_out, {'date': day, 'status': 'predecision_ineligible', 'cells_computed': 0})
                    continue
                membership = freeze_membership(strata, qualification=qualification, decision_date=day)
                _emit(membership_out, {'date': day, 'membership_sha256': membership.sha256,
                                       'strata': dataclasses.asdict(membership)['strata']})
                exposures = _exposures(membership, series, j)
                for horizon, delay in ((20, 0), (20, 1), (5, 0), (5, 1)):
                    labels = {name: open_proxy_label(qualification=qualification, sessions=sessions, decision_index=j,
                                                     security_id=name, opens=opens, horizon=horizon, delay=delay)
                              for layer in membership.strata for name in layer.full}
                    for label in labels.values():
                        _emit(label_out, {'membership_sha256': membership.sha256, **vars(label)})
                    stat = member_label_statistic(membership, labels, qualification=qualification,
                                                  decision_date=day, horizon=horizon, delay=delay)
                    _emit(statistics_out, {**dataclasses.asdict(stat), 'increment': stat.increment,
                                            'unknown_labels': stat.unknown_labels, 'denominators': stat.denominators})
                    ics = []
                    for layer in membership.strata:
                        known = [name for name in layer.full if labels[name].status == 'known']
                        ics.append({'rank_IC': _rank_ic([series[name].A[j] for name in known], [labels[name].value for name in known]),
                                    'known_pairs': len(known), 'original_denominator': len(layer.full)})
                    _emit(diagnostic_out, {'date': day, 'horizon': horizon, 'delay': delay, 'role': 'diagnostic_only',
                                           'membership_sha256': membership.sha256, 'per_stratum_rank_IC': ics,
                                           'equal_stratum_rank_IC': None if any(item['rank_IC'] is None for item in ics)
                                               else statistics.fmean(item['rank_IC'] for item in ics),
                                           'IC_known_pairs_conditional_only': any(item['known_pairs'] != item['original_denominator'] for item in ics),
                                           'past_only_exposures': exposures})
                    if horizon == 20 and delay == 0:
                        primary.append(InformationDate(day, 'eligible', stat))
        gate = aggregate_information_gate(qualification=qualification, decision_dates=dates, analysis_mask=mask, rows=primary)
        summary = {'status': 'completed_conditional_information_price_proxy_discovery',
                   'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
                   'holdout_role': 'discovery', 'independent_OOS_claim': False, 'information_gate': gate,
                   'original_securities': len(entries), 'same_provider_retired_securities': len(retired),
                   'total_securities': len(series), 'planned_grid_dates': len(dates), 'analysis_mask_dates': sum(mask),
                   'pre_calendar_valid_raw_observations': sum(item.pre_calendar_valid_observations for item in all_series),
                   'pre_calendar_observation_dates_independently_certified': False,
                   'historical_mainboard_identity_ST_and_universe_complete': False,
                   'corporate_action_economic_accuracy_verified': False, 'cash_total_return_verified': False,
                   'portfolio_or_execution_certified': False, 'candidate_count': 1, 'model_fits': 0, 'parameter_searches': 0,
                   'python_version': sys.version.split()[0],
                   'diagnostics': {'rank_IC': 'implemented_conditional_known_pairs',
                                   'recent5': 'adjusted_close_t_over_t_minus_5_minus_1',
                                   'vol20': 'population_std_of_last_20_close_to_close_log_changes_not_annualized',
                                   'amount60': 'mean_raw_amount_t_minus_59_through_t_times_1000_CNY',
                                   'PIT_industry_and_float_cap': 'not_implemented_unavailable'},
                   'source_manifest_sha256': qualification.source_manifest_sha256,
                   'source_archive_sha256': inputs['original_qualification']['source']['sha256'],
                   'calendar_review_sha256': sha256(calendar_path), 'contract_sha256': sha256(contract_path),
                   'qualification_receipt_sha256': qualification.qualification_receipt_sha256,
                   'qualification_scope': qualification.qualification_scope}
        write_json(out/'summary.json', summary)
        write_json(out/'run-state.json', {'status': 'completed', 'research_only': True, 'orders_authorized': False})
        write_json(out/'manifest.json', {path.name: sha256(path) for path in sorted(out.iterdir()) if path.name != 'manifest.json'})
        return summary
    except BaseException as exc:
        write_json(out/'run-state.json', {'status': 'failed', 'error_type': type(exc).__name__, 'error': str(exc),
                                         'automatic_restart_authorized': False, 'orders_authorized': False})
        raise
