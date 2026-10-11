"""Q-DIV-Core strategy runner and 4-curve execution engine.

Strict execution according to frozen research design:
config/ashare-q-div-core-design-20261011.json

No parameter search, no lookahead bias, no rescuing failed thresholds.
Research only: orders_authorized=false, promotion_evidence=false.
"""
from __future__ import annotations

import collections
from concurrent.futures import ThreadPoolExecutor
import dataclasses
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from qount.research.q_div import DataUnknown, date, fundamentals, number
from qount.research.q_div_cash import CashBook, CashDividend
from qount.research.q_div_pit import FinancialVersionIndex
from qount.research.q_div_universe import PointInTimeUniverse
from qount.research.q_div_sources import PublicHistorySources, resolve_job

DESIGN_ID = "ashare_q_div_core_design_20261011"


@dataclasses.dataclass(frozen=True)
class QDivCoreConfig:
    capital_cny: float = 1_000_000.0
    start: str = "20150101"
    end: str = "20260930"
    initial_signal: str = "20141231"
    maturity_valid_observations: int = 252
    risk_sessions: int = 126
    adv_sessions: int = 20
    adv_min_cny: float = 30_000_000.0
    financial_scope: str = "industrial_only"
    roe_min: float = 0.08
    cfo_profit_min: float = 0.80
    debt_assets_max: float = 0.70
    financial_age_max_calendar_days: int = 210
    maximum_positions: int = 20
    retention_rank: int = 30
    stock_target_weight: float = 0.05
    industry_target_cap: float = 0.20
    industry_slots: int = 4
    regular_gross_turnover_cap: float = 0.40
    participation_prior_adv: float = 0.01
    buy_lot_raw_shares: int = 100
    intent_window_sessions: int = 5


def standard_costs(notional: float, side: str, day: str, scale: float = 1.0) -> float:
    """Certified statutory fees: commission (3bps, min 5), transfer, stamp (sell only)."""
    commission = max(5.0, notional * 0.0003)
    transfer = notional * (0.0003 if day < "20150801" else 0.00002 if day < "20220429" else 0.00001)
    stamp = notional * (0.001 if day < "20230828" else 0.0005) if side == "sell" else 0.0
    return scale * (commission + transfer + stamp)


def standard_a_share_dividend_tax(event: CashDividend, entry_day: str, current_day: str) -> float:
    """Individual holding period dividend tax: <=30d: 20%, <=365d: 10%, >365d: 0%."""
    d_entry = dt.date(int(entry_day[:4]), int(entry_day[4:6]), int(entry_day[6:]))
    d_curr = dt.date(int(current_day[:4]), int(current_day[4:6]), int(current_day[6:]))
    calendar_days = (d_curr - d_entry).days
    if calendar_days <= 30:
        return 0.20
    elif calendar_days <= 365:
        return 0.10
    else:
        return 0.00


def fill_quote(
    raw_open: float,
    pre_close: float,
    side: str,
    slippage: float,
    amount: float = 1.0,
) -> Tuple[Optional[float], str]:
    """Opening quote with conservative limit and suspension guards."""
    if not (math.isfinite(raw_open) and raw_open > 0 and math.isfinite(pre_close) and pre_close > 0):
        return None, "missing_or_nonpositive_price"
    if not (math.isfinite(amount) and amount > 0):
        return None, "suspended_or_zero_volume"
    if side == "buy" and raw_open >= pre_close * 1.0499:
        return None, "opening_limit_up_guard"
    if side == "sell" and raw_open <= pre_close * 0.9501:
        return None, "opening_limit_down_guard"
    price = raw_open * (1.0 + slippage if side == "buy" else 1.0 - slippage)
    return price, "available"


def percentile_rank_ties(values: List[float], *, descending: bool = False) -> List[float]:
    """Compute average-rank percentile rank in [0, 1] handling ties.
    
    Formula: (average_rank - 1) / (N - 1) for N > 1, 0.0 for N == 1.
    If descending=True, largest value receives rank 1 (pct 1.0).
    If descending=False, smallest value receives rank 1 (pct 1.0).
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.0]

    value_indices = collections.defaultdict(list)
    for i, v in enumerate(values):
        value_indices[v].append(i)

    sorted_unique = sorted(value_indices.keys(), reverse=descending)

    result = [0.0] * n
    current_rank = 1
    for val in sorted_unique:
        idxs = value_indices[val]
        count = len(idxs)
        avg_rank = current_rank + (count - 1) / 2.0
        pct = 1.0 - (avg_rank - 1.0) / (n - 1.0)
        for i in idxs:
            result[i] = pct
        current_rank += count

    return result


@dataclasses.dataclass
class CandidateMetric:
    symbol: str
    sw1_name: str
    close: float
    adv20: float
    vol126: float
    dy3: float
    roe_ttm: float
    cfo_to_profit: float
    debt_to_assets: float
    quality_passed: bool
    dividend_passed: bool
    adv_passed: bool
    vol_passed: bool
    score: float = 0.0
    rank: int = 0


def score_and_rank_candidates(candidates: List[CandidateMetric]) -> List[CandidateMetric]:
    """Rank eligible candidates by mean percentile of DY3 (desc) and Vol126 (asc)."""
    eligible = [c for c in candidates if c.quality_passed and c.dividend_passed and c.adv_passed and c.vol_passed]
    if not eligible:
        return []

    dy3_vals = [c.dy3 for c in eligible]
    vol_vals = [c.vol126 for c in eligible]

    dy3_pcts = percentile_rank_ties(dy3_vals, descending=True)
    vol_pcts = percentile_rank_ties(vol_vals, descending=False)

    for i, c in enumerate(eligible):
        c.score = (dy3_pcts[i] + vol_pcts[i]) / 2.0

    eligible.sort(key=lambda c: (-c.score, c.symbol))
    for rank_idx, c in enumerate(eligible, start=1):
        c.rank = rank_idx

    return eligible


def select_rebalance_portfolio(
    held_symbols: Set[str],
    candidates: List[CandidateMetric],
    *,
    max_positions: int = 20,
    industry_slots: int = 4,
    retention_rank: int = 30,
) -> Tuple[List[str], List[str]]:
    """Select target portfolio respecting retention buffer (<=30) and industry caps (<=4)."""
    candidate_map = {c.symbol: c for c in candidates}
    held_candidates = [candidate_map[s] for s in held_symbols if s in candidate_map]

    held_candidates.sort(key=lambda c: (-c.score, c.symbol))
    retained: List[str] = []
    industry_counts: Dict[str, int] = collections.defaultdict(int)

    for c in held_candidates:
        if c.rank <= retention_rank:
            if industry_counts[c.sw1_name] < industry_slots:
                retained.append(c.symbol)
                industry_counts[c.sw1_name] += 1

    target = list(retained)
    for c in candidates:
        if len(target) >= max_positions:
            break
        if c.symbol in retained:
            continue
        if industry_counts[c.sw1_name] < industry_slots:
            target.append(c.symbol)
            industry_counts[c.sw1_name] += 1

    exit_symbols = [s for s in held_symbols if s not in target]
    return target, exit_symbols


class DividendStore:
    """In-memory dividend and share split repository across all symbols."""

    def __init__(self, records_by_symbol: Dict[str, List[dict]]):
        self.records = records_by_symbol

    @classmethod
    def load_from_sources(cls, sources: PublicHistorySources, max_workers: int = 8) -> "DividendStore":
        div_jobs = [j for j in sources.jobs if j["api_name"] == "dividend"]

        def _load_job(job):
            sym = job["params"].get("ts_code")
            reader, replacement = sources.repairs.get(job["id"], (sources, job))
            r_root, original, receipts = resolve_job(replacement, reader.root, reader.receipts, reader.inherited)
            items = []
            for r in receipts:
                if r["code"] == 0:
                    p = r_root / r["file"]
                    with gzip.open(p, "rt", encoding="utf-8") as f:
                        d = json.load(f)
                        fields = d["data"]["fields"]
                        for row in d["data"]["items"]:
                            items.append(dict(zip(fields, row, strict=True)))
            return sym, items

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            records = dict(ex.map(_load_job, div_jobs))
        return cls(records)

    def evaluate_dy3(
        self,
        symbol: str,
        asof: str,
        close_price: float,
        adj_factor_on_asof: float,
        adj_factor_by_date: Callable[[str], float],
    ) -> Tuple[bool, float]:
        """Check 3 consecutive fiscal years of positive implemented cash dividends and compute DY3."""
        if close_price <= 0 or adj_factor_on_asof <= 0:
            return False, 0.0

        y_now = int(asof[:4])
        req_years = {y_now - 1, y_now - 2, y_now - 3}

        events = self.records.get(symbol, [])
        paid_by_year: Dict[int, float] = collections.defaultdict(float)

        for r in events:
            if r.get("div_proc") != "实施":
                continue
            end_d = r.get("end_date") or ""
            ann_d = max(r.get("ann_date") or "", r.get("imp_ann_date") or "")
            ex_d = r.get("ex_date") or ""
            pay_d = r.get("pay_date") or ""
            if not (end_d and ann_d and ex_d and pay_d):
                continue
            # Implementation announcement strictly before signal date; ex and pay on/before signal date
            if ann_d >= asof or ex_d > asof or pay_d > asof:
                continue

            try:
                fiscal_y = int(end_d[:4])
            except ValueError:
                continue
            if fiscal_y not in req_years:
                continue

            cash = float(r.get("cash_div_tax") or 0.0)
            if cash <= 0:
                continue

            adj_ex = adj_factor_by_date(ex_d)
            if adj_ex <= 0:
                adj_ex = adj_factor_on_asof
            # DPS adjusted to signal share basis
            dps_signal_basis = cash * (adj_ex / adj_factor_on_asof)
            paid_by_year[fiscal_y] += dps_signal_basis

        if set(paid_by_year.keys()) < req_years:
            return False, 0.0
        if any(paid_by_year[y] <= 0 for y in req_years):
            return False, 0.0

        mean_dps = sum(paid_by_year[y] for y in req_years) / 3.0
        dy3 = mean_dps / close_price
        return True, dy3

    def cash_dividends_for_calendar(self, calendar_days: Set[str]) -> List[CashDividend]:
        """Extract CashDividend objects for CashBook within known calendar."""
        result = []
        seen = set()
        for sym, rows in self.records.items():
            for r in rows:
                if r.get("div_proc") != "实施":
                    continue
                ann_d = max(r.get("ann_date") or "", r.get("imp_ann_date") or "")
                rec_d = r.get("record_date") or ""
                ex_d = r.get("ex_date") or ""
                pay_d = r.get("pay_date") or ""
                cash = float(r.get("cash_div_tax") or 0.0)
                if not (ann_d and rec_d and ex_d and pay_d) or cash <= 0:
                    continue
                if rec_d not in calendar_days or ex_d not in calendar_days:
                    continue
                if not (ann_d <= rec_d < ex_d <= pay_d):
                    continue
                event_id = f"{sym}_{r.get('end_date')}_{ex_d}_{pay_d}"
                if event_id in seen:
                    continue
                seen.add(event_id)
                result.append(CashDividend(
                    event_id=event_id,
                    symbol=sym,
                    announcement=ann_d,
                    record_day=rec_d,
                    ex_day=ex_d,
                    pay_day=pay_d,
                    cash_per_share=cash,
                ))
        return result

    def share_distributions_by_date(self) -> Dict[Tuple[str, str], float]:
        """Map (symbol, ex_date) -> split_ratio (e.g. 10送10 -> 1.0) for pure share bonus distributions."""
        splits = {}
        for sym, rows in self.records.items():
            for r in rows:
                if r.get("div_proc") != "实施":
                    continue
                ex_d = r.get("ex_date") or ""
                if not ex_d:
                    continue
                stk = float(r.get("stk_div") or 0.0)
                bo = float(r.get("stk_bo_rate") or 0.0)
                co = float(r.get("stk_co_rate") or 0.0)
                total_split = stk + bo + co
                if total_split > 0:
                    splits[(sym, ex_d)] = total_split
        return splits


class MarketDataStore:
    """In-memory market price and volume repository across trading days."""

    def __init__(
        self,
        daily_by_date: Dict[str, Dict[str, dict]],
        adj_by_date: Dict[str, Dict[str, float]],
        calendar: Tuple[str, ...],
    ):
        self.daily = daily_by_date
        self.adj = adj_by_date
        self.calendar = calendar
        self._cal_index = {d: i for i, d in enumerate(calendar)}

    @classmethod
    def load_from_sources(
        cls,
        sources: PublicHistorySources,
        calendar: Tuple[str, ...],
        max_workers: int = 8,
    ) -> "MarketDataStore":
        daily_jobs = [j for j in sources.jobs if j["api_name"] == "daily"]
        adj_jobs = [j for j in sources.jobs if j["api_name"] == "adj_factor"]

        def _load_daily(job):
            day = job["params"].get("trade_date")
            reader, replacement = sources.repairs.get(job["id"], (sources, job))
            r_root, original, receipts = resolve_job(replacement, reader.root, reader.receipts, reader.inherited)
            m = {}
            for r in receipts:
                if r["code"] == 0:
                    p = r_root / r["file"]
                    with gzip.open(p, "rt", encoding="utf-8") as f:
                        d = json.load(f)
                        fields = d["data"]["fields"]
                        i_code = fields.index("ts_code")
                        i_open = fields.index("open")
                        i_close = fields.index("close")
                        i_pre = fields.index("pre_close")
                        i_amt = fields.index("amount")
                        for row in d["data"]["items"]:
                            sym = row[i_code]
                            m[sym] = {
                                "open": float(row[i_open] or 0.0),
                                "close": float(row[i_close] or 0.0),
                                "pre_close": float(row[i_pre] or 0.0),
                                "amount": float(row[i_amt] or 0.0) * 1000.0,  # Tushare amount is in thousands CNY
                            }
            return day, m

        def _load_adj(job):
            day = job["params"].get("trade_date")
            reader, replacement = sources.repairs.get(job["id"], (sources, job))
            r_root, original, receipts = resolve_job(replacement, reader.root, reader.receipts, reader.inherited)
            m = {}
            for r in receipts:
                if r["code"] == 0:
                    p = r_root / r["file"]
                    with gzip.open(p, "rt", encoding="utf-8") as f:
                        d = json.load(f)
                        fields = d["data"]["fields"]
                        i_code = fields.index("ts_code")
                        i_adj = fields.index("adj_factor")
                        for row in d["data"]["items"]:
                            m[row[i_code]] = float(row[i_adj] or 1.0)
            return day, m

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            daily_by_date = dict(ex.map(_load_daily, daily_jobs))
            adj_by_date = dict(ex.map(_load_adj, adj_jobs))

        return cls(daily_by_date, adj_by_date, calendar)

    def get_adj_factor(self, symbol: str, day: str) -> float:
        day_m = self.adj.get(day)
        if day_m and symbol in day_m:
            return day_m[symbol]
        # Backsearch for last known adj_factor
        idx = self._cal_index.get(day)
        if idx is not None:
            for j in range(idx - 1, -1, -1):
                prev_d = self.calendar[j]
                m = self.adj.get(prev_d)
                if m and symbol in m:
                    return m[symbol]
        return 1.0

    def compute_vol126_and_adv20(
        self,
        symbol: str,
        review_day: str,
    ) -> Tuple[bool, float, bool, float]:
        """Compute population std annualized vol (126 causal returns) and mean ADV (20 sessions)."""
        idx = self._cal_index.get(review_day)
        if idx is None or idx < 126:
            return False, 0.0, False, 0.0

        # Prior 127 sessions to get 126 returns: [idx - 126, ..., idx]
        days_127 = self.calendar[idx - 126: idx + 1]
        adj_closes = []
        for d in days_127:
            dm = self.daily.get(d, {})
            bar = dm.get(symbol)
            if not bar or bar["close"] <= 0:
                return False, 0.0, False, 0.0
            af = self.adj.get(d, {}).get(symbol, 1.0)
            adj_closes.append(bar["close"] * af)

        returns = [adj_closes[i] / adj_closes[i - 1] - 1.0 for i in range(1, len(adj_closes))]
        if len(returns) != 126:
            return False, 0.0, False, 0.0

        # Population standard deviation * sqrt(252)
        mean_r = sum(returns) / 126.0
        var = sum((r - mean_r) ** 2 for r in returns) / 126.0
        vol126 = math.sqrt(var) * math.sqrt(252.0)

        # 20 sessions of amount
        days_20 = self.calendar[idx - 19: idx + 1]
        amounts = []
        for d in days_20:
            dm = self.daily.get(d, {})
            bar = dm.get(symbol)
            if not bar:
                return True, vol126, False, 0.0
            amounts.append(bar["amount"])

        if len(amounts) != 20:
            return True, vol126, False, 0.0
        adv20 = sum(amounts) / 20.0
        adv_passed = adv20 >= 30_000_000.0

        return True, vol126, adv_passed, adv20


class QDivSignalEngine:
    """Monthly review screener producing Point-in-Time candidate rankings."""

    def __init__(
        self,
        universe: PointInTimeUniverse,
        fin_index: FinancialVersionIndex,
        dividend_store: DividendStore,
        market_store: MarketDataStore,
        config: QDivCoreConfig = QDivCoreConfig(),
    ):
        self.universe = universe
        self.fin_index = fin_index
        self.dividend_store = dividend_store
        self.market_store = market_store
        self.config = config

    def evaluate_review(self, review_day: str) -> Tuple[List[CandidateMetric], dict]:
        """Run full Point-in-Time screen at review date."""
        mature_symbols = self.universe.eligible_universe(
            review_day,
            min_sessions=self.config.maturity_valid_observations,
            exclude_st=True,
            require_sw1=True,
            mainboard_only=True,
        )

        candidates: List[CandidateMetric] = []
        counts = {
            "evaluated": len(mature_symbols),
            "quality_passed": 0,
            "dividend_passed": 0,
            "adv_passed": 0,
            "vol_passed": 0,
            "all_passed": 0,
        }

        for sym in sorted(mature_symbols):
            sw1_info = self.universe.industry_l1(sym, review_day)
            sw1_name = sw1_info[1] if sw1_info else "Unknown"

            # 1. Quality gate
            quality_passed = False
            roe_ttm, cfo_ratio, debt_ratio = 0.0, 0.0, 0.0
            try:
                sec, _ = self.fin_index.section(sym, review_day)
                q_res = fundamentals(sec["income"], sec["cashflow"], sec["balancesheet"], review_day)
                if q_res.get("passed") and q_res.get("reason") == "pass":
                    quality_passed = True
                    roe_ttm = q_res.get("ROE_TTM", 0.0)
                    cfo_ratio = q_res.get("CFO_to_parent_profit_TTM", 0.0)
                    debt_ratio = q_res.get("debt_to_assets", 0.0)
            except (DataUnknown, ValueError, KeyError):
                quality_passed = False

            if quality_passed:
                counts["quality_passed"] += 1

            # 2. Market features (Vol126 and ADV20)
            vol_ok, vol126, adv_ok, adv20 = self.market_store.compute_vol126_and_adv20(sym, review_day)
            if adv_ok:
                counts["adv_passed"] += 1
            if vol_ok:
                counts["vol_passed"] += 1

            # 3. Dividend gate and DY3
            dm = self.market_store.daily.get(review_day, {})
            bar = dm.get(sym)
            close_price = bar["close"] if bar else 0.0
            af_asof = self.market_store.get_adj_factor(sym, review_day)

            div_ok, dy3 = self.dividend_store.evaluate_dy3(
                sym,
                review_day,
                close_price,
                af_asof,
                lambda d: self.market_store.get_adj_factor(sym, d),
            )
            if div_ok:
                counts["dividend_passed"] += 1

            all_passed = quality_passed and div_ok and adv_ok and vol_ok
            if all_passed:
                counts["all_passed"] += 1

            candidates.append(CandidateMetric(
                symbol=sym,
                sw1_name=sw1_name,
                close=close_price,
                adv20=adv20,
                vol126=vol126,
                dy3=dy3,
                roe_ttm=roe_ttm,
                cfo_to_profit=cfo_ratio,
                debt_to_assets=debt_ratio,
                quality_passed=quality_passed,
                dividend_passed=div_ok,
                adv_passed=adv_ok,
                vol_passed=vol_ok,
            ))

        ranked = score_and_rank_candidates(candidates)
        return ranked, counts


@dataclasses.dataclass
class RebalanceIntent:
    review_j: int
    review_day: str
    target_symbols: List[str]
    sells: List[Dict[str, Any]]
    buys: List[Dict[str, Any]]
    review_nav: float
    is_initial: bool


class CurveSimulation:
    """Manages CashBook execution for a single cost/delay variant."""

    def __init__(
        self,
        name: str,
        sessions: Tuple[str, ...],
        universe: PointInTimeUniverse,
        market_store: MarketDataStore,
        dividend_store: DividendStore,
        *,
        scale: float = 1.0,
        delay: int = 0,
        config: QDivCoreConfig = QDivCoreConfig(),
    ):
        self.name = name
        self.sessions = sessions
        self.session_index = {d: i for i, d in enumerate(sessions)}
        self.universe = universe
        self.market_store = market_store
        self.dividend_store = dividend_store
        self.scale = scale
        self.delay = delay
        self.config = config

        cal_set = set(sessions)
        dividends = self.dividend_store.cash_dividends_for_calendar(cal_set)
        initial_industries = universe.industry_map(universe.masters.keys(), sessions[0])

        self.book = CashBook(
            sessions,
            initial_industries,
            capital=config.capital_cny,
            fee_model=lambda notional, side, day: standard_costs(notional, side, day, scale=self.scale),
            tax_rate=standard_a_share_dividend_tax,
            dividends=dividends,
        )

        self.splits = self.dividend_store.share_distributions_by_date()
        self.pending_intent: Optional[RebalanceIntent] = None
        self.accumulated_regular_turnover: float = 0.0

    @property
    def held_symbols(self) -> Set[str]:
        return {l.symbol for l in self.book.lots if l.shares > 0}

    def register_intent(self, intent: RebalanceIntent):
        self.pending_intent = intent
        self.accumulated_regular_turnover = 0.0

    def step(self, j: int, day: str):
        # 1. Open session
        self.book.open_session(day)

        # 2. Apply share distributions on ex-date
        for sym in self.held_symbols:
            split_ratio = self.splits.get((sym, day))
            if split_ratio and split_ratio > 0:
                self.book.apply_share_distribution(sym, split_ratio, day)

        # 3. Execution window
        intent = self.pending_intent
        slippage = 0.001 * self.scale
        dm = self.market_store.daily.get(day, {})

        if intent is not None:
            # Execution window: [review_j + 1 + delay, review_j + intent_window + delay]
            start_j = intent.review_j + 1 + self.delay
            end_j = intent.review_j + self.config.intent_window_sessions + self.delay

            if start_j <= j <= end_j:
                turnover_cap = self.config.regular_gross_turnover_cap * intent.review_nav

                # Execute sells first
                for sell_item in intent.sells:
                    sym = sell_item["symbol"]
                    remaining_shares = sell_item["remaining_shares"]
                    if remaining_shares <= 0 or sym not in self.held_symbols:
                        continue

                    bar = dm.get(sym)
                    if not bar:
                        continue

                    price, quote_status = fill_quote(bar["open"], bar["pre_close"], "sell", slippage, bar["amount"])
                    if price is None:
                        continue

                    adv20 = sell_item.get("adv20", 30_000_000.0)
                    max_adv_shares = math.floor(0.01 * adv20 / price)
                    if max_adv_shares <= 0:
                        continue

                    can_sell = min(remaining_shares, max_adv_shares)
                    if not intent.is_initial and not sell_item.get("is_safety", False):
                        avail_turnover = max(0.0, turnover_cap - self.accumulated_regular_turnover)
                        turnover_shares = math.floor(avail_turnover / price)
                        can_sell = min(can_sell, turnover_shares)

                    # Minimum sell ticket protection: avoid tiny sub-fee notional fills
                    if can_sell * price <= 20.0 * self.scale:
                        continue

                    if can_sell > 0:
                        filled = self.book.sell(
                            sym,
                            can_sell,
                            signal_j=intent.review_j,
                            raw_price=price,
                            prior_adv=adv20,
                            execution_allowed=True,
                            delay=self.delay,
                        )
                        if filled > 0:
                            sell_item["remaining_shares"] -= filled
                            fill_notional = filled * price
                            if not intent.is_initial and not sell_item.get("is_safety", False):
                                self.accumulated_regular_turnover += fill_notional

                # Execute buys
                for buy_item in intent.buys:
                    sym = buy_item["symbol"]
                    remaining_shares = buy_item["remaining_shares"]
                    if remaining_shares <= 0:
                        continue

                    bar = dm.get(sym)
                    if not bar:
                        continue

                    price, quote_status = fill_quote(bar["open"], bar["pre_close"], "buy", slippage, bar["amount"])
                    if price is None:
                        continue

                    adv20 = buy_item.get("adv20", 30_000_000.0)
                    max_adv_shares = math.floor(0.01 * adv20 / price / 100) * 100
                    if max_adv_shares <= 0:
                        continue

                    can_buy = min(remaining_shares, max_adv_shares)
                    if not intent.is_initial:
                        avail_turnover = max(0.0, turnover_cap - self.accumulated_regular_turnover)
                        turnover_shares = math.floor(avail_turnover / price / 100) * 100
                        can_buy = min(can_buy, turnover_shares)

                    if can_buy >= 100:
                        intent_id = f"{self.name}_{day}_{sym}_{buy_item.get('order', 0)}"
                        signal_j = j - 1 - self.delay
                        filled = self.book.buy_once(
                            intent_id,
                            sym,
                            can_buy,
                            signal_j=signal_j,
                            raw_price=price,
                            prior_adv=adv20,
                            execution_allowed=True,
                            delay=self.delay,
                        )
                        if filled > 0:
                            buy_item["remaining_shares"] -= filled
                            fill_notional = filled * price
                            if not intent.is_initial:
                                self.accumulated_regular_turnover += fill_notional

            if j == end_j:
                self.pending_intent = None

        # 4. Mark closes and close session
        raw_closes = {}
        for sym in self.held_symbols:
            bar = dm.get(sym)
            if bar and bar["close"] > 0:
                raw_closes[sym] = bar["close"]
            else:
                raw_closes[sym] = self.book.marks.get(sym, 1.0)

        self.book.close_session(raw_closes)


def compute_performance_metrics(
    curve_records: List[dict],
    trades: List[dict],
    benchmark_records: Optional[List[dict]] = None,
) -> dict:
    """Compute CAGR, MaxDD, Sharpe, turnover, annual and regime breakdowns."""
    if not curve_records:
        return {}

    start_d, end_d = curve_records[0]["date"], curve_records[-1]["date"]
    d_start = dt.date(int(start_d[:4]), int(start_d[4:6]), int(start_d[6:]))
    d_end = dt.date(int(end_d[:4]), int(end_d[4:6]), int(end_d[6:]))
    years = max(0.1, (d_end - d_start).days / 365.25)

    v_start, v_end = curve_records[0]["nav"], curve_records[-1]["nav"]
    cagr = (v_end / v_start) ** (1.0 / years) - 1.0 if v_start > 0 else 0.0

    navs = [r["nav"] for r in curve_records]
    peak = navs[0]
    max_dd = 0.0
    daily_rets = []
    for i in range(1, len(navs)):
        if navs[i] > peak:
            peak = navs[i]
        dd = (peak - navs[i]) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        r = navs[i] / navs[i - 1] - 1.0 if navs[i - 1] > 0 else 0.0
        daily_rets.append(r)

    ann_vol = statistics.stdev(daily_rets) * math.sqrt(252.0) if len(daily_rets) > 1 else 0.0
    sharpe = (statistics.mean(daily_rets) * 252.0) / ann_vol if ann_vol > 0 else 0.0
    calmar = cagr / max_dd if max_dd > 0 else 0.0

    total_buy = sum(t["shares"] * t["raw_price"] for t in trades if t["side"] == "buy")
    total_sell = sum(t["shares"] * t["raw_price"] for t in trades if t["side"] == "sell")
    mean_nav = statistics.mean(navs) if navs else 1.0
    annual_turnover = (total_buy + total_sell) / 2.0 / mean_nav / years

    by_year: Dict[int, List[float]] = collections.defaultdict(list)
    for r in curve_records:
        y = int(r["date"][:4])
        by_year[y].append(r["nav"])
    annual_returns = {}
    for y in sorted(by_year):
        pts = by_year[y]
        annual_returns[str(y)] = pts[-1] / pts[0] - 1.0 if pts[0] > 0 else 0.0

    regime_defs = {
        "2015": ("20150101", "20151231"),
        "2018": ("20180101", "20181231"),
        "2021": ("20210101", "20211231"),
        "2022": ("20220101", "20221231"),
        "post20240924": ("20240924", "20260930"),
    }
    date_to_nav = {r["date"]: r["nav"] for r in curve_records}
    sorted_days = [r["date"] for r in curve_records]

    regime_returns = {}
    for reg, (r_start, r_end) in regime_defs.items():
        in_days = [d for d in sorted_days if r_start <= d <= r_end]
        if in_days:
            r_ret = date_to_nav[in_days[-1]] / date_to_nav[in_days[0]] - 1.0
            regime_returns[reg] = r_ret

    return {
        "start": start_d,
        "end": end_d,
        "years": round(years, 3),
        "initial_nav": round(v_start, 2),
        "final_nav": round(v_end, 2),
        "cagr": round(cagr, 6),
        "max_drawdown": round(max_dd, 6),
        "annualized_volatility": round(ann_vol, 6),
        "sharpe_ratio": round(sharpe, 4),
        "calmar_ratio": round(calmar, 4),
        "one_way_annual_turnover": round(annual_turnover, 4),
        "total_trades": len(trades),
        "annual_returns": {k: round(v, 6) for k, v in annual_returns.items()},
        "regime_returns": {k: round(v, 6) for k, v in regime_returns.items()},
    }


def load_csi300_tr_benchmark(sources: PublicHistorySources) -> Dict[str, float]:
    """Load H00300.CSI official CSI 300 Total Return index daily closes."""
    h300_jobs = [j for j in sources.jobs if j["api_name"] == "index_daily" and j["params"].get("ts_code") == "H00300.CSI"]
    closes_by_date = {}
    for job in h300_jobs:
        reader, replacement = sources.repairs.get(job["id"], (sources, job))
        r_root, original, receipts = resolve_job(replacement, reader.root, reader.receipts, reader.inherited)
        for r in receipts:
            if r["code"] == 0:
                p = r_root / r["file"]
                with gzip.open(p, "rt", encoding="utf-8") as f:
                    d = json.load(f)
                    fields = d["data"]["fields"]
                    i_date = fields.index("trade_date")
                    i_close = fields.index("close")
                    for row in d["data"]["items"]:
                        closes_by_date[row[i_date]] = float(row[i_close] or 0.0)
    return closes_by_date


def run_q_div_core_backtest(
    sources: PublicHistorySources,
    *,
    config: QDivCoreConfig = QDivCoreConfig(),
    output_dir: Optional[Path] = None,
    log_fn: Callable[[str], None] = print,
) -> dict:
    """Run full 4-curve + control simulation and evaluate against frozen gates."""
    log_fn("1. Loading Point-in-Time Universe...")
    t0 = dt.datetime.now()
    universe = PointInTimeUniverse.from_sources(sources)
    log_fn(f"   Universe loaded in {(dt.datetime.now() - t0).total_seconds():.2f}s")

    log_fn("2. Loading Point-in-Time Financial Version Index...")
    t1 = dt.datetime.now()
    fin_sources = list(sources.financial_sources(report_types=("1",)))
    fin_index = FinancialVersionIndex(fin_sources)
    log_fn(f"   FinancialVersionIndex built in {(dt.datetime.now() - t1).total_seconds():.2f}s, groups: {fin_index.inventory.get('dated_groups')}")

    log_fn("3. Loading Dividend Store (parallel)...")
    t2 = dt.datetime.now()
    dividend_store = DividendStore.load_from_sources(sources, max_workers=8)
    log_fn(f"   DividendStore loaded in {(dt.datetime.now() - t2).total_seconds():.2f}s, records: {sum(len(v) for v in dividend_store.records.values())}")

    log_fn("4. Loading Market Data Store (parallel)...")
    t3 = dt.datetime.now()
    market_store = MarketDataStore.load_from_sources(sources, universe.calendar, max_workers=8)
    log_fn(f"   MarketDataStore loaded in {(dt.datetime.now() - t3).total_seconds():.2f}s, days: {len(market_store.daily)}")

    log_fn("5. Loading Official CSI 300 TR Benchmark Series (H00300.CSI)...")
    csi300_closes = load_csi300_tr_benchmark(sources)
    log_fn(f"   Benchmark points: {len(csi300_closes)}")

    signal_engine = QDivSignalEngine(universe, fin_index, dividend_store, market_store, config)

    # Simulation trading calendar: 2014-12-31 to 2026-09-30
    sim_sessions = universe.trading_days("20141231", config.end)
    log_fn(f"   Simulation calendar: {len(sim_sessions)} sessions ({sim_sessions[0]} to {sim_sessions[-1]})")

    # Curves to simulate
    curves = {
        "base": CurveSimulation("base", sim_sessions, universe, market_store, dividend_store, scale=1.0, delay=0, config=config),
        "double_cost": CurveSimulation("double_cost", sim_sessions, universe, market_store, dividend_store, scale=2.0, delay=0, config=config),
        "extra_day": CurveSimulation("extra_day", sim_sessions, universe, market_store, dividend_store, scale=1.0, delay=1, config=config),
        "double_cost_extra_day": CurveSimulation("double_cost_extra_day", sim_sessions, universe, market_store, dividend_store, scale=2.0, delay=1, config=config),
        "equal_weight_control": CurveSimulation("equal_weight_control", sim_sessions, universe, market_store, dividend_store, scale=1.0, delay=0, config=config),
    }

    # Month-end review dates: all calendar month-ends from 20141231 to 20260831
    initial_review_day = "20141231"
    review_days = [d for d in universe.month_ends("20141231", config.end) if d < sim_sessions[-1]]
    review_set = set(review_days)
    log_fn(f"   Monthly review schedule: {len(review_days)} reviews (initial {initial_review_day})")

    monthly_records = []
    log_fn("6. Commencing 4-curve + control simulation...")
    sim_t0 = dt.datetime.now()

    for j, day in enumerate(sim_sessions):
        # Determine if today is a review date
        if day in review_set:
            rev_day = day
            is_initial = (rev_day == initial_review_day)
            ranked_candidates, counts = signal_engine.evaluate_review(rev_day)

            # Record review snapshot
            top_ranked = [
                {
                    "rank": c.rank,
                    "symbol": c.symbol,
                    "score": round(c.score, 4),
                    "dy3": round(c.dy3, 4),
                    "vol126": round(c.vol126, 4),
                    "roe_ttm": round(c.roe_ttm, 4),
                    "industry": c.sw1_name,
                }
                for c in ranked_candidates[:30]
            ]
            monthly_records.append({
                "review_date": rev_day,
                "counts": counts,
                "eligible_count": len(ranked_candidates),
                "top_candidates": top_ranked,
            })

            cand_map = {c.symbol: c for c in ranked_candidates}
            current_industries = universe.industry_map([c.symbol for c in ranked_candidates], rev_day)
            for curve in curves.values():
                curve.book.update_industries(current_industries)

            # Update intents for each curve
            for c_name, curve in curves.items():
                if c_name == "equal_weight_control":
                    # EW control: all eligible names get 1/N
                    eligible_syms = [c.symbol for c in ranked_candidates]
                    n_eligible = len(eligible_syms)
                    rev_nav = curve.book.nav()
                    ew_weight = 1.0 / n_eligible if n_eligible > 0 else 0.0

                    # Sells
                    sells = []
                    for s in curve.held_symbols:
                        if s not in eligible_syms:
                            sh = sum(l.shares for l in curve.book.lots if l.symbol == s)
                            sells.append({"symbol": s, "remaining_shares": sh, "is_safety": universe.is_st(s, rev_day), "adv20": 30_000_000.0})

                    # Buys
                    buys = []
                    for order_idx, s in enumerate(eligible_syms, 1):
                        if s not in curve.held_symbols:
                            bar = market_store.daily.get(rev_day, {}).get(s)
                            px = bar["close"] if bar else 1.0
                            budget = ew_weight * rev_nav
                            des_shares = math.floor(budget / (px * 100)) * 100
                            c_item = cand_map.get(s)
                            adv = c_item.adv20 if c_item else 30_000_000.0
                            buys.append({"symbol": s, "remaining_shares": des_shares, "adv20": adv, "order": order_idx})

                    curve.register_intent(RebalanceIntent(
                        review_j=j,
                        review_day=rev_day,
                        target_symbols=eligible_syms,
                        sells=sells,
                        buys=buys,
                        review_nav=rev_nav,
                        is_initial=is_initial,
                    ))
                else:
                    # CORE curves
                    target_syms, exit_syms = select_rebalance_portfolio(
                        curve.held_symbols,
                        ranked_candidates,
                        max_positions=config.maximum_positions,
                        industry_slots=config.industry_slots,
                        retention_rank=config.retention_rank,
                    )
                    rev_nav = curve.book.nav()

                    # Sells
                    sells = []
                    for s in exit_syms:
                        sh = sum(l.shares for l in curve.book.lots if l.symbol == s)
                        c_item = cand_map.get(s)
                        adv = c_item.adv20 if c_item else 30_000_000.0
                        sells.append({
                            "symbol": s,
                            "remaining_shares": sh,
                            "is_safety": universe.is_st(s, rev_day),
                            "adv20": adv,
                        })

                    # Buys
                    buys = []
                    order_idx = 1
                    for s in target_syms:
                        if s not in curve.held_symbols:
                            bar = market_store.daily.get(rev_day, {}).get(s)
                            px = bar["close"] if bar else 1.0
                            budget = config.stock_target_weight * rev_nav
                            des_shares = math.floor(budget / (px * 100)) * 100
                            c_item = cand_map.get(s)
                            adv = c_item.adv20 if c_item else 30_000_000.0
                            buys.append({
                                "symbol": s,
                                "remaining_shares": des_shares,
                                "adv20": adv,
                                "order": order_idx,
                            })
                            order_idx += 1

                    curve.register_intent(RebalanceIntent(
                        review_j=j,
                        review_day=rev_day,
                        target_symbols=target_syms,
                        sells=sells,
                        buys=buys,
                        review_nav=rev_nav,
                        is_initial=is_initial,
                    ))

        # Daily step on all curves
        for curve in curves.values():
            curve.step(j, day)

        if (j + 1) % 500 == 0 or (j + 1) == len(sim_sessions):
            log_fn(f"   Progress: {j + 1}/{len(sim_sessions)} sessions completed (NAV base: {curves['base'].book.nav():.2f})")

    log_fn(f"   Simulation completed in {(dt.datetime.now() - sim_t0).total_seconds():.2f}s")

    # 7. Normalize benchmark series
    b_first = csi300_closes.get(sim_sessions[0], 1.0)
    b_series = []
    for d in sim_sessions:
        close_val = csi300_closes.get(d, b_first)
        nav_val = config.capital_cny * (close_val / b_first)
        b_series.append({"date": d, "nav": nav_val})

    b_metrics = compute_performance_metrics(b_series, [])

    # 8. Compute metrics for all curves
    curve_metrics = {}
    for c_name, curve in curves.items():
        curve_metrics[c_name] = compute_performance_metrics(curve.book.curve, curve.book.trades)

    # 9. Evaluate Frozen Gates
    base_m = curve_metrics["base"]
    bm_cagr = b_metrics.get("cagr", 0.0)
    bm_mdd = b_metrics.get("max_drawdown", 1.0)

    # Alternate start year CAGRs
    alt_start_cagrs = {}
    for alt_y in (2016, 2019, 2022):
        alt_d = f"{alt_y}0101"
        sub_curve = [r for r in curves["base"].book.curve if r["date"] >= alt_d]
        if sub_curve:
            y_span = (dt.date(int(sub_curve[-1]["date"][:4]), int(sub_curve[-1]["date"][4:6]), int(sub_curve[-1]["date"][6:])) -
                      dt.date(int(sub_curve[0]["date"][:4]), int(sub_curve[0]["date"][4:6]), int(sub_curve[0]["date"][6:]))).days / 365.25
            c = (sub_curve[-1]["nav"] / sub_curve[0]["nav"]) ** (1.0 / y_span) - 1.0
            alt_start_cagrs[str(alt_y)] = round(c, 6)

    # Count regime excess vs benchmark
    regime_excess_count = 0
    regime_excesses = {}
    b_date_to_nav = {r["date"]: r["nav"] for r in b_series}
    regime_defs = {
        "2015": ("20150101", "20151231"),
        "2018": ("20180101", "20181231"),
        "2021": ("20210101", "20211231"),
        "2022": ("20220101", "20221231"),
        "post20240924": ("20240924", "20260930"),
    }
    for reg, (r_start, r_end) in regime_defs.items():
        in_days = [d for d in sim_sessions if r_start <= d <= r_end]
        if in_days:
            b_ret = b_date_to_nav[in_days[-1]] / b_date_to_nav[in_days[0]] - 1.0
            base_ret = base_m["regime_returns"].get(reg, 0.0)
            diff = base_ret - b_ret
            regime_excesses[reg] = round(diff, 6)
            if diff >= 0:
                regime_excess_count += 1

    # Annual excess count
    annual_excess_count = 0
    for y_str in [str(y) for y in range(2015, 2026)]:
        y_days = [d for d in sim_sessions if d.startswith(y_str)]
        if y_days:
            b_ret = b_date_to_nav[y_days[-1]] / b_date_to_nav[y_days[0]] - 1.0
            base_ret = base_m["annual_returns"].get(y_str, 0.0)
            if base_ret > b_ret:
                annual_excess_count += 1

    gates_evaluation = {
        "gate_base_CAGR_minus_benchmark": {
            "target": ">= 0.01",
            "actual": round(base_m["cagr"] - bm_cagr, 6),
            "passed": (base_m["cagr"] - bm_cagr) >= 0.01,
        },
        "gate_base_MDD_le_benchmark": {
            "target": "<= benchmark MDD",
            "actual_base_mdd": base_m["max_drawdown"],
            "actual_benchmark_mdd": bm_mdd,
            "passed": base_m["max_drawdown"] <= bm_mdd,
        },
        "gate_stress_CAGR_minus_benchmark": {
            "target": "all >= 0.0",
            "double_cost_excess": round(curve_metrics["double_cost"]["cagr"] - bm_cagr, 6),
            "extra_day_excess": round(curve_metrics["extra_day"]["cagr"] - bm_cagr, 6),
            "double_cost_extra_day_excess": round(curve_metrics["double_cost_extra_day"]["cagr"] - bm_cagr, 6),
            "passed": all((curve_metrics[k]["cagr"] - bm_cagr) >= 0 for k in ("double_cost", "extra_day", "double_cost_extra_day")),
        },
        "gate_regime_excess_min_3_of_5": {
            "target": ">= 3",
            "actual": regime_excess_count,
            "details": regime_excesses,
            "passed": regime_excess_count >= 3,
        },
        "gate_annual_excess_min_6_of_11": {
            "target": ">= 6",
            "actual": annual_excess_count,
            "passed": annual_excess_count >= 6,
        },
        "gate_alternate_start_excess": {
            "target": "all >= 0 vs benchmark",
            "details": alt_start_cagrs,
            "passed": all(v >= bm_cagr for v in alt_start_cagrs.values()),
        },
        "gate_one_way_annual_turnover": {
            "target": "<= 1.20",
            "actual": base_m["one_way_annual_turnover"],
            "passed": base_m["one_way_annual_turnover"] <= 1.20,
        },
    }

    final_result = {
        "study_id": DESIGN_ID,
        "status": "backtest_completed",
        "research_only": True,
        "orders_authorized": False,
        "promotion_evidence": False,
        "primary_benchmark": {
            "name": "CSI300_TR (H00300.CSI)",
            "metrics": b_metrics,
        },
        "curves": curve_metrics,
        "alternate_starts": alt_start_cagrs,
        "gates_evaluation": gates_evaluation,
        "all_frozen_gates_passed": all(g["passed"] for g in gates_evaluation.values()),
        "monthly_review_count": len(monthly_records),
    }

    # 10. Write Artifacts
    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        log_fn(f"7. Writing artifacts to {output_dir}...")

        # summary.json
        (output_dir / "summary.json").write_text(json.dumps(final_result, ensure_ascii=False, indent=2) + "\n")

        # monthly_allocations.json
        (output_dir / "monthly_allocations.json").write_text(json.dumps(monthly_records, ensure_ascii=False, indent=2) + "\n")

        # curves.jsonl.gz
        curves_gz = output_dir / "curves.jsonl.gz"
        with gzip.open(curves_gz, "wt", encoding="utf-8") as f:
            for i, d in enumerate(sim_sessions):
                row = {
                    "date": d,
                    "benchmark_nav": b_series[i]["nav"],
                }
                for c_name, curve in curves.items():
                    row[f"{c_name}_nav"] = curve.book.curve[i]["nav"]
                    row[f"{c_name}_cash"] = curve.book.curve[i]["cash"]
                    row[f"{c_name}_receivable"] = curve.book.curve[i]["receivable"]
                    row[f"{c_name}_tax_liability"] = curve.book.curve[i]["tax_liability"]
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        # trades.jsonl.gz
        trades_gz = output_dir / "trades.jsonl.gz"
        with gzip.open(trades_gz, "wt", encoding="utf-8") as f:
            for c_name, curve in curves.items():
                for t in curve.book.trades:
                    f.write(json.dumps({"curve": c_name, **t}, ensure_ascii=False) + "\n")

        # manifest.json
        manifest = {
            "summary_sha256": hashlib.sha256((output_dir / "summary.json").read_bytes()).hexdigest(),
            "monthly_allocations_sha256": hashlib.sha256((output_dir / "monthly_allocations.json").read_bytes()).hexdigest(),
            "curves_gz_sha256": hashlib.sha256(curves_gz.read_bytes()).hexdigest(),
            "trades_gz_sha256": hashlib.sha256(trades_gz.read_bytes()).hexdigest(),
            "created_at": dt.datetime.now().isoformat(),
        }
        (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        log_fn("   All artifacts successfully written and hashed.")

    return final_result


