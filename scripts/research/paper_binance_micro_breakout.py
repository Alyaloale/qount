"""Offline paper stream: public-input JSONL -> deterministic checkpoint/journal.

Each row supplies time, minutes, marks, previous, completed (optional), gate
(optional), settlements (optional), and cashflow_usdt (optional, explicit flat
research transfer). Bar objects use t/o/h/l/c/v/q. Funding
history and rules are public JSON inputs. No network, account or order methods.
"""
import argparse
import json
from pathlib import Path

from qount.research.binance_micro_breakout import PaperEngine
from qount.research.small_account_breakout import Bar
from qount.research.small_account_breakout_data import sha, write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=Path('config/binance-micro-regime-breakout-v01.json'))
    p.add_argument('--rules',type=Path,required=True)
    p.add_argument('--funding',type=Path,required=True)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--checkpoint',type=Path)
    p.add_argument('--capital',type=float,default=10)
    p.add_argument('--no-gate',action='store_true')
    p.add_argument('--output',type=Path,required=True)
    a = p.parse_args()
    if a.output.exists(): raise FileExistsError('refuse_overwrite_paper_bundle')
    if a.capital <= 0: raise ValueError('invalid_capital')
    cfg,rules,funding = (json.loads(f.read_text()) for f in (a.config,a.rules,a.funding))
    engine = PaperEngine(cfg,rules,funding,a.capital,not a.no_gate)
    if a.checkpoint:
        saved = json.loads(a.checkpoint.read_text())
        expected = {str(f):sha(f) for f in (a.config,a.rules,a.funding)}
        if saved['source_hashes'] != expected: raise ValueError('checkpoint_contract_mismatch')
        if saved['gated'] != (not a.no_gate): raise ValueError('checkpoint_gate_mismatch')
        engine.restore(saved['state'])
    with a.input.open() as stream:
        for line in stream:
            row = json.loads(line)
            for key in ('minutes','marks','previous'):
                row[key] = {s:Bar(**b) for s,b in row[key].items()}
            engine.step(**row)
    a.output.mkdir(parents=True)
    hashes = {str(f):sha(f) for f in (a.config,a.rules,a.funding)}
    write_json(a.output/'checkpoint.json',{'source_hashes':hashes,'gated':not a.no_gate,
        'state':engine.snapshot(),'research_only':True,'orders_authorized':False})
    write_json(a.output/'journal.json',engine.journal)
    write_json(a.output/'manifest.json',{'source_hashes':hashes,'input_sha256':sha(a.input),
        'parent_checkpoint_sha256':sha(a.checkpoint) if a.checkpoint else None,
        'files':{f.name:sha(f) for f in a.output.iterdir()},
        'public_forward_start':None,'research_only':True,'orders_authorized':False})
    (a.output/'_COMPLETE').write_text(sha(a.output/'manifest.json')+'\n')


if __name__ == '__main__': main()
