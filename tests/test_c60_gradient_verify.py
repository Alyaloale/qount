import unittest

from qount.research.c60_gradient_verify import verify_ledger
from qount.research.c60_execution_control import replay_crypto_open
from tests.test_c60_execution_control import fixture


class IndependentReplayTests(unittest.TestCase):
    def test_currency_unit_replay_and_corruption_detection(self):
        axis,assets,opens=fixture()
        first=axis.index('2021-01-01')
        targets={t:{'ETHUSDT':.35 if t%2 else .7} for t in range(first-1,len(axis.dates))}
        raw={a.symbol:{d:[a.closes[j],1e6] for j,d in enumerate(axis.dates)} for a in assets.values()}
        rows=replay_crypto_open(axis,assets,opens,targets,cost_bps=25,rebalance_deadband=.15)['records']
        result=verify_ledger(rows,raw,opens,cost_bps=25,deadband=.15)
        self.assertEqual(result['status'],'passed')
        rows[4]['return']+=.001
        with self.assertRaises(ValueError):verify_ledger(rows,raw,opens,cost_bps=25,deadband=.15)


if __name__=='__main__':unittest.main()
