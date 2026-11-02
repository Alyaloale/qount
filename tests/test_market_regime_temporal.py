import unittest

import numpy as np

from qount.research.market_regime_temporal import duration_distribution, spell_rows
from qount.research.market_regimes import REGIMES


class MarketRegimeTemporalTests(unittest.TestCase):
    def test_spells_expose_successor_and_right_censoring(self):
        states = ['uptrend', 'uptrend', 'transition', 'downtrend', 'downtrend']
        rows = spell_rows(states, [10, 20, 30, 40, 50])
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]['next_state'], 'transition')
        self.assertEqual(rows[0]['remaining'], 2)
        self.assertIsNone(rows[-1]['next_state'])
        self.assertTrue(rows[-1]['right_censored'])
        self.assertEqual([row['index'] for row in rows if row['next_state_index'] is not None and row['index'] == row['spell_end']], [1, 2])

    def test_duration_distribution_returns_survival_and_expectation(self):
        values = np.zeros((1, 10)); values[0, 0] = .5; values[0, 9] = .5
        probabilities, survival, expected = duration_distribution(values)
        self.assertAlmostEqual(probabilities.sum(), 1.)
        self.assertGreaterEqual(survival[0, 0], survival[0, 1])
        self.assertAlmostEqual(expected[0], 5.5)

    def test_unknown_is_not_a_training_spell(self):
        rows = spell_rows(['unknown', 'uptrend', 'uptrend'], [10, 20, 30])
        self.assertTrue(all(row['state'] == 'uptrend' for row in rows))
        self.assertTrue(all(row['state'] in REGIMES for row in rows))


if __name__ == '__main__': unittest.main()
