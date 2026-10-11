"""Immutable public-source qualification and WSL Q-DIV dated snapshot runner."""
from __future__ import annotations

import collections
import gzip
import hashlib
import json
import math
import os
import sys
from pathlib import Path

from qount.research import q_div as strategy

ROOT = Path(__file__).resolve().parents[3]
DATASETS = Path('/mnt/e/qount_data/qount/datasets/equity_selection')
CAPS = {'index_daily': 6000, 'shibor': 2000, 'daily_basic': 6000, 'stock_st': 1000,
        'income': 5000, 'cashflow': 5000, 'balancesheet': 5000, 'dividend': 2000}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def bundle(root):
    """Replay declared hashes/schema/caps; never infer completeness from count alone."""
    root = Path(root)
    if not root.resolve().is_relative_to(DATASETS):
        raise ValueError('public_source_outside_E')
    acquisition = json.loads((root/'acquisition.json').read_text())
    contract = json.loads((root/'contract.json').read_text())
    if (acquisition.get('status') != 'completed' or acquisition['completed_requests'] != len(contract['requests'])
            or acquisition['contract_sha256'] != digest(root/'contract.json')
            or acquisition.get('credentials_persisted_or_exported') is not False):
        raise ValueError('incomplete_public_acquisition')
    results, fingerprints = [], {'contract.json': digest(root/'contract.json'),
                                'acquisition.json': digest(root/'acquisition.json')}
    if len(acquisition['responses']) != len(contract['requests']):
        raise ValueError('response_inventory_mismatch')
    for spec, response in zip(contract['requests'], acquisition['responses'], strict=True):
        if (any(response.get(k) != spec.get(k) for k in ('id','api_name','params','role'))
                or response.get('fields') != spec['fields'].split(',')):
            raise ValueError('request_receipt_mismatch')
        path = (root/response['file']).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('response_path_escape')
        raw = gzip.decompress(path.read_bytes())
        if hashlib.sha256(raw).hexdigest() != response['raw_response_sha256']:
            raise ValueError('raw_response_hash_mismatch')
        value = json.loads(raw); data = value.get('data', {})
        api, fields = spec['api_name'], spec['fields'].split(',')
        if (value.get('code') != 0 or data.get('has_more') is not False
                or data.get('fields') != fields or not isinstance(data.get('items'), list)
                or len(data['items']) >= CAPS[api]):
            raise ValueError('source_schema_paging_or_documented_cap:' + api)
        if len(data['items']) != response['rows'] or any(len(r) != len(fields) for r in data['items']):
            raise ValueError('source_response_dimensions')
        rows = [dict(zip(fields,r,strict=True)) for r in data['items']]
        for row in rows:
            p = spec['params']
            if p.get('ts_code') and row.get('ts_code') != p['ts_code']:
                raise ValueError('source_symbol_mismatch')
            if p.get('trade_date') and row.get('trade_date') != p['trade_date']:
                raise ValueError('source_date_mismatch')
        results.append((spec, rows)); fingerprints[response['file']] = digest(path)
    return results, {'root': str(root), 'files': fingerprints}


def validate_contract(path):
    c = json.loads(Path(path).read_text())
    if (c.get('rules') != strategy.RULES or c.get('gate') != strategy.GATE
            or c.get('research_only') is not True or c.get('orders_authorized') is not False
            or c.get('promotion_evidence') is not False):
        raise ValueError('q_div_contract_mismatch')
    if sys.platform != 'linux' or not os.path.ismount('/mnt/e'):
        raise ValueError('q_div_compute_requires_WSL_E')
    for name, sha in c['implementation_sha256'].items():
        p = (ROOT/name).resolve()
        if not p.is_relative_to(ROOT) or digest(p) != sha:
            raise ValueError('q_div_frozen_code_mismatch:' + name)
    return c


def fresh_output(out):
    out = Path(out)
    if out.exists() or not out.resolve().is_relative_to(Path('/mnt/e/qount_data/qount/artifacts/equity_selection')):
        raise ValueError('fresh_E_research_output_required')
    out.mkdir(parents=True)
    return out


def price_screen(contract_path, out):
    from qount.research.ashare_backtest_data import load_panel
    c = validate_contract(contract_path)
    out = fresh_output(out)
    bundles, sources = [], []
    for source in c['snapshot_public_sources']:
        if digest(Path(source['root'])/'contract.json') != source['contract_sha256']:
            raise ValueError('snapshot_source_contract_hash_mismatch')
        rows, fingerprint = bundle(source['root']); bundles += rows; sources.append(fingerprint)
    sessions, panel, metadata, diagnostics = load_panel(c)
    index, rates, basic, st = {}, {}, {}, None
    for spec, rows in bundles:
        api = spec['api_name']
        if api == 'index_daily':
            for r in rows:
                strategy.date(r['trade_date'])
                if r['trade_date'] in index:
                    raise ValueError('duplicate_index_date')
                index[r['trade_date']] = strategy.number(r['close'])/strategy.number(r['pre_close'])-1
        elif api == 'shibor':
            for r in rows:
                strategy.date(r['date'])
                if r['date'] in rates:
                    raise ValueError('duplicate_rate_date')
                rates[r['date']] = strategy.number(r['on'])/100/252
        elif api == 'daily_basic':
            for r in rows:
                key = (r['ts_code'],r['trade_date'])
                if key in basic:
                    raise ValueError('duplicate_daily_basic_key')
                basic[key] = r
        elif api == 'stock_st' and spec['params']['trade_date'] == sessions[-1]:
            if st is not None:
                raise ValueError('duplicate_ST_source')
            st = {r['ts_code'] for r in rows}
    if st is None:
        raise ValueError('dated_ST_inventory_required')
    j, asof = len(sessions)-1, sessions[-1]
    market = [index[d] for d in sessions[-120:]]
    rate = [rates[d] for d in sessions[-121:-1]]
    features, failures = {}, collections.Counter()
    for code,s in sorted(panel.items()):
        try:
            features[code] = strategy.price_features(s,j)
        except strategy.DataUnknown as exc:
            failures[str(exc)] += 1
    liquid = strategy.liquid_codes(features)
    turnover, unknown_turnover = {}, []
    for code in liquid:
        if code in st:
            continue
        try:
            values = [strategy.number(basic[(code,d)]['turnover_rate']) for d in sessions[-20:]]
            if any(v < 0 for v in values):
                raise strategy.DataUnknown('negative_turnover')
            turnover[code] = sum(values)/20
        except (KeyError, strategy.DataUnknown):
            unknown_turnover.append(code)
    low_turnover = strategy.low_turnover_codes(turnover)
    rows = []
    for code in low_turnover:
        f, s = features[code], panel[code]
        if not f['trend_pass'] or not f['entry_pass']:
            continue
        try:
            ret = [s.adj_close[k]/s.adj_close[k-1]-1 for k in range(j-119,j+1)]
            residual = strategy.ivol(ret,market,rate)
            mv = strategy.number(basic[(code,asof)]['total_mv'])
            if mv <= 0:
                raise strategy.DataUnknown('nonpositive_market_value')
        except (KeyError, strategy.DataUnknown) as exc:
            failures[str(exc)] += 1; continue
        rows.append({'symbol': code, 'name': metadata.get(code,{}).get('name'),
                     'industry': metadata.get(code,{}).get('industry') or '__unclassified__',
                     'total_mv_10k': mv, 'turnover20_percent': turnover[code], **f, **residual})
    rows.sort(key=lambda r: (r['IVOL'],r['symbol']))
    shortlist = rows[:strategy.RULES['snapshot_shortlist_limit']]
    summary = {'research_only': True,'orders_authorized': False,'promotion_evidence': False,
               'status': 'dated_technical_snapshot_fundamentals_pending','price_cutoff':asof,
               'contract_sha256':digest(contract_path),'source':diagnostics,
               'mature_price_pool':len(features),'liquid_pool':len(liquid),
               'dated_ST_excluded':sum(code in st for code in liquid),
               'complete_turnover_pool':len(turnover),'unknown_turnover':unknown_turnover,
               'low_turnover_pool':len(low_turnover),'technical_passers':len(rows),
               'financial_shortlist':len(shortlist),'shortlist_truncated':len(rows)>len(shortlist),
               'excluded_counts':dict(failures),'historical_backtest_run':False,
               'historical_PIT_certified':False,'signals_are_orders':False}
    write(out/'contract.json',c); write(out/'shortlist.json',shortlist)
    write(out/'technical-all.json',rows); write(out/'input-manifest.json',sources)
    write(out/'summary.json',summary)
    write(out/'manifest.json',{p.name:digest(p) for p in sorted(out.iterdir()) if p.is_file()})
    return summary


def fundamental_screen(contract_path, technical_root, financial_root, out):
    c = validate_contract(contract_path); out = fresh_output(out)
    technical_root = Path(technical_root)
    manifest = json.loads((technical_root/'manifest.json').read_text())
    for name, sha in manifest.items():
        p = (technical_root/name).resolve()
        if not p.is_relative_to(technical_root.resolve()) or digest(p) != sha:
            raise ValueError('technical_artifact_hash_mismatch')
    if digest(technical_root/'contract.json') != digest(contract_path):
        raise ValueError('technical_strategy_contract_mismatch')
    shortlist = json.loads((technical_root/'shortlist.json').read_text())
    data, fingerprint = bundle(financial_root)
    per_symbol = collections.defaultdict(dict)
    for spec, rows in data:
        symbol = spec['params'].get('ts_code'); api = spec['api_name']
        if api not in ('income','cashflow','balancesheet','dividend') or api in per_symbol[symbol]:
            raise ValueError('unexpected_financial_bundle_inventory')
        per_symbol[symbol][api] = rows
    if set(per_symbol) != {r['symbol'] for r in shortlist}:
        raise ValueError('financial_shortlist_inventory_mismatch')
    reviewed, passed, counts = [], [], collections.Counter()
    for row in shortlist:
        symbol, r = row['symbol'], dict(row)
        try:
            data = per_symbol[symbol]
            r['quality'] = strategy.fundamentals(data['income'],data['cashflow'],data['balancesheet'],c['price_cutoff'])
            r['dividend'] = strategy.dividends(data['dividend'],c['price_cutoff'],r['total_mv_10k'])
            r['status'] = 'pass' if r['quality']['passed'] and r['dividend']['passed'] else 'fail'
            if r['status'] == 'pass':
                r['yield_TTM'] = r['dividend']['yield_TTM']; passed.append(r)
        except (KeyError, strategy.DataUnknown) as exc:
            r.update(status='unknown',reason=str(exc))
        counts[r['status']] += 1; reviewed.append(r)
    selected = strategy.select_candidates(passed)
    weights = strategy.target_weights(selected); control = strategy.target_weights(selected,control=True)
    for r in selected:
        r['target_weight'] = weights[r['symbol']]; r['control_target_weight'] = control[r['symbol']]
    readiness = strategy.historical_readiness({})
    summary = {'research_only':True,'orders_authorized':False,'promotion_evidence':False,
               'status':'conditional_dated_snapshot_historical_evidence_pending',
               'price_cutoff':c['price_cutoff'],'evaluated_securities':len(reviewed),'counts':dict(counts),
               'selected_securities':len(selected),'target_cash_weight':max(0.,1-sum(weights.values())),
               'minimum_holdings_forced':False,'historical_PIT_certified':False,
               'vendor_announcement_filtered_not_vintage_certified':True,
               'investigation_and_dividend_cancellation_event_coverage':'not_qualified',
               'tradability_certified':False,'historical_backtest':readiness,
               'economic_experiments_run':0,'parameter_searches':0,
               'contract_sha256':digest(contract_path),'technical_manifest_sha256':digest(technical_root/'manifest.json')}
    write(out/'contract.json',c);write(out/'summary.json',summary);write(out/'selected.json',selected)
    write(out/'reviewed.json',reviewed);write(out/'financial-input-manifest.json',fingerprint)
    write(out/'historical-readiness.json',readiness)
    write(out/'manifest.json',{p.name:digest(p) for p in sorted(out.iterdir()) if p.is_file()})
    return summary
