"""Current, complete-only market-state data contract and model input reader.

Inputs are ordered native daily observations. Labels and retrospective change
annotations are supervised outputs, never automatically concatenated into X.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from qount.research.market_state_flows import MARKET_CHANNELS,normalize_market_windows,trading_flows

SCHEMA='current_state_complete_crypto_v2'
DEFAULT_ROOT=Path('state/research_runs/market_state_complete_20261101')
STATE_NAMES=('upward','downward','sideways')
ATTRIBUTE_NAMES=('compression_ratio','is_compression','volatility_daily','path_efficiency')
DAY_MS=86_400_000


def validate_market_inputs(d):
    count=len(d['asset']);n=int(d['reference_sessions'])
    if not count or n<3:raise ValueError('empty_dataset_or_invalid_reference')
    if not bool(d['research_only']) or bool(d['orders_authorized']):raise ValueError('research_scope_required')
    if tuple(d['market_names'])!=MARKET_CHANNELS:raise ValueError('incompatible_market_channels')
    market=np.asarray(d['market'])
    if market.shape!=(count,9) or not np.isfinite(market).all():raise ValueError('incomplete_native_market')
    if np.any(market[:,:4]<=0) or np.any(market[:,4:]<0):raise ValueError('invalid_native_market_values')
    if np.any(market[:,1]<np.maximum(market[:,0],market[:,3])) or np.any(market[:,2]>np.minimum(market[:,0],market[:,3])):
        raise ValueError('invalid_ohlc_order')
    if np.any(market[:,6]!=np.floor(market[:,6])):raise ValueError('noninteger_trade_count')
    trading_flows(market)
    if len(np.unique(d['source_row']))!=count:raise ValueError('duplicate_samples')
    for asset in np.unique(d['asset']):
        rows=np.flatnonzero(d['asset']==asset)
        gaps=np.diff(d['bar_open_at'][rows])
        if np.any(gaps<DAY_MS) or np.any(gaps%DAY_MS):raise ValueError('unordered_or_non_daily_active_history')
        if np.any(np.diff(d['decision_at'][rows])<=0):raise ValueError('unordered_sample_clock')
    if np.any(d['bar_close_at']!=d['bar_open_at']+DAY_MS-1):raise ValueError('invalid_native_daily_clock')
    if np.any(d['decision_at']<=d['bar_close_at']):raise ValueError('decision_before_bar_completion')
    if not np.array_equal(d['market_available_at'],d['decision_at']):raise ValueError('market_availability_mismatch')
    for prefix,multiple in (('n',1),('two_n',2)):
        raw=d[prefix+'_raw_market'];scaled=d[prefix+'_scaled_market'];rows=d[prefix+'_source_rows']
        if raw.shape!=(count,n*multiple,9) or not np.isfinite(raw).all():raise ValueError('incomplete_input_window')
        bars=raw.reshape(-1,9)
        if (np.any(bars[:,:4]<=0) or np.any(bars[:,4:]<0)
                or np.any(bars[:,1]<np.maximum(bars[:,0],bars[:,3]))
                or np.any(bars[:,2]>np.minimum(bars[:,0],bars[:,3]))
                or np.any(bars[:,6]!=np.floor(bars[:,6]))):raise ValueError('invalid_historical_input_bar')
        trading_flows(bars)
        if scaled.shape!=raw.shape or not np.isfinite(scaled).all():raise ValueError('incomplete_scaled_window')
        if not np.array_equal(raw[:,-1],market):raise ValueError('window_not_ending_at_sample')
        expected=d['source_row'][:,None]+np.arange(-n*multiple+1,1)[None,:]
        if not np.array_equal(rows,expected):raise ValueError('input_window_row_mismatch')
        if not np.allclose(scaled,normalize_market_windows(raw),rtol=2e-6,atol=1e-7):raise ValueError('incorrect_window_scaling')
    if not np.array_equal(d['n_raw_market'],d['two_n_raw_market'][:,-n:]):raise ValueError('inconsistent_lookback_views')
    return dict(rows=count,assets=len(np.unique(d['asset'])),reference_sessions=n,channels=9)


def validate_arrays(d):
    if 'schema' not in d or str(d['schema'])!=SCHEMA:raise ValueError('wrong_market_state_dataset_schema')
    if str(d['target_mode'])!='current' or int(d['target_offset_sessions'])!=0:
        raise ValueError('target_must_be_same_day_state')
    if not bool(d['research_only']) or bool(d['orders_authorized']):raise ValueError('research_scope_required')
    if tuple(d['market_names'])!=MARKET_CHANNELS or tuple(d['state_names'])!=STATE_NAMES:
        raise ValueError('incompatible_market_or_state_channels')
    if tuple(d['attribute_names'])!=ATTRIBUTE_NAMES:raise ValueError('incompatible_attribute_channels')
    count=len(d['asset']);n=int(d['reference_sessions'])
    if not count or n<3:raise ValueError('empty_dataset_or_invalid_reference')
    state=np.asarray(d['state']);attr=np.asarray(d['attributes'])
    if state.shape!=(count,) or np.any(~np.isin(state,[0,1,2])):raise ValueError('incomplete_state_label')
    if attr.shape!=(count,4) or not np.isfinite(attr).all():raise ValueError('incomplete_attribute_label')
    if (np.any(attr[:,0]<=0) or np.any(~np.isin(attr[:,1],[0,1]))
            or np.any(attr[:,2]<0) or np.any((attr[:,3]<0)|(attr[:,3]>1+1e-10))):
        raise ValueError('invalid_attribute_label')
    previous=np.asarray(d['previous_state_label'])
    if previous.shape!=(count,) or np.any(~np.isin(previous,[0,1,2])):raise ValueError('incomplete_predecessor_label')
    if not np.array_equal(d['switch_label'],state!=previous):raise ValueError('misaligned_switch_supervision')
    if np.any(d['label_available_at']!=d['decision_at']+n*DAY_MS):raise ValueError('same_day_label_maturity_mismatch')
    expected_label=d['source_row'][:,None]+np.arange(-n+1,n+1)[None,:]
    if not np.array_equal(d['label_context_source_rows'],expected_label):raise ValueError('wrong_centered_label_context')
    return validate_market_inputs(d)


class CurrentStateDataset:
    def __init__(self,root=DEFAULT_ROOT):
        self.root=Path(root)
        with np.load(self.root/'dataset.npz',allow_pickle=False) as z:self.data={k:z[k] for k in z.files}
        self.summary=validate_arrays(self.data)
        self.asset_names=np.unique(self.data['asset']).tolist()
        self.asset_index=np.array([self.asset_names.index(a) for a in self.data['asset']],np.int64)
        self.events=None

    def _indices(self,rows):
        rows=np.atleast_1d(rows)
        if rows.ndim!=1:raise IndexError('sample_indices_must_be_one_dimensional')
        if rows.dtype.kind=='b':
            if len(rows)!=self.summary['rows']:raise IndexError('sample_mask_length_mismatch')
            return np.flatnonzero(rows)
        if rows.dtype.kind not in ('i','u') or np.any(rows<0) or np.any(rows>=self.summary['rows']):
            raise IndexError('sample_indices_out_of_range')
        return rows.astype(np.int64)

    def inputs(self,rows,*,lookback='n',scaled=True):
        if lookback not in ('n','two_n'):raise ValueError('unknown_input_lookback')
        rows=self._indices(rows)
        key=lookback+('_scaled_market' if scaled else '_raw_market')
        return dict(market=self.data[key][rows].copy(),asset_index=self.asset_index[rows].copy())

    def targets(self,rows):
        rows=self._indices(rows)
        return dict(state=self.data['state'][rows].copy(),attributes=self.data['attributes'][rows].copy(),
            changed=self.data['switch_label'][rows].copy(),available_at=self.data['label_available_at'][rows].copy())

    def split(self,cutoff,end):
        if end<=cutoff:raise ValueError('invalid_time_interval')
        train=np.flatnonzero(self.data['label_available_at']<cutoff)
        test=np.flatnonzero((self.data['decision_at']>=cutoff)&(self.data['decision_at']<end))
        if np.any(self.data['decision_at'][train]>=cutoff):raise ValueError('future_training_input')
        return train,test

    def funding(self,rows,*,lookback='n',allow_assumed_timing=False):
        if not allow_assumed_timing:raise ValueError('funding_publication_time_is_assumed_not_verified')
        if lookback not in ('n','two_n'):raise ValueError('unknown_input_lookback')
        if self.events is None:
            with np.load(self.root/'funding_events.npz',allow_pickle=False) as z:self.events={k:z[k] for k in z.files}
        out=[]
        for row in self._indices(rows):
            first=int(self.data[lookback+'_funding_start'][row]);stop=int(self.data['funding_stop'][row])
            e=self.events;part=slice(first,stop)
            if (first<0 or stop<=first or stop>len(e['rate']) or np.any(e['asset'][part]!=self.data['asset'][row])
                    or np.any(e['available_at_assumed'][part]<e['observed_at'][part])
                    or np.any(np.diff(e['observed_at'][part])<=0)
                    or np.any(e['available_at_assumed'][part]>self.data['decision_at'][row])
                    or not np.isfinite(e['rate'][part]).all()):
                raise ValueError('incomplete_or_future_funding_context')
            out.append(dict(rate=e['rate'][part].copy(),observed_at=e['observed_at'][part].copy(),
                available_at_assumed=e['available_at_assumed'][part].copy()))
        return out

    def latest_inputs(self,*,lookback='n',scaled=True):
        if lookback not in ('n','two_n'):raise ValueError('unknown_input_lookback')
        with np.load(self.root/'latest_inputs.npz',allow_pickle=False) as z:d={k:z[k] for k in z.files}
        if str(d['schema'])!=SCHEMA+'_inputs':raise ValueError('wrong_latest_input_schema')
        if any(k in d for k in ('state','attributes','switch_label','previous_state_label')):
            raise ValueError('inference_view_must_not_contain_retrospective_labels')
        validate_market_inputs(d)
        if any(a not in self.asset_names for a in d['asset']):raise ValueError('unknown_inference_asset')
        key=lookback+('_scaled_market' if scaled else '_raw_market')
        return dict(market=d[key].copy(),asset_index=np.array([self.asset_names.index(a) for a in d['asset']],np.int64),
            asset=d['asset'].copy(),decision_at=d['decision_at'].copy(),source_row=d['source_row'].copy())
