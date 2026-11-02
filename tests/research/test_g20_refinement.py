"""Independent checks for exposure-matched and combined cash books."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/research'))
from refine_g20_cross_asset import combine, hourly_valuation, static_spy
from qount.research.g20_cross_asset import YEAR
from qount.research_data.bars import Bar


class RefinementTest(unittest.TestCase):
    def test_combination_sums_wealth_rather_than_average_percentage_returns(self):
        def child(values):
            return dict(summary=dict(costs=0.,funding_pnl=0.),fills=[],
                        curve=[dict(time=i+1,equity=x,price_pnl=0.,funding_pnl=0.,costs=0.) for i,x in enumerate(values)])
        r=combine(child([900.,810.]),child([1100.,1210.]),np.array([0,YEAR,2*YEAR]),2000.)
        self.assertAlmostEqual(r['summary']['return_pct'],1.)
        self.assertAlmostEqual(r['curve'][0]['returns'],0.)
        self.assertAlmostEqual(r['curve'][1]['returns'],.01)

    def test_static_weight_fee_solution_preserves_cash_and_post_fee_exposure(self):
        p=dict(symbols=('SPYUSDT',),times=np.array([0,86400,172800,259200]),
               open=np.array([[100.],[120.],[80.],[130.]]))
        r=static_spy(p,.5,capital=1000,cost_bp=30)
        cash,q=1000.,0.
        for fill in r['fills']:
            cash-=fill['quantity']*fill['price']+fill['costs'];q+=fill['quantity']
            if fill['time']<p['times'][-1]:
                self.assertAlmostEqual(q*fill['price']/(cash+q*fill['price']),.5)
        self.assertAlmostEqual(q,0.)
        self.assertAlmostEqual(cash,r['summary']['final'])

    def test_hourly_settlement_at_exit_is_charged_before_closing_fill(self):
        book={'SPYUSDT':dict(mark=[Bar(t,110. if t==90000 else 100.,111.,99.,100.)
                                     for t in range(3600,90001,3600)],
            funding=[dict(fundingTime=90000000,fundingRate='.01',markPrice='110')])}
        r=dict(summary=dict(initial=1000.,final=1089.,funding_pnl=-11.),
               fills=[dict(time=3600,symbol='SPYUSDT',quantity=10.,price=100.,costs=0.),
                      dict(time=90000,symbol='SPYUSDT',quantity=-10.,price=110.,costs=0.)])
        marked=hourly_valuation(book,r,3600,90000)
        self.assertAlmostEqual(marked['marked_final'],1089.)
        self.assertEqual(marked['terminal_quantities'],{})


if __name__=='__main__': unittest.main()
