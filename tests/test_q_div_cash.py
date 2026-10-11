import unittest

from qount.research.q_div import DataUnknown
from qount.research.q_div_cash import CashBook, CashDividend


DAYS = ('20260921','20260922','20260923','20260924','20260925','20260928','20260929')


def book(events=(), tax=lambda *args: .2, fees=lambda *args: 0):
    return CashBook(DAYS, {'A':'utilities','B':'utilities','C':'industry'}, capital=10000,
                    fee_model=fees, tax_rate=tax, dividends=events)


def buy(b, shares=100, symbol='A', **kwargs):
    return b.buy_once(str(b.j)+symbol,symbol,shares,signal_j=b.j-1,raw_price=10,
                      prior_adv=1e7,execution_allowed=True,**kwargs)


def event(pay='20260925'):
    return CashDividend('D','A','20260921','20260923','20260924',pay,1.)


def seed(b):
    b.open_session(DAYS[0]); b.close_session({})
    b.open_session(DAYS[1]); buy(b); b.close_session({'A':10})


class CashAccountingTests(unittest.TestCase):
    def test_record_ex_payment_and_no_double_dividend(self):
        b=book([event()]);seed(b)
        b.open_session(DAYS[2]);b.close_session({'A':10})
        self.assertEqual(b.receivable,0)
        b.open_session(DAYS[3]);row=b.close_session({'A':9})
        self.assertEqual(row['receivable'],100)
        self.assertEqual(row['cash'],9000)
        self.assertEqual(row['nav'],9980)
        b.open_session(DAYS[4])
        self.assertEqual(b.cash,9000)  # not spendable at pay-day open
        row=b.close_session({'A':9})
        self.assertEqual(row['cash'],9100)
        self.assertEqual(row['available_cash'],9080)
        self.assertEqual(row['receivable'],0)
        self.assertEqual(row['nav'],9980)
        b.open_session(DAYS[5]);b.close_session({'A':9})
        self.assertEqual(sum(c['amount'] for c in b.cashflows),100)

    def test_sell_after_record_before_ex_retains_right_and_tax_fixed_on_sale(self):
        b=book([event()],tax=lambda e,entry,end:.2 if end<'20260925' else 0)
        seed(b)
        b.open_session(DAYS[2]);b.close_session({'A':10})
        b.open_session(DAYS[3]);self.assertEqual(b.sell('A',100,signal_j=2,raw_price=9,
            prior_adv=1e7,execution_allowed=True),100)
        b.close_session({})
        self.assertEqual(b.receivable,100)
        self.assertEqual(b.tax_liability,20)
        b.open_session(DAYS[4]);row=b.close_session({})
        self.assertEqual(row['nav'],9980)
        self.assertEqual(row['tax_liability'],0)
        self.assertEqual(b.cash,9980)
        self.assertEqual([c['kind'] for c in b.cashflows],['dividend_payment','dividend_tax'])

    def test_new_buyer_on_exdate_does_not_receive_old_record_right(self):
        b=book([event()])
        for day in DAYS[:3]:b.open_session(day);b.close_session({})
        b.open_session(DAYS[3]);buy(b);b.close_session({'A':9})
        self.assertEqual(b.receivable,0)
        b.open_session(DAYS[4]);b.close_session({'A':9})
        self.assertEqual(b.cash,9000)

    def test_partial_FIFO_sales_preserve_tax_per_lot(self):
        b=book([event()],tax=lambda e,entry,end:.2 if entry=='20260922' else .1)
        seed(b)
        b.open_session(DAYS[2]);buy(b);b.close_session({'A':10})
        b.open_session(DAYS[3]);b.close_session({'A':9})
        self.assertEqual(b.tax_liability,30)
        b.open_session(DAYS[4]);b.close_session({'A':9})
        b.open_session(DAYS[5]);b.sell('A',50,signal_j=4,raw_price=9,prior_adv=1e7,execution_allowed=True)
        row=b.close_session({'A':9})
        self.assertEqual(row['tax_liability'],20)
        self.assertEqual(sum(l.shares for l in b.lots),150)
        self.assertEqual(sum(c.shares for c in b.claims),200)
        self.assertEqual(sum(-c['amount'] for c in b.cashflows if c['kind']=='dividend_tax'),10)

    def test_blocked_buy_one_attempt_and_Tplus1_and_ADV_cap(self):
        b=book();b.open_session(DAYS[0]);b.close_session({});b.open_session(DAYS[1])
        self.assertEqual(b.buy_once('blocked','A',100,signal_j=0,raw_price=10,prior_adv=1e7,execution_allowed=False),0)
        with self.assertRaisesRegex(ValueError,'single_due'):
            b.buy_once('blocked','A',100,signal_j=0,raw_price=10,prior_adv=1e7,execution_allowed=True)
        buy(b)
        self.assertEqual(b.sell('A',100,signal_j=0,raw_price=10,prior_adv=1e7,execution_allowed=True),0)
        b.close_session({'A':10});b.open_session(DAYS[2])
        self.assertEqual(b.sell('A',100,signal_j=1,raw_price=10,prior_adv=50000,execution_allowed=True),50)

    def test_cash_reinvestment_after_payment_and_sector_cap_after_fees(self):
        b=book([event()],fees=lambda *args:5);seed(b)
        for day,mark in zip(DAYS[2:5],(10,9,9)):
            b.open_session(day);b.close_session({'A':mark})
        b.open_session(DAYS[5]);b.mark_raw({'A':9})
        filled=b.buy_once('reinvest','A',10000,signal_j=4,raw_price=9,prior_adv=1e7,execution_allowed=True)
        self.assertEqual(filled,100)
        self.assertLessEqual(sum(l.shares for l in b.lots)*9,.2*b.nav()+1e-9)
        self.assertEqual(b.cash,8190)

    def test_unknown_tax_and_missing_raw_mark_stop(self):
        b=book([event()],tax=lambda *args:None);seed(b)
        b.open_session(DAYS[2]);b.close_session({'A':10});b.open_session(DAYS[3])
        with self.assertRaises(DataUnknown):b.close_session({'A':9})
        b=book();seed(b);b.open_session(DAYS[2])
        with self.assertRaises(DataUnknown):b.close_session({})


if __name__=='__main__':unittest.main()
