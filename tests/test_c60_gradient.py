import math
import unittest

from qount.research import c60_execution_control as execution
from qount.research import c60_pit_universe as pit
from tests.test_c60_execution_control import fixture


class GradientTests(unittest.TestCase):
    def test_frozen_boundaries_and_invalid_distance(self):
        for distance, exposure in ((-.03, 0), (-.02, 0), (-.019, .35), (0, .35),
                                    (.001, .7), (.02, .7), (.021, 1)):
            self.assertEqual(execution.gradient_exposure(distance), exposure)
        with self.assertRaises(ValueError):
            execution.gradient_exposure(math.nan)

    def test_prefix_invariance_and_selection_unchanged(self):
        axis, assets, _ = fixture()
        full, members = execution.warm_targets(axis, assets, btc_gradient=True)
        _, binary_members = execution.warm_targets(axis, assets)
        self.assertEqual(members, binary_members)
        cut = axis.index('2021-01-15')
        prefix_assets = {s: pit.Asset(s, a.symbol, 0, a.closes[:cut+1], a.quote[:cut+1])
                         for s, a in assets.items()}
        prefix, _ = execution.warm_targets(pit.Axis(axis.dates[:cut+1]), prefix_assets, btc_gradient=True)
        self.assertEqual(prefix, {t: full[t] for t in prefix})

    def test_deadband_uses_actual_drifted_weights_and_rotation_sides(self):
        axis, assets, opens = fixture()
        first = axis.index('2021-01-01')
        targets = {first-1: {'ETHUSDT': .35}, first: {'ETHUSDT': .50},
                   first+1: {'BTCUSDT': .35}}
        rows = execution.replay_crypto_open(axis, assets, opens, targets, cost_bps=25,
                                             rebalance_deadband=.15)['records']
        self.assertGreater(rows[0]['actual_turnover'], 0)
        self.assertTrue(rows[1]['deadband_suppressed'])
        self.assertEqual(rows[1]['actual_turnover'], 0)
        self.assertEqual(rows[1]['weights'], rows[1]['pretrade_weights'])
        self.assertFalse(rows[2]['deadband_suppressed'])
        self.assertGreater(rows[2]['actual_turnover'], .60)
        self.assertAlmostEqual(rows[2]['fee_residual'], 0, places=12)

    def test_small_exit_can_remain_and_is_disclosed(self):
        axis, assets, opens = fixture()
        first = axis.index('2021-01-01')
        targets = {first-1: {'ETHUSDT': .16}, first: {'ETHUSDT': .01}, first+1: {}}
        rows = execution.replay_crypto_open(axis, assets, opens, targets, cost_bps=0,
                                             rebalance_deadband=.15)['records']
        self.assertEqual(rows[1]['weights'], {'ETHUSDT': .01})
        self.assertTrue(rows[2]['deadband_suppressed'])
        self.assertGreater(sum(rows[2]['weights'].values()), 0)


if __name__ == '__main__':
    unittest.main()
