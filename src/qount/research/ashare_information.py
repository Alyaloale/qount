"""Pure, guarded open-price labels and gates for the fixed A-share study.

No files, APIs, credentials, orders or portfolios are accessed here. A loader
must verify immutable manifests before constructing SourceQualification; this
typed receipt is not itself a verifier of those external files. All results
are discovery research price proxies, never certified fills or account NAV.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass
from functools import cached_property, lru_cache

from qount.research.ashare_statistics import calendar_block_mean_interval


class SourceQualificationError(ValueError):
    """No real input may be evaluated without an affirmative source receipt."""


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@lru_cache(maxsize=8192)
def _date(value):
    if not isinstance(value, str):
        raise ValueError('ashare_date_must_be_string')
    if re.fullmatch(r'\d{8}', value):
        return dt.datetime.strptime(value, '%Y%m%d').date()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('ashare_invalid_date_spelling')
    return dt.date.fromisoformat(value)


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


@lru_cache(maxsize=8)
def _validated_calendar(sessions):
    dates = tuple(_date(day) for day in sessions)
    if not dates or any(a >= b for a, b in zip(dates, dates[1:])):
        raise ValueError('ashare_calendar_not_strictly_increasing')
    return True


@dataclass(frozen=True)
class SourceQualification:
    source_vendor_verified: bool
    adjustment_semantics_verified: bool
    independent_both_exchange_calendar_verified: bool
    source_manifest_sha256: str
    calendar_manifest_sha256: str
    adjustment_semantics_sha256: str
    qualification_receipt_sha256: str
    qualification_scope: str

    def missing(self):
        flags = ('source_vendor_verified', 'adjustment_semantics_verified',
                 'independent_both_exchange_calendar_verified')
        hashes = ('source_manifest_sha256', 'calendar_manifest_sha256',
                  'adjustment_semantics_sha256', 'qualification_receipt_sha256')
        return tuple([name for name in flags if getattr(self, name) is not True]
                     + [name for name in hashes if not _digest(getattr(self, name))]
                     + ([] if self.qualification_scope == 'vendor_defined_adjusted_price_proxy'
                        else ['qualification_scope']))


def require_qualified_source(qualification):
    if not isinstance(qualification, SourceQualification):
        raise SourceQualificationError('ashare_typed_source_qualification_required')
    missing = qualification.missing()
    if missing:
        raise SourceQualificationError('ashare_source_not_qualified:' + ','.join(missing))


@dataclass(frozen=True)
class LabelEndpoints:
    decision_index: int
    entry_index: int
    exit_index: int
    horizon: int
    delay: int
    uniform_mature: bool


def label_endpoints(decision_index, session_count, *, horizon=20, delay=0):
    """Arithmetic only: all cells share the latest t+22 maturity cutoff."""
    if (type(decision_index) is not int or type(session_count) is not int
            or not 0 <= decision_index < session_count):
        raise ValueError('ashare_invalid_decision_index')
    if type(horizon) is not int or horizon not in (20, 5) or type(delay) is not int or delay not in (0, 1):
        raise ValueError('ashare_unregistered_label_cell')
    return LabelEndpoints(decision_index, decision_index + 1 + delay,
                          decision_index + 1 + delay + horizon, horizon, delay,
                          decision_index + 22 < session_count)


@dataclass(frozen=True)
class OpenObservation:
    adjusted_open: float | None
    status: str
    source_manifest_sha256: str
    adjustment_semantics_sha256: str

    def __post_init__(self):
        if self.status not in ('observed', 'missing', 'synthetic_suspension', 'unknown', 'invalid'):
            raise ValueError('ashare_unknown_open_observation_status')


@dataclass(frozen=True)
class OpenProxyLabel:
    security_id: str
    decision_date: str
    horizon: int
    delay: int
    entry_date: str | None
    exit_date: str | None
    status: str
    value: float | None
    reason: str | None
    source_manifest_sha256: str
    adjustment_semantics_sha256: str

    def __post_init__(self):
        _date(self.decision_date)
        if not isinstance(self.security_id, str) or not self.security_id:
            raise ValueError('ashare_label_security_identity_required')
        if (type(self.horizon) is not int or self.horizon not in (20, 5)
                or type(self.delay) is not int or self.delay not in (0, 1)):
            raise ValueError('ashare_unregistered_label_cell')
        if not _digest(self.source_manifest_sha256) or not _digest(self.adjustment_semantics_sha256):
            raise ValueError('ashare_label_requires_source_and_semantics_binding')
        if self.status not in ('known', 'unknown', 'immature'):
            raise ValueError('ashare_unknown_label_status')
        if self.status == 'known':
            if not _finite(self.value) or self.value <= -1 or self.reason is not None:
                raise ValueError('ashare_invalid_known_open_label')
            if (self.entry_date is None or self.exit_date is None
                    or not _date(self.decision_date) < _date(self.entry_date) < _date(self.exit_date)):
                raise ValueError('ashare_invalid_known_label_dates')
        elif self.value is not None or not self.reason:
            raise ValueError('ashare_unknown_label_requires_reason_and_no_value')


def open_proxy_label(*, qualification, sessions, decision_index, security_id, opens,
                     horizon=20, delay=0):
    """Read exactly two calendar endpoints after the qualification guard.

    opens is keyed by (security_id, session_string), with the exact spelling
    used in sessions. There is no next-available-record or suspension fill.
    """
    require_qualified_source(qualification)
    if type(sessions) is not tuple:
        raise ValueError('ashare_immutable_calendar_tuple_required')
    _validated_calendar(sessions)
    endpoints = label_endpoints(decision_index, len(sessions), horizon=horizon, delay=delay)
    entry = sessions[endpoints.entry_index] if endpoints.entry_index < len(sessions) else None
    exit_ = sessions[endpoints.exit_index] if endpoints.exit_index < len(sessions) else None
    fields = (security_id, sessions[decision_index], horizon, delay, entry, exit_)
    binding = {'source_manifest_sha256': qualification.source_manifest_sha256,
               'adjustment_semantics_sha256': qualification.adjustment_semantics_sha256}
    if not endpoints.uniform_mature:
        return OpenProxyLabel(*fields, 'immature', None, 'uniform_t_plus_22_not_mature', **binding)
    values = []
    for kind, day in (('entry', entry), ('exit', exit_)):
        observation = opens.get((security_id, day))
        if observation is None:
            return OpenProxyLabel(*fields, 'unknown', None, kind + '_endpoint_missing', **binding)
        if not isinstance(observation, OpenObservation):
            raise ValueError('ashare_typed_open_observation_required')
        if (observation.source_manifest_sha256 != qualification.source_manifest_sha256
                or observation.adjustment_semantics_sha256 != qualification.adjustment_semantics_sha256):
            raise SourceQualificationError('ashare_open_source_or_semantics_binding_mismatch')
        if observation.status != 'observed':
            return OpenProxyLabel(*fields, 'unknown', None, kind + '_' + observation.status, **binding)
        if not _finite(observation.adjusted_open) or observation.adjusted_open <= 0:
            return OpenProxyLabel(*fields, 'unknown', None, kind + '_open_nonpositive_or_nonfinite', **binding)
        values.append(observation.adjusted_open)
    ratio = values[1] / values[0]
    if not math.isfinite(ratio) or ratio <= 0:
        return OpenProxyLabel(*fields, 'unknown', None, 'open_ratio_overflow_or_underflow', **binding)
    value = ratio - 1
    if value <= -1:
        return OpenProxyLabel(*fields, 'unknown', None, 'open_ratio_precision_loss', **binding)
    return OpenProxyLabel(*fields, 'known', value, None, **binding)


@dataclass(frozen=True)
class StratumMembership:
    full: tuple[str, ...]
    top: tuple[str, ...]

    def __post_init__(self):
        if (type(self.full) is not tuple or type(self.top) is not tuple
                or len(self.full) < 20 or len(set(self.full)) != len(self.full)
                or len(self.top) != len(self.full) // 3 or len(set(self.top)) != len(self.top)
                or not set(self.top) <= set(self.full)
                or any(not isinstance(name, str) or not name for name in self.full)):
            raise ValueError('ashare_invalid_stratum_membership')


@dataclass(frozen=True)
class FrozenMembership:
    strata: tuple[StratumMembership, ...]
    decision_date: str
    source_manifest_sha256: str
    adjustment_semantics_sha256: str

    def __post_init__(self):
        _date(self.decision_date)
        if type(self.strata) is not tuple or any(not isinstance(layer, StratumMembership) for layer in self.strata):
            raise ValueError('ashare_immutable_typed_strata_required')
        if not _digest(self.source_manifest_sha256) or not _digest(self.adjustment_semantics_sha256):
            raise ValueError('ashare_membership_requires_source_and_semantics_binding')
        names = [name for layer in self.strata for name in layer.full]
        if len(self.strata) != 5 or len(names) != len(set(names)):
            raise ValueError('ashare_five_disjoint_strata_required')

    @cached_property
    def sha256(self):
        value = {'strata': [{'full': layer.full, 'top': layer.top} for layer in self.strata],
                 'decision_date': _date(self.decision_date).isoformat(),
                 'source_manifest_sha256': self.source_manifest_sha256,
                 'adjustment_semantics_sha256': self.adjustment_semantics_sha256}
        return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


def freeze_membership(strata, *, qualification, decision_date):
    """Freeze existing M strata and deterministic top thirds before labels.

    The caller supplies the unchanged fixed_price_strata output; this does
    not construct a different eligible universe or substitute top-minus-rest.
    """
    require_qualified_source(qualification)
    layers = []
    for layer in strata:
        if any(not _finite(row[key]) for row in layer for key in ('M', 'A')):
            raise ValueError('ashare_nonfinite_membership_feature')
        top = sorted(layer, key=lambda row: (-row['A'], -row['M'], row['symbol']))[:len(layer) // 3]
        layers.append(StratumMembership(tuple(row['symbol'] for row in layer),
                                        tuple(row['symbol'] for row in top)))
    return FrozenMembership(tuple(layers), decision_date, qualification.source_manifest_sha256,
                            qualification.adjustment_semantics_sha256)


@dataclass(frozen=True)
class UnknownMember:
    security_id: str
    reason: str
    in_top: bool

    def __post_init__(self):
        if not self.security_id or not self.reason or type(self.in_top) is not bool:
            raise ValueError('ashare_unknown_member_requires_identity_reason_and_top_flag')


@dataclass(frozen=True)
class StratumInformation:
    full_denominator: int
    top_denominator: int
    increment: float | None
    unknown: tuple[UnknownMember, ...] = ()

    def __post_init__(self):
        if (type(self.full_denominator) is not int or type(self.top_denominator) is not int
                or self.full_denominator < 20 or self.top_denominator != self.full_denominator // 3):
            raise ValueError('ashare_invalid_information_denominator')
        if (type(self.unknown) is not tuple or any(not isinstance(item, UnknownMember) for item in self.unknown)
                or len({item.security_id for item in self.unknown}) != len(self.unknown)
                or len(self.unknown) > self.full_denominator
                or sum(item.in_top for item in self.unknown) > self.top_denominator):
            raise ValueError('ashare_invalid_unknown_member_registry')
        if self.unknown:
            if self.increment is not None:
                raise ValueError('ashare_unknown_stratum_cannot_have_increment')
        elif not _finite(self.increment):
            raise ValueError('ashare_known_stratum_requires_finite_increment')


@dataclass(frozen=True)
class InformationDay:
    decision_date: str
    horizon: int
    delay: int
    membership_sha256: str
    strata: tuple[StratumInformation, ...]
    source_manifest_sha256: str
    adjustment_semantics_sha256: str

    def __post_init__(self):
        _date(self.decision_date)
        if (type(self.horizon) is not int or self.horizon not in (20, 5)
                or type(self.delay) is not int or self.delay not in (0, 1)):
            raise ValueError('ashare_unregistered_label_cell')
        if (type(self.strata) is not tuple or len(self.strata) != 5
                or any(not isinstance(layer, StratumInformation) for layer in self.strata)
                or not _digest(self.membership_sha256)
                or not _digest(self.source_manifest_sha256)
                or not _digest(self.adjustment_semantics_sha256)):
            raise ValueError('ashare_invalid_information_day')

    @property
    def increment(self):
        if any(layer.increment is None for layer in self.strata):
            return None
        return statistics.fmean(layer.increment for layer in self.strata)

    @property
    def unknown_labels(self):
        return {'top': sum(item.in_top for layer in self.strata for item in layer.unknown),
                'full': sum(len(layer.unknown) for layer in self.strata)}

    @property
    def denominators(self):
        return {'top': sum(layer.top_denominator for layer in self.strata),
                'full': sum(layer.full_denominator for layer in self.strata)}


def member_label_statistic(membership, labels, *, qualification, decision_date, horizon=20, delay=0):
    """One shared label per member, preserving unknowns and fixed denominators."""
    require_qualified_source(qualification)
    if not isinstance(membership, FrozenMembership):
        raise ValueError('ashare_typed_frozen_membership_required')
    if (membership.source_manifest_sha256 != qualification.source_manifest_sha256
            or membership.adjustment_semantics_sha256 != qualification.adjustment_semantics_sha256):
        raise SourceQualificationError('ashare_membership_source_or_semantics_binding_mismatch')
    expected_date = _date(decision_date)
    if _date(membership.decision_date) != expected_date:
        raise ValueError('ashare_membership_decision_date_mismatch')
    layers = []
    for layer in membership.strata:
        top_ids, known, unknown = set(layer.top), {}, []
        for name in layer.full:
            label = labels.get(name)
            if label is None:
                unknown.append(UnknownMember(name, 'label_absent', name in top_ids))
                continue
            if not isinstance(label, OpenProxyLabel):
                raise ValueError('ashare_typed_member_label_required')
            if (label.security_id != name or _date(label.decision_date) != expected_date
                    or label.horizon != horizon or label.delay != delay):
                raise ValueError('ashare_label_identity_date_or_cell_mismatch')
            if (label.source_manifest_sha256 != qualification.source_manifest_sha256
                    or label.adjustment_semantics_sha256 != qualification.adjustment_semantics_sha256):
                raise SourceQualificationError('ashare_member_label_source_or_semantics_binding_mismatch')
            if label.status != 'known':
                unknown.append(UnknownMember(name, label.reason, name in top_ids))
            else:
                known[name] = label.value
        increment = None if unknown else (statistics.fmean(known[name] for name in layer.top)
                                          - statistics.fmean(known[name] for name in layer.full))
        layers.append(StratumInformation(len(layer.full), len(layer.top), increment, tuple(unknown)))
    return InformationDay(decision_date, horizon, delay, membership.sha256, tuple(layers),
                          qualification.source_manifest_sha256, qualification.adjustment_semantics_sha256)


@dataclass(frozen=True)
class InformationDate:
    decision_date: str
    status: str
    statistic: InformationDay | None = None
    reason: str | None = None

    def __post_init__(self):
        day = _date(self.decision_date)
        if self.status not in ('eligible', 'masked', 'predecision_ineligible'):
            raise ValueError('ashare_invalid_information_date_status')
        if self.status == 'eligible':
            if not isinstance(self.statistic, InformationDay) or _date(self.statistic.decision_date) != day:
                raise ValueError('ashare_eligible_date_requires_matching_statistic')
        elif self.statistic is not None or not self.reason:
            raise ValueError('ashare_excluded_date_requires_reason_and_no_statistic')


def aggregate_information_gate(*, qualification, decision_dates, analysis_mask, rows):
    """Aggregate only the registered h=20,d=0 cell on the full planned grid.

    analysis_mask must come from the frozen uniform maturity/purge/embargo
    contract. Masked and past-only ineligible positions stay in bootstrap
    blocks; an eligible date with an unknown member makes the plan inconclusive.
    Certified adverse bounds are deliberately unsupported, never invented.
    """
    try:
        require_qualified_source(qualification)
    except SourceQualificationError as exc:
        return {'status': 'data_blocked', 'reasons': [str(exc)], 'research_only': True,
                'orders_authorized': False, 'promotion_evidence': False}
    dates = tuple(_date(day) for day in decision_dates)
    if not dates or any(a >= b for a, b in zip(dates, dates[1:])):
        raise ValueError('ashare_gate_calendar_not_strictly_increasing')
    if len(rows) != len(dates) or len(analysis_mask) != len(dates) or any(type(v) is not bool for v in analysis_mask):
        raise ValueError('ashare_gate_full_calendar_shape_mismatch')
    values, annual, segments = [], {}, [[], [], []]
    masked = ineligible = unknown_dates = 0
    unknown_labels = {'top': 0, 'full': 0}
    for day, retain, row in zip(dates, analysis_mask, rows):
        if not isinstance(row, InformationDate) or _date(row.decision_date) != day:
            raise ValueError('ashare_gate_date_registry_mismatch')
        if not dt.date(2015, 1, 1) <= day <= dt.date(2026, 9, 30):
            raise ValueError('ashare_gate_date_outside_declared_range')
        if (row.status == 'masked') != (not retain):
            raise ValueError('ashare_gate_analysis_mask_mismatch')
        value = None
        if row.status == 'masked':
            masked += 1
        elif row.status == 'predecision_ineligible':
            ineligible += 1
        else:
            item = row.statistic
            if item.horizon != 20 or item.delay != 0:
                raise ValueError('ashare_primary_h20_delay0_required')
            if (item.source_manifest_sha256 != qualification.source_manifest_sha256
                    or item.adjustment_semantics_sha256 != qualification.adjustment_semantics_sha256):
                raise SourceQualificationError('ashare_date_statistic_source_or_semantics_binding_mismatch')
            value = item.increment
            for key, count in item.unknown_labels.items():
                unknown_labels[key] += count
            if value is None:
                unknown_dates += 1
            else:
                annual.setdefault(day.year, []).append(value)
                segments[0 if day.year <= 2018 else 1 if day.year <= 2022 else 2].append(value)
        values.append(value)
    interval = calendar_block_mean_interval(values, block_sessions=60, samples=2000, seed=20261009)
    years = {year: {'dates': len(data), 'mean': statistics.fmean(data), 'evaluable': len(data) >= 120}
             for year, data in sorted(annual.items())}
    evaluable = [year for year, data in years.items() if data['evaluable']]
    positive_years = sum(years[year]['mean'] > 0 for year in evaluable)
    required_positive_years = (2 * len(evaluable) + 2) // 3
    best_year = min(years, key=lambda year: (-years[year]['mean'], year)) if years else None
    remaining = [value for day, value in zip(dates, values) if value is not None and day.year != best_year]
    remaining_mean = statistics.fmean(remaining) if remaining else None
    predicates = {
        'minimum_1000_dates': interval['observed_positions'] >= 1000,
        'minimum_250_each_segment': all(len(data) >= 250 for data in segments),
        'minimum_8_evaluable_years': len(evaluable) >= 8,
        'complete_plan_unknowns_resolved': unknown_dates == 0,
        'all_2000_bootstrap_draws_nonempty': interval['nonempty_draws'] == 2000,
        'primary_95pct_CI_lower_gt_zero': interval['mean_95pct_interval_conditional'] is not None
            and interval['mean_95pct_interval_conditional'][0] > 0,
        'annual_positive_fraction_at_least_two_thirds': bool(evaluable) and positive_years >= required_positive_years,
        'drop_best_mean_year_remaining_equal_date_mean_gt_zero': remaining_mean is not None and remaining_mean > 0,
    }
    evidence = ('minimum_1000_dates', 'minimum_250_each_segment', 'minimum_8_evaluable_years',
                'complete_plan_unknowns_resolved', 'all_2000_bootstrap_draws_nonempty')
    if any(not predicates[key] for key in evidence):
        status = 'inconclusive'
    elif all(predicates.values()):
        status = 'information_price_proxy_passed'
    else:
        status = 'information_gate_not_passed'
    return {'status': status, 'reasons': [key for key, passed in predicates.items() if not passed],
            'predicates': predicates, 'primary_horizon': 20, 'primary_delay': 0,
            'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
            'holdout_role': 'discovery', 'independent_OOS_claim': False,
            'calendar_positions': len(dates), 'analysis_mask_retained_dates': sum(analysis_mask),
            'masked_dates': masked, 'predecision_ineligible_dates': ineligible,
            'unknown_eligible_dates': unknown_dates, 'unknown_labels': unknown_labels,
            'annual': years, 'evaluable_years': evaluable, 'positive_evaluable_years': positive_years,
            'best_year_candidate_years': list(years),
            'required_positive_evaluable_years': required_positive_years,
            'segments': [{'dates': len(data), 'mean': statistics.fmean(data) if data else None} for data in segments],
            'best_year_by_annual_mean': best_year,
            'best_year_scope': 'all_years_with_observed_certified_dates_not_only_evaluable_years',
            'remaining_dates_after_best_year': len(remaining), 'remaining_mean_after_best_year': remaining_mean,
            'interval': interval, 'certified_adverse_bounds_supported': False,
            'conditional_summaries_only': unknown_dates > 0,
            'source_manifest_sha256': qualification.source_manifest_sha256,
            'qualification_scope': qualification.qualification_scope,
            'qualification_receipt_sha256': qualification.qualification_receipt_sha256}
