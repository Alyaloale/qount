"""Synthetic source adapters and fail-closed integration boundaries."""
import datetime as dt
import gzip
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.research.ashare_information import SourceQualificationError
from qount.research import ashare_information_run as runner


def fixture(n=310):
    start = dt.date(2020, 1, 1)
    sessions = tuple((start + dt.timedelta(days=i)).strftime('%Y%m%d') for i in range(n))
    rows = [dict(ts_code='fixture', trade_date=day, open=10+i, high=11+i,
                 low=9+i, close=10+i, amount=100+i, adj_factor=2,
                 adj_open=20+2*i, adj_high=22+2*i, adj_low=18+2*i, adj_close=20+2*i)
            for i, day in enumerate(sessions)]
    return sessions, rows


class InformationRunTests(unittest.TestCase):
    def test_features_use_only_past_252_observations_and_exact_65_sessions(self):
        dates, rows = fixture()
        item = runner._rows_to_series('fixture', rows, dates, source_kind='original_zip')
        self.assertEqual(item.window_status[250], 1)
        self.assertEqual(item.window_status[251], 0)
        j = 270
        self.assertAlmostEqual(item.M[j], math.log((10+j-5)/(10+j-60)))
        self.assertAlmostEqual(item.A[j], math.log((100+j-2)/(100+j-34.5)))
        changed = [dict(row) for row in rows]
        for row in changed[j+1:]:
            row.update(adj_close=1e6, amount=1e6)
        other = runner._rows_to_series('fixture', changed, dates, source_kind='original_zip')
        self.assertEqual((item.M[j], item.A[j], item.window_status[j]),
                         (other.M[j], other.A[j], other.window_status[j]))

    def test_missing_session_is_not_compacted_or_future_completed(self):
        dates, rows = fixture(340)
        del rows[260]
        item = runner._rows_to_series('fixture', rows, dates, source_kind='original_zip')
        self.assertEqual(item.open_status[260], 0)
        self.assertTrue(all(item.window_status[j] == 2 for j in range(260, 325)))
        self.assertEqual(item.window_status[325], 0)
        self.assertEqual(item.history[260], item.history[259])

    def test_retired_factors_are_same_date_only_and_constant_anchor_cancels(self):
        dates, rows = fixture()
        factors = {day: 3.0 for day in dates}
        item = runner._rows_to_series('fixture', rows, dates, source_kind='tushare_retired', factors=factors)
        self.assertEqual(item.opens[270], rows[270]['open']*3)
        self.assertAlmostEqual(item.M[270], math.log(rows[265]['close']/rows[210]['close']))
        del factors[dates[260]]
        other = runner._rows_to_series('fixture', rows, dates, source_kind='tushare_retired', factors=factors)
        self.assertEqual(other.open_status[260], 0)
        self.assertEqual(other.window_status[270], 2)

    def test_zero_and_missing_amount_are_unknown_open_and_ineligible_window(self):
        dates, rows = fixture()
        rows[260]['amount'] = 0
        rows[261]['amount'] = None
        item = runner._rows_to_series('fixture', rows, dates, source_kind='original_zip')
        self.assertEqual((item.open_status[260], item.open_status[261]), (2, 0))
        self.assertEqual(item.window_status[270], 2)

    def test_invalid_raw_ohlc_envelope_cannot_supply_maturity_or_complete_window(self):
        dates, rows = fixture()
        rows[260]['high'] = rows[260]['low']
        item = runner._rows_to_series('fixture', rows, dates, source_kind='original_zip')
        self.assertEqual(item.history[260], item.history[259])
        self.assertEqual(item.window_status[270], 2)

    def test_pre_calendar_observations_only_supply_maturity(self):
        dates, rows = fixture(340)
        item = runner._rows_to_series('fixture', rows, dates[250:], source_kind='original_zip')
        self.assertEqual(item.pre_calendar_valid_observations, 250)
        self.assertEqual(item.window_status[63], 2)
        self.assertEqual(item.window_status[64], 0)

    def test_invalid_identity_duplicate_and_noncalendar_date_fail(self):
        dates, rows = fixture()
        for changes in (dict(ts_code='other'), dict(trade_date=dates[0]), dict(trade_date='20209999')):
            bad = [dict(row) for row in rows]
            bad[1].update(changes)
            with self.assertRaises(ValueError):
                runner._rows_to_series('fixture', bad, dates, source_kind='original_zip')

    def test_rank_ic_average_ties_and_constant_undefined(self):
        self.assertEqual(runner._ranks([2, 1, 2]), [1.5, 0., 1.5])
        self.assertAlmostEqual(runner._rank_ic([1, 2, 3], [3, 2, 1]), -1.)
        self.assertIsNone(runner._rank_ic([1, 1], [2, 3]))
        self.assertIsNone(runner._rank_ic([1], [2]))

    def test_response_binds_uncompressed_bytes_and_only_daily_has_6000_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            body = {'code': 0, 'data': {'fields': ['ts_code'], 'items': [['fixture']]*6000, 'has_more': False}}
            raw = json.dumps(body).encode()
            (root/'raw.gz').write_bytes(gzip.compress(raw))
            request = {'file': 'raw.gz', 'rows': 6000, 'api_name': 'adj_factor',
                       'raw_response_sha256': hashlib.sha256(raw).hexdigest(), 'params': {'ts_code': 'fixture'}}
            self.assertEqual(len(runner._response_rows(root, request)), 6000)
            with self.assertRaisesRegex(ValueError, 'pagination'):
                runner._response_rows(root, {**request, 'api_name': 'daily'})
            with self.assertRaisesRegex(ValueError, 'raw_hash'):
                runner._response_rows(root, {**request, 'raw_response_sha256': '0'*64})

    def test_false_source_receipt_fails_before_raw_data_or_source_manifest_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def save(name, value):
                p = root/name
                p.write_text(json.dumps(value))
                return hashlib.sha256(p.read_bytes()).hexdigest()
            proposal = save('proposal.json', {'holdout_role': 'discovery'})
            stage = save('stage.json', {'original_proposal_sha256': proposal})
            old = save('old.json', {})
            summary = save('summary.json', {'source_vendor_verified': True,
                'adjustment_semantics_verified_for_information_proxy': False,
                'independent_calendar_verified': True, 'source_manifest_sha256': 'a'*64,
                'calendar_review_sha256': 'b'*64, 'adjustment_semantics_review_sha256': 'c'*64,
                'adjustment_semantics_scope': 'vendor_defined_adjusted_price_proxy'})
            manifest = save('manifest.json', {'summary.json': summary})
            contract = {'phase': 'ashare_information_price_proxy', 'research_only': True,
                'orders_authorized': False, 'promotion_evidence': False, 'holdout_role': 'discovery',
                'authorization': {'information_study_run': True, 'automatic_restart': False,
                                  'production_or_account_access': False}, 'workers': 4,
                'inputs': {key: {'path': str(root/name), 'sha256': digest}
                    for key, name, digest in [('proposal','proposal.json',proposal),
                        ('stage','stage.json',stage), ('original_qualification','old.json',old)]},
                'qualification_manifest_sha256': manifest, 'qualification_summary_sha256': summary}
            save('run.json', contract)
            with patch.object(runner, 'verify_manifest', side_effect=AssertionError('raw/source touched')):
                with self.assertRaises(SourceQualificationError):
                    runner._preflight(root/'run.json', root, root/'nonexistent-source', root/'nonexistent-calendar')


if __name__ == '__main__':
    unittest.main()
