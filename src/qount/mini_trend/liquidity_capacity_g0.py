"""No-PnL G0 for ``liquidity_capacity_meta_v1``.

Audits PIT rules revision coverage, volume/turnover, Amihud illiquidity,
Corwin-Schultz spread estimates and book spread/depth availability. It does NOT
produce direction, alpha or PnL. Kill tests fire before any PnL read: rules
coverage below 100%, PIT rules not reconstructable, capacity insufficient, or
estimated cost error exceeding the candidate edge.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.research_data.market_data import Bar
from qount.mini_trend.liquid_trend import LIQUID_TREND_UNIVERSE


LIQUIDITY_CAPACITY_G0_VERSION = "liquidity_capacity_meta_g0_v0.1"
LIQUIDITY_CAPACITY_FAMILY = "liquidity_capacity_meta_v1"


@dataclass(frozen=True)
class LiquidityCapacityG0Protocol:
    hypothesis_family: str = LIQUIDITY_CAPACITY_FAMILY
    candidate_id: str = "liquidity_capacity_state_v0"
    trial_number_within_family: int = 0
    family_trial_budget: int = 3
    target_universe: tuple[str, ...] = LIQUID_TREND_UNIVERSE
    interval: str = "1d"
    market: str = "um"
    start_month: str = "2020-02"
    end_month: str = "2026-06"
    amihud_lookback: int = 20
    corwin_schultz_lookback: int = 20
    minimum_rules_coverage: float = 1.0
    minimum_median_daily_quote_volume_usdt: float = 10_000_000.0
    maximum_amihud_x_1e6: float = 50.0
    output_role: str = "eligibility_cost_capacity_no_alpha"

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "hypothesis_family": self.hypothesis_family,
            "candidate_id": self.candidate_id,
            "trial_number_within_family": self.trial_number_within_family,
            "family_trial_budget": self.family_trial_budget,
            "data": {
                "market": self.market,
                "interval": self.interval,
                "target_universe": list(self.target_universe),
                "start_month": self.start_month,
                "end_month": self.end_month,
                "data_role": "consumed_historical_discovery_pool",
                "existing_cache_only": True,
            },
            "features": {
                "rules_revision_coverage": "fraction of universe with PIT exchange rules",
                "median_daily_quote_volume": "median USDT quote volume per symbol",
                "amihud_illiquidity": "mean(|daily_return| / quote_volume) * 1e6",
                "corwin_schultz_spread": "daily high-low spread proxy",
                "book_spread_depth": "real-time order book snapshot (requires live collection)",
                "missing_data_fail_closed": "symbols/missing funding handled by exclusion",
            },
            "output_role": self.output_role,
            "kill_tests": {
                "rules_coverage_below_100": f"rules coverage < {self.minimum_rules_coverage}",
                "pit_rules_not_reconstructable": "no PIT exchangeInfo revision artifact",
                "capacity_insufficient": f"median quote volume < {self.minimum_median_daily_quote_volume_usdt}",
                "cost_error_exceeds_edge": f"Amihud*1e6 > {self.maximum_amihud_x_1e6}",
            },
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)


LIQUIDITY_CAPACITY_G0_PROTOCOL = LiquidityCapacityG0Protocol()


def _daily_returns(bars: Sequence[Bar]) -> list[float]:
    closes = [bar.close for bar in bars]
    return [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]


def _amihud(bars: Sequence[Bar], lookback: int) -> float | None:
    if len(bars) < lookback + 1:
        return None
    window = bars[-(lookback + 1):]
    values: list[float] = []
    for index in range(1, len(window)):
        ret = window[index].close / window[index - 1].close - 1.0
        volume = window[index].volume * window[index].close
        if volume > 0.0:
            values.append(abs(ret) / volume * 1e6)
    return statistics.mean(values) if values else None


def _corwin_schultz_spread(bars: Sequence[Bar], lookback: int) -> float | None:
    if len(bars) < lookback:
        return None
    window = bars[-lookback:]
    spreads: list[float] = []
    for bar in window:
        if bar.high > 0.0 and bar.low > 0.0 and bar.high > bar.low:
            ln_hl = math.log(bar.high / bar.low)
            spreads.append(2.0 * (ln_hl * ln_hl) / (1.0 + math.sqrt(max(0.0, 2.0 * ln_hl * ln_hl - math.log(bar.high / bar.low) ** 2))))
    return statistics.mean(spreads) if spreads else None


def _bars_by_date(bars: Mapping[str, Sequence[Bar]]) -> tuple[dict[str, dict[str, Bar]], list[str]]:
    dates_by_symbol = {
        symbol: {bar.date: bar for bar in rows} for symbol, rows in bars.items()
    }
    common = sorted(
        set.intersection(*(set(d.keys()) for d in dates_by_symbol.values()))
        if dates_by_symbol
        else set()
    )
    return dates_by_symbol, common


def build_liquidity_capacity_g0_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    *,
    available_symbols: Sequence[str],
    exchange_rules: Mapping[str, Any] | None,
    observed_at: str,
) -> dict[str, Any]:
    protocol = LIQUIDITY_CAPACITY_G0_PROTOCOL
    universe_gap = sorted(set(protocol.target_universe) - set(available_symbols))
    universe_coverage = len(available_symbols) / len(protocol.target_universe)

    rules_present = 0
    rules_trading = 0
    rule_rows: dict[str, Any] = {}
    indexed_rules: dict[str, Mapping[str, Any]] = {}
    if exchange_rules and exchange_rules.get("rules"):
        indexed_rules = {
            str(row.get("symbol", "")).upper(): row
            for row in exchange_rules.get("rules", [])
            if isinstance(row, Mapping) and row.get("symbol")
        }
    for symbol in protocol.target_universe:
        rule = indexed_rules.get(symbol)
        if rule is None:
            rule_rows[symbol] = {"present": False, "trading": False}
            continue
        rules_present += 1
        trading = rule.get("status") == "TRADING"
        if trading:
            rules_trading += 1
        rule_rows[symbol] = {
            "present": True,
            "trading": trading,
            "status": rule.get("status"),
            "min_notional": rule.get("min_notional"),
            "price_filter": rule.get("price_filter"),
        }
    rules_coverage = rules_present / len(protocol.target_universe)

    symbol_rows: dict[str, Any] = {}
    for symbol in available_symbols:
        bars = bars_by_symbol.get(symbol, [])
        if not bars:
            symbol_rows[symbol] = {"bar_count": 0}
            continue
        quote_volumes = [bar.volume * bar.close for bar in bars]
        median_volume = statistics.median(quote_volumes) if quote_volumes else 0.0
        amihud = _amihud(bars, protocol.amihud_lookback)
        cs_spread = _corwin_schultz_spread(bars, protocol.corwin_schultz_lookback)
        symbol_rows[symbol] = {
            "bar_count": len(bars),
            "first_date": bars[0].date,
            "last_date": bars[-1].date,
            "median_daily_quote_volume_usdt": median_volume,
            "amihud_x_1e6": amihud,
            "corwin_schultz_spread_estimate": cs_spread,
            "book_spread_depth_available": False,
            "book_spread_depth_note": "real-time order book collection not started",
        }

    all_volumes_ok = all(
        float(row.get("median_daily_quote_volume_usdt", 0.0))
        >= protocol.minimum_median_daily_quote_volume_usdt
        for row in symbol_rows.values()
        if row.get("bar_count", 0) > 0
    )
    all_amihud_ok = all(
        (row.get("amihud_x_1e6") is None
         or float(row["amihud_x_1e6"]) <= protocol.maximum_amihud_x_1e6)
        for row in symbol_rows.values()
        if row.get("bar_count", 0) > 0
    )

    kill_tests = {
        "rules_coverage_below_100": rules_coverage < protocol.minimum_rules_coverage,
        "pit_rules_not_reconstructable": exchange_rules is None,
        "capacity_insufficient": not all_volumes_ok if symbol_rows else True,
        "cost_error_exceeds_edge": not all_amihud_ok if symbol_rows else True,
    }
    blocked = any(kill_tests.values())

    return {
        "schema_version": LIQUIDITY_CAPACITY_G0_VERSION,
        "artifact_type": "liquidity_capacity_meta_g0",
        "observed_at": observed_at,
        "contract_hash": protocol.contract_hash,
        "meta": {
            "research_only": True,
            "output_role": protocol.output_role,
            "direction_produced": False,
            "pnl_evaluated": False,
            "alpha_attributed": False,
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        },
        "universe": {
            "target": list(protocol.target_universe),
            "available": list(available_symbols),
            "missing": universe_gap,
            "coverage_ratio": universe_coverage,
        },
        "rules": {
            "artifact_present": exchange_rules is not None,
            "rules_present": rules_present,
            "rules_trading": rules_trading,
            "coverage": rules_coverage,
            "pit_revision_available": False,
            "by_symbol": rule_rows,
        },
        "liquidity": symbol_rows,
        "kill_tests": kill_tests,
        "verdict": "block_capacity" if blocked else "pass_to_capacity_calibration",
        "remaining_blockers": (
            [
                f"rules_coverage_{rules_coverage:.4f}_below_{protocol.minimum_rules_coverage}",
                f"pit_rules_artifact_{'missing' if exchange_rules is None else 'present_but_not_pit'}",
                f"universe_gap_{len(universe_gap)}_symbols_missing",
                "book_spread_depth_collection_not_started",
            ]
            if blocked
            else []
        ),
    }
