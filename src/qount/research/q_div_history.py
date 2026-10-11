"""WSL-only audit of existing financial versions, without a return experiment."""
from __future__ import annotations

from collections import Counter
import json
import os
import sys
from pathlib import Path

from qount.research.q_div_data import bundle, digest, fresh_output, write
from qount.research.q_div_pit import FinancialVersionIndex


def audit(financial_root, out, review_days):
    if sys.platform != 'linux' or not os.path.ismount('/mnt/e'):
        raise ValueError('history_audit_requires_WSL_E')
    rows, fingerprint = bundle(financial_root)
    index = FinancialVersionIndex((spec['api_name'], values) for spec, values in rows)
    days = json.loads(Path(review_days).read_text())
    results = list(index.rolling(days))
    out = fresh_output(out)
    write(out/'input-manifest.json', fingerprint)
    write(out/'review-days.json', days)
    write(out/'conflicts.json', index.conflicts)
    write(out/'rejected-rows.json', index.rejected)
    write(out/'sections.json', results)
    counts = Counter(r['status'] for r in results)
    reasons = Counter(r.get('reason') for r in results if r['status'] == 'unknown')
    summary = {'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
        'status': 'historical_financial_evidence_insufficient_no_returns',
        'source_scope': 'prior_current_technical_shortlist_not_historical_universe',
        'securities': len(index.symbols), 'review_days': len(days), 'sections': len(results),
        'inventory': index.inventory, 'same_date_conflicts': len(index.conflicts),
        'rejected_rows': len(index.rejected), 'section_status': dict(counts), 'unknown_reasons': dict(reasons),
        'historical_PIT_certified': False, 'historical_backtest_run': False,
        'economic_experiments_run': 0, 'parameter_searches': 0,
        'blocking_evidence': ['historical_universe_wide_public_version_coverage',
            'PIT_SW1_identity_ST_delisting', 'record_ex_pay_ordinary_special_share_bridges',
            'dated_fee_tax_execution_and_total_return_benchmarks'],
        'review_days_sha256': digest(review_days),
        'implementation_sha256': {name: digest(Path(__file__).with_name(name))
                                  for name in ('q_div_pit.py','q_div_history.py','q_div_cash.py')}}
    write(out/'summary.json', summary)
    write(out/'manifest.json', {'files': {p.name: digest(p) for p in sorted(out.iterdir()) if p.is_file()}})
    return summary
