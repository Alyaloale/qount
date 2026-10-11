"""Raw-share cash accounting kernel for Q-DIV research fixtures.

No adjusted price is accepted. Fee and dividend-tax policies are explicit caller
inputs, not certified tariffs. The original synthetic-unit Book stays intact;
this kernel is not yet a qualified historical strategy/execution runner.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from qount.research.q_div import DataUnknown, date, number


@dataclass
class Lot:
    lot_id: int
    symbol: str
    entry_day: str
    shares: int


@dataclass(frozen=True)
class CashDividend:
    event_id: str
    symbol: str
    announcement: str
    record_day: str
    ex_day: str
    pay_day: str
    cash_per_share: float

    def __post_init__(self):
        for day in (self.announcement, self.record_day, self.ex_day, self.pay_day):
            date(day)
        if not self.announcement <= self.record_day < self.ex_day <= self.pay_day:
            raise DataUnknown('dividend_dates_not_ordered')
        if not self.event_id or not self.symbol or number(self.cash_per_share) <= 0:
            raise DataUnknown('invalid_cash_dividend')


@dataclass
class Claim:
    event_id: str
    lot_id: int
    entry_day: str
    shares: int
    sale_day: str | None = None
    tax_settled: bool = False


class CashBook:
    """FIFO raw shares, record-date rights and conservative tax-reserved cash.

    On ex day the gross dividend becomes receivable. Payment is credited after
    the pay-day close, never assumed available for the same opening. A caller's
    tax policy returns the effective final rate for (event, entry, sale/current
    day); open entitlements reserve that amount. Sold entitlements settle on sale
    if paid, otherwise on payment. Unknown policy results stop accounting.

    A decrease in a holding-period tax reserve is explicitly a liability change,
    not a second dividend. Input policies and supported corporate actions must
    receive independent qualification before any formal return experiment.
    """
    def __init__(self, sessions, industries, *, capital, fee_model, tax_rate, dividends=()):
        self.sessions = tuple(sessions)
        if not self.sessions or list(self.sessions) != sorted(set(self.sessions)):
            raise ValueError('cash_book_calendar_invalid')
        for day in self.sessions:
            date(day)
        self.industries = dict(industries)
        self.capital = number(capital)
        if self.capital <= 0:
            raise ValueError('cash_book_capital_invalid')
        self.cash = self.capital
        self.fee_model, self.tax_rate = fee_model, tax_rate
        self.events = {e.event_id: e for e in dividends}
        if len(self.events) != len(dividends):
            raise ValueError('duplicate_dividend_event')
        for e in dividends:
            if e.record_day not in self.sessions or e.ex_day not in self.sessions:
                raise DataUnknown('dividend_record_or_ex_outside_calendar')
        self.lots, self.claims, self.marks = [], [], {}
        self.accrued, self.paid, self.recorded = set(), set(), set()
        self.trades, self.cashflows, self.curve = [], [], []
        self.attempted_buys = set()
        self.day, self.j, self.is_open = None, -1, False
        self.next_lot = 0

    def _tax(self, claim):
        event = self.events[claim.event_id]
        rate = number(self.tax_rate(event, claim.entry_day, claim.sale_day or self.day))
        if not 0 <= rate <= 1:
            raise DataUnknown('dividend_tax_rate_invalid')
        return claim.shares * event.cash_per_share * rate

    @property
    def tax_liability(self):
        return sum(self._tax(c) for c in self.claims
                   if c.event_id in self.accrued and not c.tax_settled)

    @property
    def receivable(self):
        return sum(c.shares * self.events[c.event_id].cash_per_share for c in self.claims
                   if c.event_id in self.accrued and c.event_id not in self.paid)

    @property
    def available_cash(self):
        # Reserve paid-dividend tax; future gross receivables cannot fund buys.
        reserve = sum(self._tax(c) for c in self.claims
                      if c.event_id in self.paid and not c.tax_settled)
        return max(0., self.cash-reserve)

    def nav(self):
        values = sum(l.shares*self.marks[l.symbol] for l in self.lots)
        return self.cash + values + self.receivable - self.tax_liability

    def _settle(self):
        for claim in self.claims:
            if claim.event_id in self.paid and claim.sale_day and not claim.tax_settled:
                tax = self._tax(claim)
                self.cash -= tax
                claim.tax_settled = True
                self.cashflows.append({'date': self.day, 'kind': 'dividend_tax',
                    'event_id': claim.event_id, 'lot_id': claim.lot_id, 'amount': -tax})
        if self.cash < -1e-7:
            raise DataUnknown('tax_settlement_negative_cash')

    def _pay(self, *, inclusive):
        for event in self.events.values():
            due = event.pay_day <= self.day if inclusive else event.pay_day < self.day
            if due and event.event_id in self.accrued and event.event_id not in self.paid:
                gross = sum(c.shares*event.cash_per_share for c in self.claims if c.event_id == event.event_id)
                self.cash += gross
                self.paid.add(event.event_id)
                self.cashflows.append({'date': self.day, 'kind': 'dividend_payment',
                                      'event_id': event.event_id, 'amount': gross})
        self._settle()

    def open_session(self, day):
        if self.is_open or self.j+1 >= len(self.sessions) or self.sessions[self.j+1] != day:
            raise ValueError('cash_book_sessions_must_advance_once_in_order')
        self.day, self.j, self.is_open = day, self.j+1, True
        for event in self.events.values():
            if event.ex_day == day:
                if event.event_id not in self.recorded:
                    raise DataUnknown('dividend_record_snapshot_missing')
                self.accrued.add(event.event_id)
        self._pay(inclusive=False)

    def _check_fill(self, signal_j, delay, raw_price, prior_adv, execution_allowed):
        if not self.is_open or delay not in (0, 1) or not isinstance(signal_j, int) or signal_j < 0:
            raise ValueError('cash_fill_clock_invalid')
        if self.j < signal_j+1+delay:
            raise ValueError('cash_fill_before_due_open')
        price, adv = number(raw_price), number(prior_adv)
        if price <= 0 or adv <= 0:
            raise DataUnknown('cash_fill_price_or_prior_ADV_invalid')
        if not isinstance(execution_allowed, bool):
            raise DataUnknown('opening_execution_evidence_unknown')
        return price, adv, execution_allowed

    def buy_once(self, intent_id, symbol, desired_shares, *, signal_j, raw_price,
                 prior_adv, execution_allowed, delay=0):
        price, adv, allowed = self._check_fill(signal_j, delay, raw_price, prior_adv, execution_allowed)
        if self.j != signal_j+1+delay or intent_id in self.attempted_buys:
            raise ValueError('buy_single_due_open_attempt_required')
        self.attempted_buys.add(intent_id)
        if not allowed:
            return 0
        if type(desired_shares) is not int or desired_shares < 0 or desired_shares % 100:
            raise ValueError('whole100share_buy_lots_required')
        industry = self.industries.get(symbol)
        if not industry:
            raise DataUnknown('PIT_level1_industry_missing')
        # Caller marks existing holdings at this open, using raw prices.
        nav = self.nav()
        sector_value = sum(l.shares*self.marks[l.symbol] for l in self.lots
                           if self.industries.get(l.symbol) == industry)
        capacity = max(0., .2*nav-sector_value)
        shares = min(desired_shares, math.floor(min(self.available_cash, .01*adv, capacity)/price/100)*100)
        while shares >= 100:
            notional = shares*price
            fee = number(self.fee_model(notional, 'buy', self.day))
            if fee < 0:
                raise DataUnknown('negative_execution_fee')
            if notional+fee <= self.available_cash+1e-9 and sector_value+notional <= .2*(nav-fee)+1e-9:
                break
            shares -= 100
        if shares < 100:
            return 0
        self.cash -= notional+fee
        self.next_lot += 1
        self.lots.append(Lot(self.next_lot, symbol, self.day, shares))
        self.marks[symbol] = price
        self.trades.append({'date': self.day, 'side': 'buy', 'symbol': symbol, 'shares': shares,
                            'raw_price': price, 'fee': fee, 'signal_j': signal_j, 'intent_id': intent_id})
        return shares

    def sell(self, symbol, desired_shares, *, signal_j, raw_price, prior_adv,
             execution_allowed, delay=0):
        price, adv, allowed = self._check_fill(signal_j, delay, raw_price, prior_adv, execution_allowed)
        if type(desired_shares) is not int or desired_shares < 0:
            raise ValueError('integer_sell_shares_required')
        if not allowed:
            return 0
        eligible = [l for l in self.lots if l.symbol == symbol and l.entry_day < self.day]
        shares = min(desired_shares, sum(l.shares for l in eligible), math.floor(.01*adv/price))
        if shares <= 0:
            return 0
        notional = shares*price
        fee = number(self.fee_model(notional, 'sell', self.day))
        if fee < 0 or notional-fee < 0:
            raise DataUnknown('sell_fees_invalid')
        remaining = shares
        for lot in eligible:
            sold = min(remaining, lot.shares)
            if not sold:
                break
            # Preserve dividend rights when a lot is sold after record day.
            for claim in list(self.claims):
                if claim.lot_id == lot.lot_id and claim.sale_day is None:
                    if sold == claim.shares:
                        claim.sale_day = self.day
                    else:
                        self.claims.append(replace(claim, shares=sold, sale_day=self.day))
                        claim.shares -= sold
            lot.shares -= sold
            remaining -= sold
        self.lots = [l for l in self.lots if l.shares]
        self.cash += notional-fee
        self.marks[symbol] = price
        self._settle()
        self.trades.append({'date': self.day, 'side': 'sell', 'symbol': symbol, 'shares': shares,
                            'raw_price': price, 'fee': fee, 'signal_j': signal_j})
        return shares

    def update_industries(self, mapping: dict):
        self.industries.update(mapping)

    def apply_share_distribution(self, symbol: str, split_ratio: float, day: str):
        """Scale lot shares and active claims on ex-date for non-cash bonus/transfer distributions."""
        if not self.is_open or self.day != day:
            raise ValueError('share_distribution_requires_open_session_on_date')
        ratio = number(split_ratio)
        if ratio <= 0:
            raise ValueError('split_ratio_must_be_positive')
        for lot in self.lots:
            if lot.symbol == symbol:
                lot.shares = int(math.floor(lot.shares * (1.0 + ratio)))
        for claim in self.claims:
            if claim.sale_day is None:
                event = self.events.get(claim.event_id)
                if event and event.symbol == symbol:
                    claim.shares = int(math.floor(claim.shares * (1.0 + ratio)))

    def mark_raw(self, prices):
        if not self.is_open:
            raise ValueError('cash_book_session_not_open')
        for symbol in {l.symbol for l in self.lots}:
            value = number(prices.get(symbol))
            if value <= 0:
                raise DataUnknown('raw_mark_missing_or_nonpositive')
            self.marks[symbol] = value

    def close_session(self, raw_closes):
        self.mark_raw(raw_closes)
        for event in self.events.values():
            if event.record_day == self.day:
                self.claims.extend(Claim(event.event_id, l.lot_id, l.entry_day, l.shares)
                                   for l in self.lots if l.symbol == event.symbol)
                self.recorded.add(event.event_id)
        self._pay(inclusive=True)
        row = {'date': self.day, 'cash': self.cash, 'available_cash': self.available_cash,
               'receivable': self.receivable, 'tax_liability': self.tax_liability, 'nav': self.nav(),
               'research_only': True, 'orders_authorized': False}
        self.curve.append(row)
        self.is_open = False
        return row
