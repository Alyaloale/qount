"""One offline discovery comparison; no service, credential or account access."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from qount.research import c60_execution_control as execution
from qount.research.dual_engine_execution_study import load_cache, read_opens, summary
from qount.research.dual_engine_optimization import build_crypto_assets


RULES = {
    'start': '2021-01-01', 'end': '2026-08-31',
    'btc_distance': 'completed_close_div_SMA50_minus1',
    'upper_bounds': [-.02, 0., .02], 'exposures': [0., .35, .70, 1.],
    'own_gate': 'unchanged_strict_close_gt_SMA20', 'PAXG': 'BTC_gate_exempt_unchanged',
    'deadband': .15, 'deadband_metric': 'full_portfolio_L1_vs_actual_pretrade_weights',
    'deadband_clock': 'after_open_mark_before_fee_sizing_no_trade_when_L1_le15pct',
    'small_exits': 'also_suppressed_no_safety_override_new_rule',
    'vol_cap': 'unchanged_60pct_computed_on_scaled_weights',
    'cells': [[25, 0], [25, 1], [50, 0], [50, 1]],
    'variants': ['binary', 'gradient_only', 'gradient_deadband'],
    'selection': 'none_report_all_no_parameter_rescue',
    'historical_gate': 'all4_cells_turnover_lower_CAGR_ge_baseline_MDD_no_worse',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def run(contract_path, out, repo):
    contract_path, out, repo = map(Path, (contract_path, out, repo))
    c = json.loads(contract_path.read_text())
    if (c.get('rules') != RULES or c.get('research_only') is not True
            or c.get('orders_authorized') is not False or c.get('promotion_evidence') is not False):
        raise ValueError('gradient_contract_mismatch')
    allowed = Path('/mnt/e/qount_data/qount/artifacts/dual_engine')
    if sys.platform != 'linux' or not os.path.ismount('/mnt/e') or not out.resolve().is_relative_to(allowed):
        raise ValueError('gradient_requires_WSL_E')
    if out.exists():
        raise ValueError('gradient_fresh_output_required')
    for name, expected in c['implementation_sha256'].items():
        p = (repo/name).resolve()
        if not p.is_relative_to(repo.resolve()) or sha(p) != expected:
            raise ValueError('gradient_code_changed:'+name)
    # Inputs and code are checked before reading any new strategy returns.
    raw, cache_hashes = load_cache(Path(c['pit_cache']))
    opens, open_files = read_opens(Path(c['open_root']))
    original = Path(c['prior_input_audit'])
    if sha(original) != c['prior_input_audit_sha256']:
        raise ValueError('gradient_prior_audit_changed')
    audit = json.loads(original.read_text())
    if cache_hashes != audit['pit_cache_sha256'] or open_files != audit['open_files_sha256']:
        raise ValueError('gradient_original_inputs_changed')
    supplemental = []
    for spec in c.get('supplemental_open_roots', []):
        root = Path(spec['root'])
        if sha(root/'manifest.json') != spec['manifest_sha256']:
            raise ValueError('gradient_supplemental_manifest_changed')
        extra, files = read_opens(root)
        metadata = json.loads((root/'manifest.json').read_text())
        if any(cache_hashes.get(name) != value for name, value in metadata['cache_sha256'].items()):
            raise ValueError('gradient_supplemental_cache_lineage_changed')
        for symbol, values in extra.items():
            saved = opens.setdefault(symbol, {})
            for day, price in values.items():
                if day in saved and saved[day] != price:
                    raise ValueError('gradient_open_sources_disagree')
                saved[day] = price
        supplemental.append({'root': str(root), 'files': files, 'manifest_sha256': spec['manifest_sha256']})
    axis, assets = build_crypto_assets(raw, end=RULES['end'])
    binary, members = execution.warm_targets(axis, assets)
    gradient, gradient_members = execution.warm_targets(axis, assets, btc_gradient=True)
    if members != gradient_members:
        raise ValueError('gradient_candidate_selection_changed')
    out.mkdir(parents=True)
    write(out/'contract.json', c)
    write(out/'input-audit.json', {'cache_sha256': cache_hashes, 'open_files': open_files,
                                  'supplemental_opens': supplemental,
                                  'prior_input_audit_sha256': sha(original)})
    results, gates = {}, {}
    for cost, delay in RULES['cells']:
        cell = f'c{cost}-d{delay}'
        results[cell] = {}
        for variant in RULES['variants']:
            targets = binary if variant == 'binary' else gradient
            # Check each newly requested opening and next held mark, including
            # targets introduced by a partly open BTC gate. Never fetch silently.
            for signal, weights in targets.items():
                t = signal+1+delay
                if t >= len(axis.dates) or axis.dates[t] < RULES['start']:
                    continue
                for k in weights:
                    for mark in (t, t+1):
                        if mark < len(axis.dates) and assets[k].has(mark):
                            if axis.dates[mark] not in opens.get(assets[k].symbol, {}):
                                raise ValueError('gradient_open_coverage_missing:'+assets[k].symbol+':'+axis.dates[mark])
            ledger = execution.replay_crypto_open(axis, assets, opens, targets,
                start=RULES['start'], cost_bps=cost, delay=delay,
                rebalance_deadband=.15 if variant == 'gradient_deadband' else 0.)
            for row in ledger['records']:
                t = axis.index(row['date'])
                if any(assets[k].has(t) for k in row['overnight_missing_marks']):
                    raise ValueError('gradient_held_open_coverage_missing:'+row['date'])
            write(out/f'{cell}-{variant}.json', ledger)
            metrics = summary(ledger, 365)
            ytd = {'records': [r for r in ledger['records'] if r['date'] >= '2026-01-01']}
            results[cell][variant] = {'full': metrics, 'ytd_2026': summary(ytd, 365),
                'suppressed_days': sum(r['deadband_suppressed'] for r in ledger['records']),
                'missing_marks': sum(len(r['missing_marks']) for r in ledger['records'])}
        a, b = (results[cell][name]['full'] for name in ('gradient_deadband', 'binary'))
        gates[cell] = {'turnover_lower': a['annual_turnover'] < b['annual_turnover'],
                       'cagr_not_lower': a['cagr'] >= b['cagr'],
                       'drawdown_not_worse': a['max_drawdown'] >= b['max_drawdown']}
    passed = all(all(v.values()) for v in gates.values())
    result = {'research_only': True, 'orders_authorized': False, 'promotion_evidence': False,
              'status': 'historical_screen_pass' if passed else 'historical_screen_fail_preserved',
              'data_role': 'consumed_historical_discovery_pool', 'independent_OOS': False,
              'new_primary_rules': 1, 'new_diagnostic_rules': 1, 'curve_exposures': 12,
              'parameter_searches': 0, 'global_trial_count': None, 'DSR_PBO': 'not_calculated',
              'gates': gates, 'results': results, 'contract_sha256': sha(contract_path)}
    write(out/'summary.json', result)
    write(out/'manifest.json', {'files': {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}})
    return result
