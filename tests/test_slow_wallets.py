import importlib.util
from pathlib import Path
import unittest

_path=Path(__file__).resolve().parents[1]/"scripts/research/study_slow_wallets.py"
_spec=importlib.util.spec_from_file_location("slow_wallets",_path)
study=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(study)


def fill(t, before, side, tid):
    return dict(time=t,startPosition=str(before),sz="1",side=side,tid=tid,hash=str(tid),
                coin="BTC",dir="Open Long" if side=="B" else "Close Long",closedPnl="999999")


class SlowWalletTest(unittest.TestCase):
    def test_behavior_ignores_future_fills_and_reported_profit(self):
        rows=[fill(0,0,"B",1),fill(study.DAY,1,"A",2),fill(14*study.DAY,0,"B",3),fill(15*study.DAY,1,"A",4)]
        args=dict(start=0,split=28*study.DAY,saturated=False,universe=["BTC","ETH"])
        before=study.behavior_screen(rows,**args)
        self.assertTrue(before["eligible"])
        altered=[dict(r,closedPnl="-999999") for r in rows]
        future=fill(29*study.DAY,0,"B",5);future["coin"]="ETH"
        self.assertEqual(before,study.behavior_screen(altered+[future],**args))
        self.assertEqual(before["mapped_training_assets"],["BTC"])

    def test_saturated_history_is_not_accepted_as_complete(self):
        rows=[fill(0,0,"B",1),fill(study.DAY,1,"A",2),fill(14*study.DAY,0,"B",3),fill(15*study.DAY,1,"A",4)]
        result=study.behavior_screen(rows,start=0,split=28*study.DAY,saturated=True,universe=["BTC"])
        self.assertFalse(result["eligible"])
        self.assertIn("response_saturated",result["reasons"])

    def test_initial_position_uses_only_pre_split_observations(self):
        source=dict(states=[dict(time_ms=1,coin="BTC",after="2"),dict(time_ms=10,coin="BTC",after="-2")],
                    signals=[dict(time_ms=10,coin="BTC",target=-1)])
        follow,static=study.initialized_signals(source,"BTC",5)
        self.assertEqual(static[0]["target"],1)
        self.assertEqual(follow[-1]["target"],-1)
        self.assertEqual(follow[-1]["time_ms"],10)

    def test_first_observation_is_not_backfilled_to_window_start(self):
        source=dict(states=[dict(time_ms=10,coin="BTC",after="2")],signals=[])
        follow,static=study.initialized_signals(source,"BTC",0)
        self.assertEqual([(s["time_ms"],s["target"]) for s in follow],[(0,0),(10,1)])
        self.assertEqual(follow,static)


if __name__=="__main__":
    unittest.main()
