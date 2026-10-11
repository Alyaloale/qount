"""Synthetic-only endpoints, unknown accounting and the frozen information gate."""
import dataclasses
import datetime as dt
import math
import statistics
import unittest
from unittest.mock import patch

from qount.research.ashare_information import (
    FrozenMembership, InformationDate, InformationDay, OpenObservation, OpenProxyLabel,
    SourceQualification, SourceQualificationError, StratumInformation, StratumMembership,
    UnknownMember, aggregate_information_gate, freeze_membership, label_endpoints,
    member_label_statistic, open_proxy_label, require_qualified_source,
)
from qount.research import ashare_information
from qount.research.ashare_statistics import decision_mask


def qualified():
    return SourceQualification(True, True, True, 'a' * 64, 'b' * 64, 'c' * 64,
                               'd' * 64, 'vendor_defined_adjusted_price_proxy')


def weekdays(first, last):
    """Fabricated weekday calendar, explicitly not an official holiday calendar."""
    start, end = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    return tuple((start + dt.timedelta(days=i)).strftime('%Y%m%d')
                 for i in range((end-start).days + 1)
                 if (start + dt.timedelta(days=i)).weekday() < 5)


def observation(value, status='observed', **changes):
    return OpenObservation(value, status, changes.get('source_manifest_sha256', 'a' * 64),
                           changes.get('adjustment_semantics_sha256', 'c' * 64))


def known_label(name, value=0.0, horizon=20, delay=0):
    return OpenProxyLabel(name, '20210104', horizon, delay, '20210105', '20210202',
                          'known', value, None, 'a' * 64, 'c' * 64)


def membership_fixture():
    rows = [[{'symbol': f'{s}:{i:03d}', 'M': float(1000-s*100-i), 'A': float(i)}
             for i in range(n)] for s, n in enumerate((21, 21, 21, 20, 20))]
    return freeze_membership(rows, qualification=qualified(), decision_date='20210104')


def statistic(day, value=.01, *, unknown=False, horizon=20, delay=0):
    first = StratumInformation(20, 6, None, (UnknownMember('fixture_unknown', 'missing_exit', True),)) \
        if unknown else StratumInformation(20, 6, value)
    return InformationDay(day, horizon, delay, 'e' * 64,
                          (first,) + (StratumInformation(20, 6, value),) * 4,
                          'a' * 64, 'c' * 64)


def gate_fixture(year_values=None, retained_years=None):
    dates = weekdays('2015-01-01', '2026-09-30')
    boundaries = tuple(next(i for i, day in enumerate(dates) if day >= border)
                       for border in ('20190101', '20230101'))
    mask = decision_mask(len(dates), boundaries)
    rows = []
    for day, retain in zip(dates, mask):
        year = int(day[:4])
        if not retain:
            rows.append(InformationDate(day, 'masked', reason='frozen_maturity_purge_or_embargo'))
        elif retained_years is not None and year not in retained_years:
            rows.append(InformationDate(day, 'predecision_ineligible', reason='synthetic_past_only_eligibility'))
        else:
            rows.append(InformationDate(day, 'eligible', statistic(day, (year_values or {}).get(year, .01))))
    return dates, mask, rows


def evaluate(fixture, qualification=None):
    dates, mask, rows = fixture
    return aggregate_information_gate(qualification=qualification or qualified(),
                                       decision_dates=dates, analysis_mask=mask, rows=rows)


class ExplodingInput:
    def __len__(self):
        raise AssertionError('unqualified input accessed')

    def __iter__(self):
        raise AssertionError('unqualified input accessed')

    def get(self, key):
        raise AssertionError('unqualified input accessed')


class AshareInformationTests(unittest.TestCase):
    def test_exact_registered_endpoints_and_shared_maturity(self):
        for horizon, delay, entry, exit_ in ((20, 0, 11, 31), (20, 1, 12, 32),
                                            (5, 0, 11, 16), (5, 1, 12, 17)):
            item = label_endpoints(10, 40, horizon=horizon, delay=delay)
            self.assertEqual((item.entry_index, item.exit_index), (entry, exit_))
            self.assertTrue(item.uniform_mature)
        self.assertTrue(label_endpoints(17, 40).uniform_mature)
        self.assertFalse(label_endpoints(18, 40, horizon=5).uniform_mature)
        for horizon, delay in ((1, 0), (60, 0), (20, 2), (20, True)):
            with self.assertRaisesRegex(ValueError, 'unregistered'):
                label_endpoints(0, 40, horizon=horizon, delay=delay)

    def test_false_guard_precedes_every_input_access_and_scope_is_bound(self):
        bad = dataclasses.replace(qualified(), adjustment_semantics_verified=False)
        bomb = ExplodingInput()
        with self.assertRaises(SourceQualificationError):
            freeze_membership(bomb, qualification=bad, decision_date='20210104')
        with self.assertRaises(SourceQualificationError):
            open_proxy_label(qualification=bad, sessions=bomb, decision_index=0,
                             security_id='fixture', opens=bomb)
        with self.assertRaises(SourceQualificationError):
            member_label_statistic(bomb, bomb, qualification=bad, decision_date='20210104')
        result = aggregate_information_gate(qualification=bad, decision_dates=bomb,
                                             analysis_mask=bomb, rows=bomb)
        self.assertEqual(result['status'], 'data_blocked')
        for bad in ({'adjustment_semantics_verified': True},
                    dataclasses.replace(qualified(), source_vendor_verified=1),
                    dataclasses.replace(qualified(), source_manifest_sha256='not-a-hash'),
                    dataclasses.replace(qualified(), qualification_scope='cash_total_return')):
            with self.assertRaises(SourceQualificationError):
                require_qualified_source(bad)

    def test_open_labels_use_exact_sessions_and_shift_both_endpoints(self):
        dates = weekdays('2021-01-04', '2021-03-31')
        opens = {('fixture', day): observation(float(i+1)) for i, day in enumerate(dates)}
        for horizon, delay in ((20, 0), (20, 1), (5, 0), (5, 1)):
            label = open_proxy_label(qualification=qualified(), sessions=dates, decision_index=0,
                                     security_id='fixture', opens=opens, horizon=horizon, delay=delay)
            self.assertEqual((label.entry_date, label.exit_date), (dates[1+delay], dates[1+delay+horizon]))
            self.assertAlmostEqual(label.value, (2+delay+horizon)/(2+delay)-1)
        del opens[('fixture', dates[21])]
        label = open_proxy_label(qualification=qualified(), sessions=dates, decision_index=0,
                                 security_id='fixture', opens=opens)
        self.assertEqual((label.status, label.reason), ('unknown', 'exit_endpoint_missing'))
        self.assertIsNone(label.value)  # A later observed open is not substituted.

    def test_immutable_calendar_validation_is_cached_and_invalid_calendars_still_fail(self):
        dates = weekdays('2021-01-04', '2021-03-31')
        opens = {('fixture', day): observation(10.) for day in dates}
        ashare_information._validated_calendar.cache_clear()
        for _ in range(3):
            open_proxy_label(qualification=qualified(), sessions=dates, decision_index=0,
                             security_id='fixture', opens=opens)
        info = ashare_information._validated_calendar.cache_info()
        self.assertEqual((info.misses, info.hits), (1, 2))
        for bad in (dates + (dates[-1],), dates[::-1], ('bad-date',)):
            with self.assertRaises(ValueError):
                open_proxy_label(qualification=qualified(), sessions=bad, decision_index=0,
                                 security_id='fixture', opens=opens)
        with self.assertRaisesRegex(ValueError, 'immutable_calendar_tuple'):
            open_proxy_label(qualification=qualified(), sessions=list(dates), decision_index=0,
                             security_id='fixture', opens=opens)
        previous = ashare_information._validated_calendar.cache_info()
        with self.assertRaises(SourceQualificationError):
            open_proxy_label(qualification=dataclasses.replace(qualified(), adjustment_semantics_verified=False),
                             sessions=ExplodingInput(), decision_index=0, security_id='fixture', opens=ExplodingInput())
        self.assertEqual(ashare_information._validated_calendar.cache_info(), previous)

    def test_zero_return_is_known_and_suspension_or_invalid_open_is_unknown(self):
        dates = weekdays('2021-01-04', '2021-03-31')
        for value, status, expected in ((10., 'observed', 'known'), (10., 'synthetic_suspension', 'unknown'),
                                         (0., 'observed', 'unknown'), (math.nan, 'observed', 'unknown'),
                                         (math.inf, 'observed', 'unknown'), (True, 'observed', 'unknown')):
            opens = {('fixture', dates[1]): observation(10.),
                     ('fixture', dates[21]): observation(value, status)}
            label = open_proxy_label(qualification=qualified(), sessions=dates, decision_index=0,
                                     security_id='fixture', opens=opens)
            self.assertEqual(label.status, expected)
            if expected == 'known':
                self.assertEqual(label.value, 0.)

    def test_immature_cells_do_not_access_opens_and_bindings_cannot_mix(self):
        dates = weekdays('2021-01-04', '2021-03-31')
        label = open_proxy_label(qualification=qualified(), sessions=dates,
                                 decision_index=len(dates)-22, security_id='fixture',
                                 opens=ExplodingInput(), horizon=5)
        self.assertEqual(label.status, 'immature')
        opens = {('fixture', dates[1]): observation(10., source_manifest_sha256='f'*64)}
        with self.assertRaisesRegex(SourceQualificationError, 'binding_mismatch'):
            open_proxy_label(qualification=qualified(), sessions=dates, decision_index=0,
                             security_id='fixture', opens=opens)
        with self.assertRaisesRegex(ValueError, 'strictly_increasing'):
            open_proxy_label(qualification=qualified(), sessions=dates + (dates[-1],),
                             decision_index=0, security_id='fixture', opens={})

    def test_overflow_or_underflow_does_not_create_an_extreme_known_return(self):
        dates = weekdays('2021-01-04', '2021-03-31')
        for entry, exit_ in ((1e-300, 1e300), (1e300, 1e-300)):
            opens = {('fixture', dates[1]): observation(entry), ('fixture', dates[21]): observation(exit_)}
            label = open_proxy_label(qualification=qualified(), sessions=dates, decision_index=0,
                                     security_id='fixture', opens=opens)
            self.assertEqual(label.status, 'unknown')

    def test_full_includes_top_and_strata_have_equal_not_pooled_weight(self):
        membership = membership_fixture()
        labels = {name: known_label(name, float(name in layer.top))
                  for layer in membership.strata for name in layer.full}
        result = member_label_statistic(membership, labels, qualification=qualified(), decision_date='20210104')
        expected = statistics.fmean([2/3, 2/3, 2/3, .7, .7])
        self.assertAlmostEqual(result.increment, expected)
        self.assertNotAlmostEqual(result.increment, 1-33/103)
        self.assertLess(result.increment, 1.)  # top-minus-rest would have been 1.
        self.assertEqual(result.denominators, {'top': 33, 'full': 103})
        self.assertEqual(membership, membership_fixture())

    def test_unknown_top_and_other_member_preserve_members_and_denominators(self):
        membership = membership_fixture()
        labels = {name: known_label(name, 0.) for layer in membership.strata for name in layer.full}
        for missing, expected_top in ((membership.strata[0].top[0], 1), (membership.strata[0].full[0], 0)):
            partial = dict(labels); del partial[missing]
            result = member_label_statistic(membership, partial, qualification=qualified(), decision_date='20210104')
            self.assertIsNone(result.increment)
            self.assertEqual(result.denominators, {'top': 33, 'full': 103})
            self.assertEqual(result.unknown_labels, {'top': expected_top, 'full': 1})
            self.assertEqual(result.strata[0].unknown[0].security_id, missing)
            self.assertEqual(result.membership_sha256, membership.sha256)

    def test_duplicate_members_or_wrong_label_cell_or_binding_fail(self):
        layer = StratumMembership(tuple(f'fixture{i}' for i in range(20)), tuple(f'fixture{i}' for i in range(6)))
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            FrozenMembership((layer,)*5, '20210104', 'a'*64, 'c'*64)
        with self.assertRaisesRegex(ValueError, 'invalid_stratum'):
            StratumMembership(list(layer.full), layer.top)
        membership = membership_fixture()
        name = membership.strata[0].full[0]
        with self.assertRaisesRegex(ValueError, 'membership_decision_date'):
            member_label_statistic(membership, {}, qualification=qualified(), decision_date='20210105')
        with self.assertRaisesRegex(ValueError, 'cell_mismatch'):
            member_label_statistic(membership, {name: known_label(name, horizon=5)},
                                   qualification=qualified(), decision_date='20210104')
        with self.assertRaisesRegex(SourceQualificationError, 'binding_mismatch'):
            member_label_statistic(membership, {name: dataclasses.replace(known_label(name), source_manifest_sha256='f'*64)},
                                   qualification=qualified(), decision_date='20210104')

    def test_complete_positive_fixture_passes_only_the_proxy_information_gate(self):
        fixture = gate_fixture()
        result = evaluate(fixture)
        self.assertEqual(result['status'], 'information_price_proxy_passed')
        self.assertTrue(all(result['predicates'].values()))
        self.assertFalse(result['orders_authorized'])
        self.assertFalse(result['promotion_evidence'])
        self.assertEqual(result['qualification_scope'], 'vendor_defined_adjusted_price_proxy')
        self.assertEqual(result['best_year_by_annual_mean'], 2015)
        self.assertEqual(result['best_year_candidate_years'], list(range(2015, 2027)))
        self.assertEqual(result['remaining_dates_after_best_year'],
                         sum(item['dates'] for year, item in result['annual'].items() if year != 2015))
        self.assertEqual(result['interval']['calendar_positions'], len(fixture[0]))
        self.assertEqual(result['interval']['block_sessions'], 60)
        self.assertEqual(result['interval']['requested_draws'], 2000)
        self.assertEqual(result['interval']['seed'], 20261009)

    def test_unknown_date_never_disappears_or_passes_a_positive_conditional_ci(self):
        dates, mask, rows = gate_fixture()
        index = next(i for i, row in enumerate(rows) if row.status == 'eligible')
        rows[index] = InformationDate(dates[index], 'eligible', statistic(dates[index], unknown=True))
        result = evaluate((dates, mask, rows))
        self.assertEqual(result['status'], 'inconclusive')
        self.assertEqual(result['unknown_eligible_dates'], 1)
        self.assertEqual(result['unknown_labels'], {'top': 1, 'full': 1})
        self.assertEqual(result['calendar_positions'], len(dates))
        self.assertGreater(result['interval']['mean_95pct_interval_conditional'][0], 0)
        self.assertFalse(result['predicates']['complete_plan_unknowns_resolved'])
        self.assertTrue(result['conditional_summaries_only'])

    def test_counts_and_ceil_annual_fraction_use_evaluable_years_only(self):
        retained = (2015, 2016, 2017, 2018, 2019, 2020, 2023, 2024)
        values = {year: (.1 if year in retained[:5] else -.001) for year in retained}
        result = evaluate(gate_fixture(values, retained))
        self.assertEqual(len(result['evaluable_years']), 8)
        self.assertEqual(result['required_positive_evaluable_years'], 6)
        self.assertFalse(result['predicates']['annual_positive_fraction_at_least_two_thirds'])
        self.assertEqual(result['status'], 'information_gate_not_passed')
        too_few = evaluate(gate_fixture(retained_years=retained[:7]))
        self.assertEqual(too_few['status'], 'inconclusive')
        self.assertFalse(too_few['predicates']['minimum_8_evaluable_years'])

    def test_best_year_is_annual_mean_not_total_or_only_evaluable_years(self):
        result = evaluate(gate_fixture({2015: .19, 2026: .2}))
        self.assertGreater(result['annual'][2015]['dates']*.19, result['annual'][2026]['dates']*.2)
        self.assertEqual(result['best_year_by_annual_mean'], 2026)
        dates, mask, rows = gate_fixture()
        kept = 0
        for i, row in enumerate(rows):
            if row.status == 'eligible' and dates[i].startswith('2026'):
                if kept < 5:
                    rows[i] = InformationDate(dates[i], 'eligible', statistic(dates[i], 1.))
                    kept += 1
                else:
                    rows[i] = InformationDate(dates[i], 'predecision_ineligible', reason='synthetic_past_only_eligibility')
        result = evaluate((dates, mask, rows))
        self.assertNotIn(2026, result['evaluable_years'])
        self.assertIn(2026, result['best_year_candidate_years'])
        self.assertEqual(result['best_year_by_annual_mean'], 2026)
        self.assertEqual(result['remaining_dates_after_best_year'],
                         result['interval']['observed_positions']-5)

    def test_zero_means_are_not_positive_and_remaining_mean_is_date_weighted(self):
        result = evaluate(gate_fixture({year: (1. if year == 2015 else 0.) for year in range(2015, 2027)}))
        self.assertEqual(result['positive_evaluable_years'], 1)
        self.assertEqual(result['remaining_mean_after_best_year'], 0.)
        self.assertFalse(result['predicates']['drop_best_mean_year_remaining_equal_date_mean_gt_zero'])
        result = evaluate(gate_fixture({2015: .3, 2026: .2}))
        expected = sum(item['dates']*item['mean'] for year, item in result['annual'].items() if year != 2015) \
            / result['remaining_dates_after_best_year']
        self.assertAlmostEqual(result['remaining_mean_after_best_year'], expected)

    def test_mask_grid_and_diagnostic_cells_cannot_be_silently_substituted(self):
        dates, mask, rows = gate_fixture()
        with self.assertRaisesRegex(ValueError, 'shape_mismatch'):
            evaluate((dates, mask, rows[:-1]))
        wrong_mask = list(mask); wrong_mask[0] = not wrong_mask[0]
        with self.assertRaisesRegex(ValueError, 'mask_mismatch'):
            evaluate((dates, wrong_mask, rows))
        index = next(i for i, row in enumerate(rows) if row.status == 'eligible')
        for horizon, delay in ((5, 0), (20, 1)):
            bad = list(rows)
            bad[index] = InformationDate(dates[index], 'eligible', statistic(dates[index], horizon=horizon, delay=delay))
            with self.assertRaisesRegex(ValueError, 'h20_delay0'):
                evaluate((dates, mask, bad))

    def test_date_and_year_count_thresholds_are_inclusive(self):
        dates, mask, original = gate_fixture()
        for per_year, expected_evaluable in ((119, 0), (120, 12)):
            rows, seen = [], {}
            for day, row in zip(dates, original):
                year = int(day[:4])
                if row.status == 'eligible':
                    seen[year] = seen.get(year, 0) + 1
                    if seen[year] > per_year:
                        row = InformationDate(day, 'predecision_ineligible', reason='synthetic_past_only_eligibility')
                rows.append(row)
            result = evaluate((dates, mask, rows))
            self.assertEqual(len(result['evaluable_years']), expected_evaluable)
        for maximum, expected in ((999, False), (1000, True)):
            rows, seen = [], 0
            for day, row in zip(dates, original):
                if row.status == 'eligible':
                    seen += 1
                    if seen > maximum:
                        row = InformationDate(day, 'predecision_ineligible', reason='synthetic_past_only_eligibility')
                rows.append(row)
            result = evaluate((dates, mask, rows))
            self.assertEqual(result['predicates']['minimum_1000_dates'], expected)

    def test_segment_threshold_and_failed_bootstrap_draw_are_not_waived(self):
        dates, mask, original = gate_fixture()
        for maximum, expected in ((249, False), (250, True)):
            rows, seen = [], 0
            for day, row in zip(dates, original):
                if row.status == 'eligible' and int(day[:4]) <= 2018:
                    seen += 1
                    if seen > maximum:
                        row = InformationDate(day, 'predecision_ineligible', reason='synthetic_past_only_eligibility')
                rows.append(row)
            result = evaluate((dates, mask, rows))
            self.assertEqual(result['predicates']['minimum_250_each_segment'], expected)
        from qount.research.ashare_statistics import calendar_block_mean_interval
        def fewer_draws(values, **kwargs):
            self.assertEqual(kwargs, {'block_sessions': 60, 'samples': 2000, 'seed': 20261009})
            self.assertEqual(len(values), len(dates))
            self.assertEqual(sum(value is None for value in values), sum(not value for value in mask))
            result = calendar_block_mean_interval(values, **kwargs)
            result['nonempty_draws'] = 1999
            return result
        with patch('qount.research.ashare_information.calendar_block_mean_interval', side_effect=fewer_draws):
            result = evaluate((dates, mask, original))
        self.assertEqual(result['status'], 'inconclusive')
        self.assertFalse(result['predicates']['all_2000_bootstrap_draws_nonempty'])


if __name__ == '__main__':
    unittest.main()
