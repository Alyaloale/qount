"""Observable targets, strict label maturity and prediction-score semantics."""
import unittest

from qount.research.market_state_validation import (
    breakout_survival, causal_probabilities, future_direction, range_containment, scores,
)
from qount.research_data.bars import Bar


class MarketStateValidationTest(unittest.TestCase):
    def fixture(self):
        bars=[Bar(i*86400,100,101,99,100,1000) for i in range(211)]
        rows={b.t:dict(action_state='range',route_side=0,event=None,volatility20=.01,
                      previous_low20=99,previous_high20=101) for b in bars}
        return bars,rows

    def test_neutral_endpoint_does_not_imply_range_path(self):
        bars,rows=self.fixture()
        bars[202]=Bar(202*86400,100,121,99,120,1000)
        direction=future_direction(bars,rows)
        containment=range_containment(bars,rows)
        self.assertEqual(direction[0]['outcome'],1)
        self.assertEqual(containment[0]['outcome'],0)
        self.assertEqual(direction[0]['known_at'],200*86400)
        self.assertEqual(direction[0]['mature_at'],205*86400)

    def test_large_future_move_is_not_in_current_features(self):
        bars,rows=self.fixture()
        old=future_direction(bars,rows)
        bars[205]=Bar(205*86400,100,106,99,105,1000)
        changed=future_direction(bars,rows)
        self.assertEqual(old[0]['outcome'],1)
        self.assertEqual(changed[0]['outcome'],2)
        self.assertEqual(old[0]['known_direction_threshold'],changed[0]['known_direction_threshold'])

    def test_confirmation_gets_its_own_full_future_horizon(self):
        bars,rows=self.fixture()
        for i in range(200,204):
            bars[i]=Bar(i*86400,101,102,100,101,1000)
            rows[bars[i].t]['event']=dict(started_at=200*86400,side=1,boundary=100,
                status='pending' if i==200 else 'confirmed')
        bars[204]=Bar(204*86400,101,102,98,99,1000)
        records=breakout_survival(bars,rows)
        self.assertEqual(len(records),2)
        self.assertEqual(records[0]['outcome'],1)
        self.assertEqual(records[1]['outcome'],0)
        self.assertEqual(records[0]['mature_at']-records[0]['known_at'],3*86400)
        self.assertEqual(records[1]['mature_at']-records[1]['known_at'],3*86400)

    def test_unmatured_and_exact_boundary_labels_never_train_prediction(self):
        samples=[dict(known_at=i,mature_at=i+2,asset='A',key='trend',outcome=i%2)
                 for i in range(1,8)]
        predicted=causal_probabilities(samples,2)
        self.assertEqual(predicted[2]['state_training_count'],0)  # label at t=3 excluded
        self.assertEqual(predicted[3]['state_training_count'],1)
        for row in predicted:
            self.assertTrue(row['last_training_maturity'] is None or row['last_training_maturity']<row['known_at'])
        changed=[dict(s,outcome=1-s['outcome']) if s['mature_at']>=5 else s for s in samples]
        again=causal_probabilities(changed,2)
        self.assertEqual([r['probabilities'] for r in predicted[:4]],[r['probabilities'] for r in again[:4]])

    def test_future_append_leaves_earlier_forecasts_unchanged(self):
        samples=[dict(known_at=i,mature_at=i+5,asset='A' if i%2 else 'B',
                      key='up' if i%3 else 'range',outcome=i%3) for i in range(1,100)]
        full=causal_probabilities(samples,3)
        prefix=causal_probabilities(samples[:60],3)
        self.assertEqual(full[:60],prefix)

    def test_scores_include_class_balance_and_probability_error(self):
        records=[dict(outcome=k,probabilities=[float(j==k) for j in range(3)]) for k in range(3)]
        summary=scores(records)
        self.assertEqual(summary['accuracy'],1)
        self.assertEqual(summary['balanced_accuracy'],1)
        self.assertEqual(summary['brier'],0)
        self.assertEqual(summary['log_loss'],0)
        self.assertEqual(sum(r['count'] for r in summary['calibration']),3)


if __name__=='__main__':
    unittest.main()
