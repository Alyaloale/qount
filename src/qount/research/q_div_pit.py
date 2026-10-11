"""Indexed historical financial sections, with explicit snapshot/PIT separation.

Vendor dates are useful clocks but never proof of a historical public vintage.
This index preserves revisions and ambiguities instead of selecting update_flag.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
import copy
import hashlib
import json

from qount.research.q_div import DataUnknown, date, fundamentals

FIELDS = {
    'income': ('n_income_attr_p',),
    'cashflow': ('n_cashflow_act',),
    'balancesheet': ('total_hldr_eqy_exc_min_int', 'total_liab', 'total_assets'),
}


def row_hash(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


class FinancialVersionIndex:
    """Immutable in-memory index over (API, symbol, period, publication date).

    A row can have a separate externally reconciled publication evidence entry.
    An evidence entry binds its full row hash, original document hash and public
    date; a boolean 'certified' flag alone is deliberately insufficient. Coverage
    of the full historical universe remains a separate prerequisite.
    """
    def __init__(self, sources, evidence=()):
        proofs = {}
        for proof in evidence:
            key = proof['row_sha256']
            if key in proofs:
                raise ValueError('duplicate_publication_evidence')
            date(proof['public_date'])
            for name in ('row_sha256', 'document_sha256'):
                value = proof.get(name)
                if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                    raise ValueError('invalid_publication_evidence_hash')
            if not proof.get('document_ref') or proof.get('reconciliation') != 'exact_fields_and_period':
                raise ValueError('publication_evidence_not_reconciled')
            proofs[key] = copy.deepcopy(proof)
        groups = defaultdict(lambda: defaultdict(list))
        self.symbols = set()
        self.inventory = defaultdict(int)
        self.rejected = []
        used_proofs = set()
        for api, rows in sources:
            if api not in FIELDS:
                continue
            for source_row in rows:
                row = copy.deepcopy(source_row)
                if str(row.get('report_type')) != '1':
                    self.inventory['non_consolidated_rows_excluded'] += 1
                    continue
                try:
                    symbol, period = row['ts_code'], row['end_date']
                    date(period)
                    dates = [row[k] for k in ('ann_date','f_ann_date') if row.get(k)]
                    if not dates:
                        raise DataUnknown('missing_publication_date')
                    for day in dates:
                        date(day)
                    announced = max(dates)
                    if not isinstance(symbol, str) or not symbol:
                        raise DataUnknown('missing_symbol')
                except (KeyError, DataUnknown) as exc:
                    self.rejected.append({'api': api, 'row_sha256': row_hash(row), 'reason': str(exc)})
                    continue
                key = row_hash(row)
                proof = proofs.get(key)
                if proof:
                    used_proofs.add(key)
                    if proof['public_date'] < announced:
                        raise ValueError('publication_evidence_precedes_vendor_clock')
                available = proof['public_date'] if proof else announced
                groups[(api, symbol, period)][available].append((row, key, proof))
                self.symbols.add(symbol)
                self.inventory['consolidated_rows'] += 1
        if set(proofs) != used_proofs:
            raise ValueError('unmatched_publication_evidence')
        self._groups = {}
        by_symbol = defaultdict(list)
        self.conflicts = []
        for key, versions in sorted(groups.items()):
            dates = tuple(sorted(versions))
            self._groups[key] = (dates, tuple(tuple(versions[d]) for d in dates))
            by_symbol[key[1]].append((key,self._groups[key]))
            for day in dates:
                candidates = versions[day]
                signatures = {self._signature(key[0], r) for r, _, _ in candidates}
                self.inventory['dated_groups'] += 1
                self.inventory['multiple_record_groups'] += len(candidates) > 1
                if len(signatures) != 1:
                    self.conflicts.append({'api': key[0], 'symbol': key[1], 'period': key[2],
                                           'public_date': day, 'row_sha256': sorted(h for _, h, _ in candidates)})
        self.inventory = dict(self.inventory)
        self._by_symbol = {symbol:tuple(values) for symbol,values in by_symbol.items()}

    @staticmethod
    def _signature(api, row):
        # Numeric equality preserves vendor values; missing stays distinct from 0.
        return tuple(row.get(k) for k in FIELDS[api])

    def section(self, symbol, asof, *, require_public_evidence=False):
        date(asof)
        result = {api: [] for api in FIELDS}
        lineage = []
        for (api, code, period), (days, groups) in self._by_symbol.get(symbol, ()):
            if period > asof:
                continue
            offset = bisect_left(days, asof)-1  # same-day publication is not usable
            if offset < 0:
                continue
            candidates = groups[offset]
            if len({self._signature(api, r) for r, _, _ in candidates}) != 1:
                raise DataUnknown('ambiguous_same_date_financial_revision:'+api+':'+period)
            # Prefer a reconciled copy of identical values, then stable full hash;
            # update_flag never ranks a version, nor resolves conflicting values.
            row, key, proof = min(candidates, key=lambda x: (x[2] is None, x[1]))
            if require_public_evidence and proof is None:
                raise DataUnknown('historical_public_version_evidence_missing:'+api+':'+period)
            result[api].append(copy.deepcopy(row))
            lineage.append({'api': api, 'period': period, 'available_date': days[offset],
                            'row_sha256': key, 'publication_evidence': copy.deepcopy(proof)})
        return result, lineage

    def quality(self, symbol, asof, *, require_public_evidence=False):
        section, lineage = self.section(symbol, asof, require_public_evidence=require_public_evidence)
        result = fundamentals(section['income'], section['cashflow'], section['balancesheet'], asof)
        return {'symbol': symbol, 'asof': asof, 'quality': result, 'lineage': lineage,
                'historical_PIT_certified': False,
                'status': 'public_rows_coverage_pending' if require_public_evidence else 'conditional_vendor_snapshot'}

    def rolling(self, review_days, symbols=None, *, require_public_evidence=False):
        """Yield dated sections; caller supplies actual exchange review dates."""
        days = list(review_days)
        if days != sorted(set(days)):
            raise ValueError('review_dates_must_be_unique_and_sorted')
        for day in days:
            date(day)
            for symbol in sorted(self.symbols if symbols is None else symbols):
                try:
                    yield self.quality(symbol, day, require_public_evidence=require_public_evidence)
                except DataUnknown as exc:
                    yield {'symbol': symbol, 'asof': day, 'status': 'unknown', 'reason': str(exc),
                           'historical_PIT_certified': False}
