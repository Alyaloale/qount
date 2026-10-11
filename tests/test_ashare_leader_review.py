"""Independent scenario checks for breakout windows and persistent risk exits."""
import math
import statistics
import unittest

from tests.test_ashare_strategy import series
from qount.research.ashare_strategy import Position, make_features
from qount.research.ashare_leader import LeaderBook, make_leader_features


class LeaderReviewTests(unittest.TestCase):
    def fixture(self):
        s=series()
        base=make_features(s)
        extra=make_leader_features(s,base)
        for j in range(len(s.valid)):
            extra.ma20[j]=1
            base.adv20[j]=100_000_000
        book=LeaderBook('sector_base',{'X':{'industry':'A'}})
        book.positions['X']=Position(100,0,1000,10,10,0,0)
        return s,base,extra,book

    def decide(self,book,s,base,extra,j):
        book.decisions(j,'20260901',{'X':s},{'X':base},{'X':extra},
                       {'market_on':False,'sector_rank':[],'price_rank':[]},279)

    def test_peak30_tightening_survives_profit_falling_below30(self):
        s,base,extra,book=self.fixture()
        for j,c in ((1,13),(2,12.7),(3,12.3)):
            s.adj_close[j]=c
            book.mark(j,'20260901',{'X':s})
            self.decide(book,s,base,extra,j)
            if j<3:
                self.assertEqual(book.pending,[])
        self.assertEqual(book.pending[0]['reason'],'profit_trail5')
        self.assertEqual(book.pending[0]['due_j'],4)
        s.raw_open[4]=s.pre_close[4]=s.adj_open[4]=12.1
        book.execute(4,'20260902',{'X':s})
        self.assertAlmostEqual(book.trades[0]['raw_price_with_slippage'],12.0879)
        self.assertEqual(book.closed[0]['reason'],'profit_trail5')

    def test_invalid_close_and_intraday_high_cannot_arm_profit_trail(self):
        s,base,extra,book=self.fixture()
        s.raw_high[1]=1000;s.adj_close[1]=13;s.valid[1]=0
        book.mark(1,'20260901',{'X':s});self.decide(book,s,base,extra,1)
        s.adj_close[2]=10.4
        book.mark(2,'20260902',{'X':s});self.decide(book,s,base,extra,2)
        self.assertEqual(book.positions['X'].peak,10.4)
        self.assertEqual(book.pending,[])

    def test_blocked_initial_exit_survives_subsequent_price_recovery(self):
        s,base,extra,book=self.fixture()
        s.adj_close[1]=9.2
        book.mark(1,'20260901',{'X':s});self.decide(book,s,base,extra,1)
        s.raw_open[2]=9;s.pre_close[2]=10
        book.execute(2,'20260902',{'X':s})
        s.adj_close[2]=11.5
        book.mark(2,'20260902',{'X':s});self.decide(book,s,base,extra,2)
        self.assertEqual(len(book.pending),1)
        self.assertEqual(book.pending[0]['reason'],'initial_stop7')
        self.assertEqual(book.pending[0]['signal_j'],1)
        s.raw_open[3]=s.pre_close[3]=s.adj_open[3]=11.5
        book.execute(3,'20260903',{'X':s})
        self.assertEqual(book.closed[0]['reason'],'initial_stop7')

    def test_prior_high_and_mean_match_literal_windows_across_gaps(self):
        s=series(400)
        for j in range(400):
            s.adj_close[j]=10+2*math.sin(j*.17)+.01*j
        for j in (12,67,180,300):
            s.valid[j]=0
        extra=make_leader_features(s)
        for j in range(20,400):
            if all(s.valid[j-20:j]):
                self.assertEqual(extra.prior20_high[j],max(s.adj_close[j-20:j]))
            else:
                self.assertTrue(math.isnan(extra.prior20_high[j]))
            if all(s.valid[j-19:j+1]):
                self.assertAlmostEqual(extra.ma20[j],statistics.mean(s.adj_close[j-19:j+1]))
            else:
                self.assertTrue(math.isnan(extra.ma20[j]))


if __name__=='__main__':
    unittest.main()
