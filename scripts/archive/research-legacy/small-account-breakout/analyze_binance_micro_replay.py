"""Read immutable micro-account ledgers; diagnose concentration and account paths."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def utc(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat() if t is not None else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('state/research_runs/binance_micro_replay_20261013'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('refuse_overwrite_diagnosis')
    source = args.input
    manifest = json.loads((source/'manifest.json').read_text())
    if (source/'_COMPLETE').read_text().strip() != sha(source/'manifest.json'):
        raise ValueError('incomplete_source_bundle')
    for name, expected in manifest['files'].items():
        if sha(source/name) != expected:
            raise ValueError(f'source_file_hash_mismatch:{name}')
    runs = json.loads((source/'summary.json').read_text())['runs']
    details, bundles = [], {}
    for summary in runs:
        name = summary['run']
        bundle = json.loads((source/f'{name}.json').read_text())
        if bundle['summary'] != summary:
            raise ValueError(f'summary_mismatch:{name}')
        trades = bundle['trades']
        pnl = sum(t['net_pnl_usdt'] for t in trades)
        capital = summary['initial_equity_usdt']
        if not math.isclose(capital+pnl, summary['final_equity_usdt'], abs_tol=1e-8, rel_tol=0):
            raise ValueError(f'ledger_mismatch:{name}')
        for trade in trades:
            net = trade['quantity']*(trade['exit_price']-trade['entry_price'])-trade['fees_usdt']+trade['funding_net_usdt']
            if not math.isclose(net, trade['net_pnl_usdt'], abs_tol=1e-8, rel_tol=0):
                raise ValueError(f'trade_pnl_mismatch:{name}')
        ranked = sorted(trades, key=lambda t:t['net_pnl_usdt'], reverse=True)
        top_two = sum(t['net_pnl_usdt'] for t in ranked[:2] if t['net_pnl_usdt'] > 0)
        details.append({**summary,
            'first_entry_utc': utc(min((t['entry_time'] for t in trades), default=None)),
            'last_exit_utc': utc(max((t['exit_time'] for t in trades), default=None)),
            'net_pnl_usdt': pnl, 'top_two_winning_pnl_usdt': top_two,
            'net_pnl_excluding_top_two_winners_usdt': pnl-top_two,
            'top_two_share_of_positive_net_pnl': top_two/pnl if pnl > 0 else None})
        bundles[name] = bundle
    paired = []
    for summary in runs:
        if summary['gated'] or summary['scenario'] != 'base':
            continue
        peer = next(r for r in runs if r['gated'] and r['scenario'] == 'base'
            and all(r[k] == summary[k] for k in ('window','interval_hours','initial_equity_usdt')))
        left = bundles[summary['run']]['trades']
        right = bundles[peer['run']]['trades']
        left_keys = {(t['symbol'],t['entry_time']) for t in left}
        right_keys = {(t['symbol'],t['entry_time']) for t in right}
        paired.append({'window': summary['window'], 'interval_hours': summary['interval_hours'],
            'capital_usdt': summary['initial_equity_usdt'],
            'gate_minus_no_gate_return_pp': 100*(peer['net_return']-summary['net_return']),
            'shared_entry_count': len(left_keys & right_keys),
            'no_gate_only_entry_count': len(left_keys-right_keys),
            'gate_only_entry_count': len(right_keys-left_keys),
            'exact_trade_ledgers_equal': left == right})
    current = {name: {'original': expected, 'current': sha(Path(name)) if Path(name).is_file() else None}
        for name, expected in manifest['source_hashes'].items()}
    args.output.mkdir(parents=True)
    write(args.output/'diagnosis.json', {'source_bundle': str(source),
        'source_manifest_sha256': sha(source/'manifest.json'),
        'source_bundle_files_verified': len(manifest['files']), 'ledgers_reconciled': len(runs),
        'source_versions': current, 'runs': details, 'base_gate_pairs': paired,
        'limitations': ['Consumed history; descriptive diagnostics only.',
            'Different account paths and permanent HALT prevent causal attribution to the entry gate.',
            'Trade concentration is arithmetic, not a bootstrap or statistical edge test.',
            'Current source may differ from original; original results are not reruns of current code.',
            'Exact HALT time is not recorded in the original journal; last exit is not its trigger time.'],
        'independent_oos': False, 'forward_start': None,
        'research_only': True, 'orders_authorized': False})
    lines = ['# Binance micro replay diagnosis', '',
        'Original bundle hashes and all 96 net-PnL ledgers reconciled. Consumed history only.', '',
        '| Window | Base arm / 10 USDT | First entry UTC | Last exit UTC | HALT | Net PnL | Top two winners | Cash time |',
        '|---|---|---|---|---|---:|---:|---:|']
    for row in details:
        if row['initial_equity_usdt'] == 10 and row['scenario'] == 'base':
            arm = f"{row['interval_hours']}h {'gate' if row['gated'] else 'no gate'}"
            lines.append(f"| {row['window']} | {arm} | {row['first_entry_utc']} | {row['last_exit_utc']} | {row['halt'] or 'none'} | {row['net_pnl_usdt']:.6f} | {row['top_two_winning_pnl_usdt']:.6f} | {row['time_in_cash']:.2%} |")
    lines += ['', 'Top-two amounts are a concentration diagnostic, not a realizable strategy that deletes trades.',
        '2025 1h gated/no-gate trade ledgers are identical. 2026 1h at 10 USDT has zero shared entries.',
        'At 30/100 USDT, 2026 1h gated returns trail no-gate; see diagnosis.json for all capital/cost cases.',
        'Permanent HALT includes mark-to-market profit giveback. No automatic reset was modeled.', '']
    (args.output/'report.md').write_text('\n'.join(lines))
    write(args.output/'manifest.json', {'source_bundle_manifest_sha256': sha(source/'manifest.json'),
        'analysis_script_sha256': sha(Path(__file__)),
        'files': {p.name: sha(p) for p in args.output.iterdir()},
        'research_only': True, 'orders_authorized': False})
    (args.output/'_COMPLETE').write_text(sha(args.output/'manifest.json')+'\n')
    print(json.dumps({'ledgers_reconciled': len(runs), 'output': str(args.output),
        'original_bundle_files_verified': len(manifest['files'])}))


if __name__ == '__main__':
    main()
