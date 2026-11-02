import unittest
from decimal import Decimal

import numpy as np

from qount.research.wallet_follow import connect_group, hourly_inventory_signals, persistence_signals, reconstruct, simulate_direction


def fill(before, size, side, tid=1, time=0):
    return dict(startPosition=str(before),sz=str(size),side=side,tid=tid,hash=str(tid),
                time=time,coin="ETH",dir="Open Long")


class WalletFollowTest(unittest.TestCase):
    def test_reorders_same_millisecond_by_position_edges(self):
        a,b,path=connect_group([fill(2,1,"B"),fill(0,2,"B",2)], Decimal(0))
        self.assertEqual((a,b,path),(Decimal(0),Decimal(3),[1,0]))

    def test_cycle_requires_observed_anchor(self):
        rows=[fill(1,1,"A"),fill(0,1,"B",2)]
        with self.assertRaisesRegex(ValueError,"ambiguous_cycle"):
            connect_group(rows)
        a,b,_=connect_group(rows,Decimal(0))
        self.assertEqual((a,b),(Decimal(0),Decimal(0)))

    def test_disconnected_position_paths_are_rejected(self):
        rows=[fill(0,1,"B"),fill(1,1,"A",2),fill(10,1,"B",3),fill(11,1,"A",4)]
        with self.assertRaisesRegex(ValueError,"disconnected"):
            connect_group(rows,Decimal(0))

    def test_duplicate_fill_and_gap_do_not_invent_complete_episode(self):
        a=fill(0,1,"B",1,0)
        b=fill(5,5,"A",2,1000)
        b["dir"]="Close Long"
        r=reconstruct([a,a,b])
        self.assertEqual(r["stats"]["duplicate_fills"],1)
        self.assertEqual(r["stats"]["cross_timestamp_gaps"],1)
        self.assertEqual(r["episodes"],[])

    def test_delay_latest_target_and_funding_ledger(self):
        bars=np.full((8,12),100.);bars[:,0]=np.arange(8)*60000
        signals=[dict(time_ms=10000,target=1),dict(time_ms=190000,target=0)]
        payments=[dict(fundingTime=t,fundingRate=".001",markPrice="100")for t in (120000,180000)]
        r=simulate_direction(signals,bars,payments,start_ms=0,end_ms=360000,initial=1000)
        self.assertEqual([t["time_ms"]for t in r["trades"]],[120000,300000])
        self.assertAlmostEqual(r["funding_pnl"],-.999)
        self.assertAlmostEqual(r["costs"],1.998)
        self.assertAlmostEqual(r["final_equity"],997.003)

    def test_unobserved_future_changes_do_not_create_early_trades(self):
        bars=np.full((8,12),100.);bars[:,0]=np.arange(8)*60000
        signals=[dict(time_ms=10000,target=1),dict(time_ms=20000,target=0)]
        r=simulate_direction(signals,bars,[],start_ms=0,end_ms=360000)
        self.assertEqual(r["order_count"],0)

    def test_persistence_cancels_brief_direction_without_lookahead(self):
        signals=[dict(time_ms=0,target=1),dict(time_ms=60000,target=-1),dict(time_ms=1000000,target=0)]
        out=persistence_signals(signals,900,last_observed_ms=1000000)
        self.assertEqual([(s["time_ms"],s["target"])for s in out],[(960000,-1),(1000000,0)])
        prefix=persistence_signals(signals[:2],900,last_observed_ms=970000)
        self.assertEqual(prefix,[out[0]])

    def test_exact_confirmation_boundary_change_cancels_entry(self):
        signals=[dict(time_ms=0,target=1),dict(time_ms=900000,target=0)]
        self.assertEqual(persistence_signals(signals,900,last_observed_ms=1000000),[])

    def test_inventory_uses_time_weights_and_no_future_state(self):
        states=[dict(time_ms=0,after="2"),dict(time_ms=900000,after="-1"),
                dict(time_ms=3600000,after="100")]
        out=hourly_inventory_signals(states,last_observed_ms=3600000)
        self.assertEqual(out[0]["target"],-1)
        self.assertAlmostEqual(out[0]["mean_inventory"],-.25)
        self.assertEqual(out,hourly_inventory_signals(states[:2],last_observed_ms=3600000))

    def test_hourly_execution_uses_hour_boundaries(self):
        bars=np.full((8,12),100.);bars[:,0]=np.arange(8)*3600000
        r=simulate_direction([dict(time_ms=60000,target=1)],bars,[],start_ms=0,end_ms=14400000,
                             delay_seconds=3600,bar_ms=3600000,cost_bp=0)
        self.assertEqual(r["trades"][0]["time_ms"],7200000)
        self.assertEqual(r["minutes"],240)
        self.assertEqual(r["active_minutes"],120)


if __name__=="__main__":
    unittest.main()
