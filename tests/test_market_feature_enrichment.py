"""Source clocks, partial-source handling and causal enriched calculations."""
import datetime as dt
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np

from qount.research.market_feature_enrichment import (
    MACRO_TICKERS, NEW_NAMES, QUALITY, UNVERIFIED, activity_features, activity_tables,
    csv_proxy_records, enrich, global_features, hourly_snapshots, intraday_metric_snapshots, macro_features, price_path_features,
)
from qount.research.market_learning import model_matrix
from qount.research.market_learning_data import ALL_FEATURES, build_dataset
from qount.research.market_stages import market_state_machine
from qount.research_data.bars import Bar


def fixture(count=230):
    rng=np.random.default_rng(55)
    prices=100*np.exp(np.cumsum(rng.normal(0,.015,count)))
    bars=[Bar((i+1)*86400-1,float(p),float(p*1.02),float(p*.98),float(p),1000) for i,p in enumerate(prices)]
    raw_rows=[[i*86400000,b.o,b.h,b.l,b.c,b.v,(i+1)*86400000-1,1e8,100,0,5e7,0] for i,b in enumerate(bars)]
    funding=[dict(fundingTime=i*86400000,fundingRate='.0001') for i in range(count)]
    raw=dict(data=dict(BTCUSDT_klines=raw_rows,BTCUSDT_funding=funding))
    panel=dict(quote=np.full((count,1),1e8),daily_rate=np.full((count,1),.0001),taker=np.full((count,1),5e7))
    return bars,raw,panel


class MarketFeatureEnrichmentTest(unittest.TestCase):
    def test_price_path_prefix_and_path_drawdown(self):
        bars,_,_=fixture(300)
        a=price_path_features(bars,market_state_machine(bars),250)
        b=price_path_features(bars[:251],market_state_machine(bars[:251]),250)
        np.testing.assert_array_equal(a,b)
        closes=np.array([b.c for b in bars[125:251]])
        self.assertAlmostEqual(a[11],max(1-closes/np.maximum.accumulate(closes)))
        self.assertGreaterEqual(a[11],1-closes[-1]/max(closes))
        self.assertTrue(0<=a[1]<=1)

    def test_macro_backward_asof_and_freshness(self):
        records={t:(np.array([100,200]),np.array([[.02,.01,1.],[999,.001,0.]])) for t in MACRO_TICKERS}
        a,clock=macro_features(records,199)
        self.assertAlmostEqual(a[0],2/np.sqrt(20))
        self.assertTrue(np.all(clock[:6]==100))
        changed={t:(c,np.array([r[0],[1e6,1,0]])) for t,(c,r) in records.items()}
        np.testing.assert_array_equal(a,macro_features(changed,199)[0])
        self.assertTrue(np.all(np.isnan(macro_features(records,200+96*3600+1)[0])))

    def test_hourly_requires_full_paired_closed_intervals(self):
        rows=[]
        for hour in range(24):
            stamp=hour*3600000
            rows.append([stamp,100,102,99,101,1000,stamp+3599999,100000,20,500,60000,0])
        future=[r.copy() for r in rows]
        for r in future:
            for col in (1,2,3,4):r[col]*=1.001
            r[10]=40000
        data=dict(data=dict(BTCUSDT_spot=rows,BTCUSDT_futures=future))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'hourly.json'
            path.write_text(json.dumps(data))
            snapshots,_=hourly_snapshots(directory)
            clock,values=snapshots['BTCUSDT',0]
            self.assertEqual(clock,86460)
            np.testing.assert_allclose(values[:4],[.001,.001,.2,.4],atol=1e-12)
            data['data']['BTCUSDT_spot']=rows[:-1]
            path.write_text(json.dumps(data))
            self.assertEqual(hourly_snapshots(directory)[0],{})
            data['data']['BTCUSDT_spot']=rows
            future[0][6]-=1
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'incomplete_hourly_interval'):hourly_snapshots(directory)

    def test_global_proxy_csv_uses_cash_close_and_stops_when_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'BIL_daily.csv'
            days=[dt.date(2025,1,1)+dt.timedelta(days=i) for i in range(80)]
            path.write_text('Date,Adj Close\n'+''.join(f'{day},{100+i*.01}\n' for i,day in enumerate(days)))
            records,_=csv_proxy_records(directory)
            clock=int(dt.datetime(2025,3,21,20,1,tzinfo=dt.timezone.utc).timestamp())
            self.assertEqual(records['BIL'][0][-1],clock)
            values,available=global_features(records,clock)
            self.assertEqual(available[-1],clock)
            self.assertAlmostEqual(values[-1],np.log(100.79/100.59))
            self.assertTrue(np.isnan(global_features(records,clock+96*3600+1)[0][-1]))

    def test_intraday_oi_survives_missing_optional_ratios_but_not_gap(self):
        start=int(dt.datetime(2025,1,3,tzinfo=dt.timezone.utc).timestamp())
        fields=['create_time','symbol','sum_open_interest']
        def payload(skip=()):
            stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
            for i in reversed(range(288)):  # Source row order is not time order.
                if i in skip:continue
                writer.writerow(dict(create_time=dt.datetime.fromtimestamp(start+300*i,dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                    symbol='BTCUSDT',sum_open_interest=100+i))
            return stream.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'BTCUSDT-metrics-2025-01-03.zip'
            with zipfile.ZipFile(path,'w') as z:z.writestr('metrics.csv',payload())
            snapshots,_,rejected=intraday_metric_snapshots(directory)
            clock,values=snapshots['BTCUSDT',start]
            self.assertEqual(clock,start+86400)
            self.assertAlmostEqual(values[0],np.log(387/100))
            self.assertTrue(np.all(np.isnan(values[2:7])))
            self.assertEqual(rejected,0)
            with zipfile.ZipFile(path,'w') as z:z.writestr('metrics.csv',payload(range(100,105)))
            snapshots,_,rejected=intraday_metric_snapshots(directory)
            self.assertEqual(snapshots,{})
            self.assertEqual(rejected,1)

    def test_actual_funding_count_and_no_future_settlement(self):
        _,raw,_=fixture()
        raw['data']['BTCUSDT_funding'].extend([
            dict(fundingTime=220*86400000+3600000,fundingRate='-.0003'),
            dict(fundingTime=220*86400000+7200000,fundingRate='.0002'),
            dict(fundingTime=221*86400000+3600000,fundingRate='100')])
        source=activity_tables(raw)
        row=activity_features(source,'BTCUSDT',220)
        self.assertEqual(row[-1],3)
        self.assertEqual(row[2],.0002)
        self.assertLess(row[3],.01)
        raw['data']['BTCUSDT_funding'].append(raw['data']['BTCUSDT_funding'][0])
        with self.assertRaisesRegex(ValueError,'duplicate_funding'):activity_tables(raw)

    def test_enrichment_preserves_targets_and_masks_unverified_inputs(self):
        bars,raw,panel=fixture()
        markets={'crypto':{'BTCUSDT':bars}};states={'crypto':{'BTCUSDT':market_state_machine(bars)}}
        old=build_dataset(markets,states,panel,{},etf_cache='unused')
        data=enrich(old,markets,states,raw,panel,{}, {}, {})
        self.assertEqual(data['X'].shape,(25,98))
        np.testing.assert_array_equal(old['X'],data['X'][:,:45])
        for key in ('y','maturity','known_at','previous_row','next_row'):
            np.testing.assert_array_equal(old[key],data[key])
        self.assertTrue(np.all(data['feature_available_at']<=data['known_at'][:,None]))
        names=list(data['feature_names'])
        for name in UNVERIFIED|QUALITY|{'top_position_account_log_ratio'}:
            self.assertFalse(data['default_feature_mask'][names.index(name)])
        a=model_matrix(data)
        data['X'][:,~data['default_feature_mask']]=1e10
        data['missing'][:,~data['default_feature_mask']]=False
        np.testing.assert_array_equal(a,model_matrix(data))
        self.assertTrue(np.all(data['missing'][:,names.index('oi_quantity_growth_intraday')]))
        self.assertEqual(len(ALL_FEATURES)+len(NEW_NAMES),98)
        old_matrix=model_matrix(old)
        self.assertEqual(a.shape[1]-old_matrix.shape[1],2*(89-45))
        broken=dict(old,bar_close_time=old['bar_close_time']+1)
        with self.assertRaisesRegex(ValueError,'parent_row_source_clock'):enrich(broken,markets,states,raw,panel,{}, {}, {})
        first=205*86400
        future_hourly={('BTCUSDT',first):(int(old['known_at'][0])+1,np.ones(8))}
        with self.assertRaisesRegex(ValueError,'enriched_feature_lookahead'):
            enrich(old,markets,states,raw,panel,{},future_hourly,{})


if __name__=='__main__':unittest.main()
