"""G20-LP v3 live execution: full-pool leveraged hold, daily resize cycle.

Contract (docs/g20-v3-leveraged-pool-2026-11.md), live semantics:

* 11-leg 5U-tier pool, equal weight 1/11, total gross 2.0x on USDT-M futures.
* Daily cycle right after the 00:00 UTC daily bar close: the just-closed bar
  is the signal, the cycle trades at market (the backtest fills at the next
  bar open, which is that same 00:00 boundary for these 24/7 perps).
* Scheduled resize every 5 cycles (weekly) OR when any held leg drifts more
  than 25% relative from its target; a resize recomputes the whole book.
* Min-notional semantics (live): a target below the exchange minimum closes
  the leg to cash; a resize DELTA below the exchange minimum is rejected
  (skipped) — never an unexecutable order.  This matches the exchange and
  the 2026-11-02 review's corrected execution semantics.
* Shared wallet, sizing on USDT marginBalance (equity incl. unrealized).
* No trend logic, no gate, no drawdown de-leveraging.
* Executed cycles normalize account config first (cross margin, 3x per-symbol
  margin setting) and refuse to trade legs near an isolated liquidation.

Authorization: real orders require QOUNT_LIVE_ENABLE=true AND
QOUNT_PRIMARY_STRATEGY == g20_leveraged_pool_v3 (enforced again inside
BinanceUsdMExecution.submit) AND the caller passing confirmed=True.
research_only=false only in the receipt of an authorized executed cycle.

Failure posture: any exception blocks the cycle with an error TYPE only
(exchange messages may carry signed URLs); positions outside the pool also
block the cycle (the 2x sizing contract assumes the wallet is the pool
book).  The next cycle reconciles against real exchange positions before
acting.  Order claims are
idempotent through BinanceExecutionStore; a re-run polls an existing
claim instead of re-planning it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
import time

from qount.execution.binance_usdm import (
    BinanceExecutionStore,
    BinanceUsdMExecution,
    ExecutionContractError,
    lookup_usdm_rule,
)
from qount.execution.protection import position_amount

STRATEGY_ID = "g20_leveraged_pool_v3"
POOL = ("SOLUSDT", "BNBUSDT", "XRPUSDT", "SPYUSDT", "QQQUSDT", "SMHUSDT",
        "IWMUSDT", "XLEUSDT", "XAUUSDT", "COPPERUSDT", "CLUSDT")
GROSS = 2.0
REBALANCE_CYCLES = 5
DRIFT_BAND = 0.25
DAY_MS = 86_400_000
# Per-symbol margin setting only; realized leverage is decided by GROSS sizing.
# Owner-selected 2026-11-04 (3x keeps ~33% initial margin headroom).
EXECUTION_LEVERAGE = 3
# An isolated leg may never sit near its liquidation price (2026-11-04 XRPUSDT
# liquidation ran on a leftover 100x-isolated setting).  Min distance from mark.
ISOLATED_LIQ_MIN_DISTANCE = 0.30


class V3Blocked(Exception):
    """Cycle could not proceed; details stay out of receipts."""


@dataclass(frozen=True)
class LegRule:
    step_size: float
    minimum_quantity: float
    minimum_notional: float


def _floor(value: float, step: float) -> float:
    from decimal import Decimal, ROUND_DOWN
    return float((Decimal(str(value)) / Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN) * Decimal(str(step)))


def plan_legs(*, equity: float, prices: dict[str, float], held: dict[str, float],
              rules: dict[str, LegRule], pool: tuple[str, ...] = POOL,
              gross: float = GROSS) -> list[dict]:
    """Pure resize plan for the whole book.  Live min-notional semantics.

    Each leg -> dict(symbol, action, quantity, target_notional, held_quantity,
    desired_quantity, reason) with action in BUY/SELL/CLOSE/HOLD/SKIP.
    """
    if not (math.isfinite(equity) and equity > 0):
        raise V3Blocked("equity_invalid")
    share = 1.0 / len(pool)
    plan = []
    for symbol in pool:
        price = prices[symbol]
        rule = rules[symbol]
        held_q = float(held.get(symbol, 0.0))
        target_notional = equity * gross * share
        desired = 0.0
        if target_notional >= rule.minimum_notional:
            desired = _floor(target_notional / price, rule.step_size)
            if desired < rule.minimum_quantity or desired * price < rule.minimum_notional:
                desired = 0.0
        delta = desired - held_q
        if desired == 0.0 and held_q > 0.0:
            if held_q * price < rule.minimum_notional:
                plan.append(dict(symbol=symbol, action="SKIP", quantity=0.0,
                                 target_notional=target_notional, held_quantity=held_q,
                                 desired_quantity=0.0, reason="close_below_minimum_notional"))
            else:
                plan.append(dict(symbol=symbol, action="CLOSE", quantity=held_q,
                                 target_notional=target_notional, held_quantity=held_q,
                                 desired_quantity=0.0, reason="target_below_minimum_notional"))
        elif abs(delta) < 1e-12:
            plan.append(dict(symbol=symbol, action="HOLD", quantity=0.0,
                             target_notional=target_notional, held_quantity=held_q,
                             desired_quantity=desired, reason="at_target"))
        elif held_q > 0.0 and (abs(delta) * price < rule.minimum_notional
                               or abs(delta) < rule.minimum_quantity):
            plan.append(dict(symbol=symbol, action="SKIP", quantity=0.0,
                             target_notional=target_notional, held_quantity=held_q,
                             desired_quantity=desired, reason="delta_below_minimum_notional"))
        else:
            plan.append(dict(symbol=symbol, action="BUY" if delta > 0 else "SELL",
                             quantity=abs(delta), target_notional=target_notional,
                             held_quantity=held_q, desired_quantity=desired,
                             reason="resize" if held_q > 0.0 else "entry"))
    return plan


def breaches(*, equity: float, prices: dict[str, float], held: dict[str, float],
             pool: tuple[str, ...] = POOL, gross: float = GROSS,
             drift_band: float = DRIFT_BAND) -> bool:
    """Mirror the backtest breach rule: only held pool legs can breach."""
    share = 1.0 / len(pool)
    for symbol, qty in held.items():
        if qty <= 0 or symbol not in pool:
            continue
        target = equity * gross * share
        actual = qty * prices[symbol]
        if target <= 0 or abs(actual / target - 1.0) > drift_band:
            return True
    return False


def signal_from_klines(rows: list, *, now_ms: int | None = None) -> tuple[int, float]:
    """Return (signal_day_ms, signal_close) from ccxt 1d OHLCV rows.

    The signal bar is the last daily bar whose window has fully closed at
    cycle time (00:00:05 UTC); guard against a missing forming bar and skew.
    """
    if not rows or len(rows) < 2:
        raise V3Blocked("klines_insufficient")
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    last = rows[-1]
    if int(last[0]) + DAY_MS <= now_ms:      # no forming bar in the response
        bar = last
    else:
        bar = rows[-2]
    day, close = int(bar[0]), float(bar[4])
    if not (math.isfinite(close) and close > 0):
        raise V3Blocked("signal_close_invalid")
    return day, close


@dataclass
class V3PoolLive:
    exchange: object
    execution: BinanceUsdMExecution
    state: dict = field(default_factory=dict)

    def balance(self) -> float:
        account = self.exchange.fapiPrivateV3GetAccount({})
        usdt = next(a for a in account["assets"] if a["asset"] == "USDT")
        equity = float(usdt["marginBalance"])
        if not (math.isfinite(equity) and equity > 0):
            raise V3Blocked("usdt_balance_invalid")
        return equity

    def positions(self) -> dict[str, float]:
        rows = self.exchange.fapiPrivateV3GetPositionRisk({})
        if not isinstance(rows, list):
            raise V3Blocked("positions_response_invalid")
        return {str(r["symbol"]): float(position_amount(r))
                for r in rows if abs(position_amount(r)) > 1e-12}

    def ensure_account_config(self) -> None:
        """Normalize per-symbol leverage and margin mode before ordering.

        A legacy account setting must never reach live sizing again (the
        2026-11-04 XRPUSDT liquidation ran on a leftover 100x-isolated
        configuration).  Idempotent, fail-closed.
        """
        for symbol in POOL:
            try:
                self.exchange.fapiPrivatePostLeverage(
                    {"symbol": symbol, "leverage": EXECUTION_LEVERAGE})
            except Exception as exc:
                raise V3Blocked(f"account_config_leverage:{type(exc).__name__}") from exc
            try:
                self.exchange.fapiPrivatePostMarginType(
                    {"symbol": symbol, "marginType": "CROSSED"})
            except Exception as exc:
                message = str(getattr(exc, "args", [""])[0] or exc)
                # -4046: already crossed.  -4048: cannot switch while a
                # position is held; its liquidation distance is guarded by
                # check_isolated_liq instead.
                if "-4046" not in message and "-4048" not in message:
                    raise V3Blocked(f"account_config_margin_type:{type(exc).__name__}") from exc

    def check_isolated_liq(self) -> None:
        """No pool leg may sit near an isolated liquidation price."""
        if not hasattr(self.exchange, "fapiPrivateV2GetPositionRisk"):
            return
        rows = self.exchange.fapiPrivateV2GetPositionRisk({})
        for row in rows if isinstance(rows, list) else []:
            if str(row.get("marginType", "")).lower() != "isolated":
                continue
            try:
                amount = abs(float(row.get("positionAmt") or 0.0))
                liq = abs(float(row.get("liquidationPrice") or 0.0))
                mark = float(row.get("markPrice") or 0.0)
            except (TypeError, ValueError) as exc:
                raise V3Blocked("isolated_liq_invalid") from exc
            if amount <= 1e-12 or liq <= 0.0 or mark <= 0.0:
                continue
            if abs(mark - liq) / mark < ISOLATED_LIQ_MIN_DISTANCE:
                raise V3Blocked("isolated_liq_too_close")

    def signal_prices(self) -> tuple[int, dict[str, float]]:
        now_ms = int(time.time() * 1000)
        days, prices = set(), {}
        for symbol in POOL:
            rows = self.exchange.fetch_ohlcv(symbol, "1d", limit=3)
            day, close = signal_from_klines(rows, now_ms=now_ms)
            days.add(day)
            prices[symbol] = close
        if len(days) != 1:
            raise V3Blocked("signal_day_mismatch")
        day = days.pop()
        if now_ms - day >= 2 * DAY_MS:
            raise V3Blocked("signal_stale")
        return day, prices

    def cycle(self, *, execute: bool, now: int | None = None) -> dict:
        stamp = int(time.time()) if now is None else now
        receipt = dict(strategy_id=STRATEGY_ID,
                       created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp)),
                       execution_mode="auto_live" if execute else "plan_only",
                       orders_authorized=bool(execute and self.execution.authorized_for(STRATEGY_ID)),
                       research_only=not execute, auto_action="NO_ACTION")
        try:
            if self.execution.store.inflight():
                # A crash may have left claims mid-flight: reconcile against the
                # venue before planning anything new.
                self.execution.recover()
                if self.execution.store.inflight():
                    raise V3Blocked("inflight_orders_present")
            if execute and self.execution.authorized_for(STRATEGY_ID):
                self.ensure_account_config()
            self.check_isolated_liq()
            day, prices = self.signal_prices()
            signal_date = time.strftime("%Y-%m-%d", time.gmtime(day / 1000))
            receipt["signal_date"] = signal_date
            if self.state.get("last_signal_date") == signal_date:
                receipt["auto_action"] = "NO_ACTION"
                receipt["reason"] = "signal_date_already_processed"
                return receipt
            equity = self.balance()
            held = self.positions()
            if any(symbol not in POOL for symbol in held):
                # The sizing contract (gross 2x on whole marginBalance) is
                # undefined with foreign exposure in the shared wallet: block
                # explicitly instead of acting on a book we do not manage.
                raise V3Blocked("positions_outside_pool")
            rules = {s: _rule(self.exchange, s) for s in POOL}
            cycle_count = int(self.state.get("cycle_count", 0))
            scheduled = cycle_count % REBALANCE_CYCLES == 0
            breach = breaches(equity=equity, prices=prices, held=held)
            receipt.update(capital_usdt=equity, cycle_count=cycle_count,
                           scheduled_resize=bool(scheduled), drift_breach=bool(breach),
                           positions={s: q for s, q in held.items()})
            if not (scheduled or breach):
                receipt["auto_action"] = "NO_ACTION"
                receipt["reason"] = "within_drift_band"
                self.state.update(cycle_count=cycle_count + 1, last_signal_date=signal_date)
                return receipt
            plan = plan_legs(equity=equity, prices=prices, held=held, rules=rules)
            receipt["plan"] = plan
            receipt["auto_action"] = "RESIZE"
            results = []
            for leg in plan:
                if leg["action"] not in {"BUY", "SELL", "CLOSE"}:
                    continue
                side = "buy" if leg["action"] == "BUY" else "sell"
                intent = "b" if side == "buy" else ("c" if leg["action"] == "CLOSE" else "s")
                client_order_id = f"v3-{signal_date.replace('-', '')}-{leg['symbol']}-{intent}"
                outcome = self._submit_leg(leg, side=side, client_order_id=client_order_id,
                                           signal_date=signal_date, execute=execute,
                                           price=prices[leg["symbol"]])
                results.append(outcome)
            receipt["orders"] = results
            receipt["order_counts"] = {
                "submitted": sum(1 for r in results if r["status"] in {"SUBMITTING", "NEW", "PARTIALLY_FILLED", "FILLED"}),
                "skipped_rule": sum(1 for r in results if r["status"] == "SKIPPED_RULE"),
                "planned_only": sum(1 for r in results if r["status"] == "PLANNED")}
            self.state.update(cycle_count=cycle_count + 1, last_signal_date=signal_date)
            return receipt
        except V3Blocked as exc:
            receipt.update(auto_action="BLOCKED", execution_blocker=str(exc))
            return receipt
        except Exception as exc:
            # Exchange exceptions can contain signed URLs. Never serialize messages.
            receipt.update(auto_action="BLOCKED",
                           execution_blocker=f"input_or_exchange_error:{type(exc).__name__}")
            return receipt

    def _submit_leg(self, leg: dict, *, side: str, client_order_id: str,
                    signal_date: str, execute: bool, price: float) -> dict:
        signal_id = f"g20v3-{signal_date.replace('-', '')}"
        order_intent_id = f"{signal_id}-{leg['symbol']}"
        existing = self.execution.store.get_order(client_order_id)
        if existing is not None:
            # A prior attempt claimed this identity: reconcile, never re-plan.
            return {"symbol": leg["symbol"], "client_order_id": client_order_id,
                    "action": leg["action"], "status": "RECONCILED",
                    "order": self.execution.poll(client_order_id)}
        if not execute:
            return {"symbol": leg["symbol"], "client_order_id": client_order_id,
                    "action": leg["action"], "quantity": leg["quantity"],
                    "status": "PLANNED"}
        try:
            plan = self.execution.build_order_plan(
                client_order_id=client_order_id, symbol=leg["symbol"], side=side,
                quantity=leg["quantity"], price=price, strategy_id=STRATEGY_ID,
                signal_id=signal_id, order_intent_id=order_intent_id,
                reduce_only=(leg["action"] == "CLOSE"))
        except ExecutionContractError:
            # Exchange rules reject this order (e.g. dust close). Record, move on.
            return {"symbol": leg["symbol"], "client_order_id": client_order_id,
                    "action": leg["action"], "status": "SKIPPED_RULE"}
        order = self.execution.submit(plan, confirmed=True)
        # Always poll once so trade identities land in the store this cycle.
        polled = self.execution.poll(client_order_id)
        return {"symbol": leg["symbol"], "client_order_id": client_order_id,
                "action": leg["action"], "status": str(polled.get("status")),
                "executed_quantity": polled.get("executed_quantity")}


def _rule(exchange, symbol: str) -> LegRule:
    rule = lookup_usdm_rule(exchange, symbol)
    return LegRule(step_size=rule.step_size, minimum_quantity=rule.minimum_quantity,
                   minimum_notional=rule.minimum_notional)
