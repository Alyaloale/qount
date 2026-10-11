import math
import unittest
from array import array
from tests.test_ashare_strategy import series
from qount.research.ashare_strategy import Position,make_features
from qount.research.ashare_lowrisk import LowriskBook,vol126,select

class LowriskTests(unittest.TestCase):
 def test_vol_exact_population_and_window(self):
  s=series()
  for j in range(280):s.adj_close[j]=10*math.exp(.001*j+.02*math.sin(j))
  v=vol126(s);changes=[math.log(s.adj_close[k]/s.adj_close[k-1]) for k in range(154,280)]
  mean=sum(changes)/126;expected=math.sqrt(sum((x-mean)**2 for x in changes)/126)*math.sqrt(252)
  self.assertAlmostEqual(v[279],expected);self.assertTrue(math.isnan(v[125]));self.assertTrue(math.isfinite(v[126]))
 def test_vol_missing_not_compressed(self):
  s=series();s.valid[200]=0;self.assertTrue(math.isnan(vol126(s)[279]))
 def test_future_vol_does_not_change_past(self):
  s=series();a=vol126(s);s.adj_close[-1]=999;b=vol126(s);self.assertEqual(a[270],b[270])
 def test_circuit_cancels_old_buy_and_starts_cooldown(self):
  b=LowriskBook('sector_extra_day',{});b.cash=790000;b.plan(1,'X','buy','test',raw_shares=100,budget_cny=1000,adv20=1e8)
  b.decisions(2,'20260101',{}, {}, {'market_on':True,'sector_rank':['X']},True,300)
  self.assertEqual(b.pending,[]);self.assertEqual(b.cooldown_until,65);self.assertEqual(len(b.risk_events),1)
 def test_cooldown_does_not_reset_until_exit_completed(self):
  b=LowriskBook('sector_base',{'X':{'industry':'A'}});s=series();f=make_features(s);f.adv20[70]=1e8
  b.cooldown_until=65;b.positions['X']=Position(100,0,1000,10,10,0,0)
  b.decisions(70,'20260101',{'X':s},{'X':f},{'market_on':True,'sector_rank':['X']},True,279)
  self.assertEqual(b.cooldown_until,65);self.assertEqual(b.pending[0]['side'],'sell')
 def test_reset_after_cooldown(self):
  b=LowriskBook('sector_base',{});b.cash=790000;b.cooldown_until=65
  b.decisions(65,'20260101',{}, {}, {'market_on':False,'sector_rank':[]},False,300)
  self.assertEqual(b.cooldown_until,-1);self.assertEqual(b.anchor_peak,790000);self.assertEqual(b.risk_events,[])
 def test_unknown_industry_and_retired_not_removed(self):
  s=series();s.source_kind='tushare_retired'
  for j in range(280):s.adj_close[j]=10*math.exp(.002*j)
  f=make_features(s);x=select(279,{'X':s},{'X':f},{'X':vol126(s)},{'X':{'industry':None,'list_status':'D'}})
  self.assertEqual(x['sector_rank'],['X']);self.assertEqual(x['price_rank'],['X']);self.assertEqual(x['eligible_retired'],1)
 def test_low_vol_ranks_before_high_vol_and_deterministic_ties(self):
  s=series()
  for j in range(280):s.adj_close[j]=10*math.exp(.002*j)
  f=make_features(s);pan={c:s for c in ['A','B','C']};fs={c:f for c in pan};vol={c:array('d',[v])*280 for c,v in [('A',.4),('B',.1),('C',.1)]};meta={c:{'industry':c} for c in pan}
  x=select(279,pan,fs,vol,meta);self.assertEqual(x['sector_rank'],['B','C','A'])

if __name__=='__main__':unittest.main()
