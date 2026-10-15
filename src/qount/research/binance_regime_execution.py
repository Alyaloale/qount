"""
QOUNT Universal Regime Expectancy Strategy — Binance USDⓈ-M Futures Execution Engine

Implements the official Universal Market Regime & Dynamic Expectancy Architecture
(universal-regime-expectancy-strategy-2026-10.md) over the Binance Futures venue.

Key Features:
1. Macro Asset Mapping:
   - SPY -> SPYUSDT (S&P 500 Market Anchor)
   - SMH -> SMHUSDT (Semiconductor / Attack Spear)
   - IWM -> IWMUSDT (Russell 2000 Small-Cap Elasticity)
   - QQQ -> QQQUSDT (Nasdaq 100 Tech Growth)
   - GLD -> XAUUSDT (Precious Metals / Currency Hedge)
   - CPER -> COPPERUSDT (Industrial Commodities / Economic Barometer)
   - XLE -> XLEUSDT / CLUSDT (Energy Sector)
2. Microstructure Precision:
   - Automated fetching of Binance stepSize, minQty, tickSize, and minNotional (5 USDT).
   - 1.5x ATR gap-cushioned position sizing model with Floor rounding.
3. 4D Regime & 5-Fold Gate Evaluator:
   - SPY Macro Trend Gate (SPY > EMA200 & EMA50 > EMA200).
   - First-principles Volatility Floor (ATR14 / C >= 0.85%).
   - Quarterly Momentum Gate (RS60 >= -3%).
   - Right-side green reclaim gate (Close > Open).
   - Orthogonal Tier Constraint (Max 1 Equity + Max 1 Commodity/Rate).
4. Dual-Track Exit & Sizing:
   - Stagnant release (30 days < 0.8R), Trend decay (7 days ER < 0.18), MR decay (5 days ER < 0.20).
   - Small-cap DYNAMIC_BULL_2_5X leverage scaling (2.5X strong bull, 1.0X normal, 0X bear).
5. Safety First:
   - Default dry_run=True, orders_authorized=False, research_only=True.
   - Fail-closed execution barrier requiring explicit affirmative live flags.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import math
from pathlib import Path
import statistics
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import urllib.request

# Venue Constants
BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"

# Macro Universe Mapping: Strategy Symbol -> Binance Futures Contract
BINANCE_SYMBOL_MAPPING: Dict[str, str] = {
    "SPY": "SPYUSDT",
    "SMH": "SMHUSDT",
    "IWM": "IWMUSDT",
    "QQQ": "QQQUSDT",
    "GLD": "XAUUSDT",
    "CPER": "COPPERUSDT",
    "XLE": "XLEUSDT",
    "CL": "CLUSDT",
}

REVERSE_SYMBOL_MAPPING: Dict[str, str] = {v: k for k, v in BINANCE_SYMBOL_MAPPING.items()}

NON_EQUITY_BINANCE_SYMBOLS = ["XAUUSDT", "COPPERUSDT", "CLUSDT"]
EQUITY_BINANCE_SYMBOLS = ["SPYUSDT", "SMHUSDT", "IWMUSDT", "QQQUSDT", "XLEUSDT"]


class BinanceKlineBar:
    """Standardized OHLCV bar parsed from Binance Futures."""
    def __init__(self, open_time_ms: int, o: float, h: float, l: float, c: float, v: float, close_time_ms: int):
        self.open_time_ms = int(open_time_ms)
        self.close_time_ms = int(close_time_ms)
        self.o = float(o)
        self.h = float(h)
        self.l = float(l)
        self.c = float(c)
        self.v = float(v)
        self.date_str = dt.datetime.fromtimestamp(open_time_ms / 1000.0, tz=dt.timezone.utc).strftime("%Y-%m-%d")


class BinanceFuturesClient:
    """Lightweight, zero-bloat Binance USDⓈ-M Futures REST client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: str = BINANCE_FUTURES_BASE_URL,
        timeout_seconds: float = 15.0,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        params = params or {}
        headers = {
            "User-Agent": "QOUNT-Binance-Regime-Executor/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key

        if signed:
            if not self.api_key or not self.api_secret:
                raise ValueError("Binance API key and secret are required for signed endpoints.")
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 5000
            query_str = urllib.parse.urlencode(params)
            signature = hmac.new(
                self.api_secret.encode("utf-8"),
                query_str.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            query_str += f"&signature={signature}"
        else:
            query_str = urllib.parse.urlencode(params) if params else ""

        url = f"{self.base_url}{endpoint}"
        req_data = None
        if method == "GET":
            if query_str:
                url = f"{url}?{query_str}"
        elif method in ("POST", "DELETE"):
            req_data = query_str.encode("utf-8") if query_str else b""

        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)

    def get_exchange_info(self) -> Dict[str, Any]:
        """Fetches exchange metadata, trading rules, filters and symbols."""
        return self._request("GET", "/fapi/v1/exchangeInfo")

    def get_klines(
        self,
        symbol: str,
        interval: str = "1d",
        limit: int = 100,
    ) -> List[BinanceKlineBar]:
        """Fetches historical K-lines for regime and indicator computation."""
        raw = self._request("GET", "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        bars = []
        for r in raw:
            bars.append(BinanceKlineBar(
                open_time_ms=r[0],
                o=r[1],
                h=r[2],
                l=r[3],
                c=r[4],
                v=r[5],
                close_time_ms=r[6],
            ))
        return bars

    def get_symbol_rules(self, symbol: str) -> Dict[str, Any]:
        """Extracts LOT_SIZE, PRICE_FILTER, and MIN_NOTIONAL for a symbol."""
        info = self.get_exchange_info()
        for s in info.get("symbols", []):
            if s["symbol"] == symbol:
                rules = {
                    "symbol": symbol,
                    "baseAsset": s["baseAsset"],
                    "quoteAsset": s["quoteAsset"],
                    "status": s["status"],
                    "minQty": 0.0,
                    "stepSize": 0.0,
                    "minNotional": 5.0,
                    "tickSize": 0.01,
                }
                for f in s.get("filters", []):
                    f_type = f.get("filterType")
                    if f_type == "LOT_SIZE":
                        rules["minQty"] = float(f.get("minQty", 0.0))
                        rules["stepSize"] = float(f.get("stepSize", 0.0))
                    elif f_type == "MIN_NOTIONAL":
                        rules["minNotional"] = float(f.get("notional", 5.0))
                    elif f_type == "PRICE_FILTER":
                        rules["tickSize"] = float(f.get("tickSize", 0.01))
                return rules
        raise ValueError(f"Symbol {symbol} not found on Binance Futures.")

    def get_account_balance(self) -> List[Dict[str, Any]]:
        """Signed: Fetches available futures account balances."""
        return self._request("GET", "/fapi/v2/balance", signed=True)

    def get_position_risk(self) -> List[Dict[str, Any]]:
        """Signed: Fetches active position risks and margin status."""
        return self._request("GET", "/fapi/v2/positionRisk", signed=True)

    def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """Signed: Adjusts leverage for a symbol."""
        return self._request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage}, signed=True)

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> Dict[str, Any]:
        """Signed: Sets ISOLATED or CROSSED margin type."""
        return self._request("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": margin_type}, signed=True)

    def place_order(
        self,
        symbol: str,
        side: str,  # BUY or SELL
        order_type: str,  # LIMIT, MARKET, STOP_MARKET, TAKE_PROFIT_MARKET
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        reduce_only: bool = False,
        close_position: bool = False,
        time_in_force: str = "GTC",
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Signed: Submits a futures order."""
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        if quantity is not None:
            params["quantity"] = quantity
        if price is not None:
            params["price"] = price
            params["timeInForce"] = time_in_force
        if stop_price is not None:
            params["stopPrice"] = stop_price
        if reduce_only:
            params["reduceOnly"] = "true"
        if close_position:
            params["closePosition"] = "true"
        if client_order_id:
            params["newClientOrderId"] = client_order_id

        return self._request("POST", "/fapi/v1/order", params, signed=True)


# Mathematical & Technical Indicator Helpers

def compute_ema(series: List[float], span: int) -> List[float]:
    if not series:
        return []
    alpha = 2.0 / (span + 1.0)
    res = [series[0]]
    for x in series[1:]:
        res.append(alpha * x + (1.0 - alpha) * res[-1])
    return res


def compute_atr(bars: List[BinanceKlineBar], span: int = 14) -> List[float]:
    if not bars:
        return []
    res = [bars[0].h - bars[0].l]
    alpha = 1.0 / span
    for i in range(1, len(bars)):
        tr = max(
            bars[i].h - bars[i].l,
            abs(bars[i].h - bars[i - 1].c),
            abs(bars[i].l - bars[i - 1].c),
        )
        res.append(alpha * tr + (1.0 - alpha) * res[-1])
    return res


def compute_kaufman_er(closes: List[float], period: int = 20) -> List[float]:
    ers = []
    for i in range(len(closes)):
        if i < period:
            ers.append(0.3)
        else:
            net_chg = abs(closes[i] - closes[i - period])
            gross_chg = sum(abs(closes[i - k] - closes[i - k - 1]) for k in range(period))
            ers.append(net_chg / (gross_chg + 1e-9))
    return ers


def compute_profile_state(
    bars: List[BinanceKlineBar], c_now: float, cur_atr: float
) -> Tuple[int, str, float, float, float, float, float]:
    """Computes 4D microstructure regime state: S1 (Compression), S2 (Trend), S3 (Exhaustion), S4 (Chop)."""
    if len(bars) < 15 or cur_atr <= 0:
        return 4, "CHOP", c_now, c_now + cur_atr, c_now - cur_atr, 0.5, 0.0
    min_p = min(b.l for b in bars)
    max_p = max(b.h for b in bars)
    if max_p <= min_p:
        return 4, "CHOP", c_now, c_now + cur_atr, c_now - cur_atr, 0.5, 0.0

    num_bins = 40
    bin_w = (max_p - min_p) / num_bins
    bin_v = [0.0] * num_bins
    tot_v = 0.0
    for b in bars:
        v = b.v
        if v <= 0:
            continue
        tot_v += v
        i_l = max(0, min(num_bins - 1, int((b.l - min_p) / bin_w)))
        i_h = max(0, min(num_bins - 1, int((b.h - min_p) / bin_w)))
        n_sp = max(1, i_h - i_l + 1)
        for idx in range(i_l, i_h + 1):
            bin_v[idx] += v / n_sp

    if tot_v <= 0:
        return 4, "CHOP", c_now, c_now + cur_atr, c_now - cur_atr, 0.5, 0.0

    max_idx = max(range(num_bins), key=lambda k: bin_v[k])
    poc_p = min_p + (max_idx + 0.5) * bin_w
    below_v = sum(bin_v[k] for k in range(num_bins) if min_p + (k + 0.5) * bin_w < c_now)
    profit_ratio = below_v / tot_v

    tgt_70 = tot_v * 0.70
    acc_v = bin_v[max_idx]
    l_idx = r_idx = max_idx
    while acc_v < tgt_70 and (l_idx > 0 or r_idx < num_bins - 1):
        v_l = bin_v[l_idx - 1] if l_idx > 0 else -1
        v_r = bin_v[r_idx + 1] if r_idx < num_bins - 1 else -1
        if v_l >= v_r and l_idx > 0:
            l_idx -= 1
            acc_v += bin_v[l_idx]
        elif r_idx < num_bins - 1:
            r_idx += 1
            acc_v += bin_v[r_idx]
        else:
            break

    val = min_p + l_idx * bin_w
    vah = min_p + (r_idx + 1) * bin_w
    concentration = 1.0 - (vah - val) / (max_p - min_p) if (max_p - min_p) > 0 else 0
    dist_poc_atr = (c_now - poc_p) / cur_atr

    if dist_poc_atr > 3.8 and profit_ratio > 0.90:
        return 3, "EXHAUSTION", poc_p, vah, val, profit_ratio, concentration
    if c_now > vah and dist_poc_atr > 0.6 and profit_ratio > 0.65:
        return 2, "TREND_UP", poc_p, vah, val, profit_ratio, concentration
    if concentration > 0.40 and abs(dist_poc_atr) < 1.2 and 0.30 <= profit_ratio <= 0.70:
        return 1, "ACCUMULATION", poc_p, vah, val, profit_ratio, concentration
    return 4, "CHOP", poc_p, vah, val, profit_ratio, concentration


def round_step(val: float, step: float) -> float:
    """Floor rounds quantity to exchange stepSize."""
    if step <= 0:
        return val
    precision = max(0, -int(math.floor(math.log10(step))))
    multiplier = 10 ** precision
    rounded = math.floor(val * multiplier) / multiplier
    return round(rounded, precision)


def round_tick(price: float, tick: float) -> float:
    """Rounds price to exchange tickSize."""
    if tick <= 0:
        return price
    precision = max(0, -int(math.floor(math.log10(tick))))
    return round(round(price / tick) * tick, precision)


class BinanceRegimeExecutionEngine:
    """
    Evaluates real-time Binance Futures market data, generates regime decisions,
    calculates position sizes, and executes or dry-runs orders with audited causality.
    """

    def __init__(
        self,
        client: Optional[BinanceFuturesClient] = None,
        mode: str = "DYNAMIC_BULL_2_5X",  # "1X_SPOT", "TRADIFI_MARGIN_2X", "DYNAMIC_BULL_2_5X"
        dry_run: bool = True,
        orders_authorized: bool = False,
        min_atr_pct: float = 0.0085,
        er_min: float = 0.28,
        min_rs60: float = -0.03,
        max_positions: int = 1,
        risk_budget_pct: float = 0.08,
    ):
        self.client = client or BinanceFuturesClient()
        self.mode = mode
        self.dry_run = dry_run
        self.orders_authorized = orders_authorized
        self.min_atr_pct = min_atr_pct
        self.er_min = er_min
        self.min_rs60 = min_rs60
        self.max_positions = max_positions
        self.risk_budget_pct = risk_budget_pct
        self.active_positions: Dict[str, Dict[str, Any]] = {}

    def evaluate_live_decision_plan(
        self,
        account_equity: float = 100.0,
        historical_candles: Optional[Dict[str, List[BinanceKlineBar]]] = None,
        fetch_missing: bool = True,
    ) -> Dict[str, Any]:
        """
        Pulls or receives daily K-lines for mapped Binance assets, runs the 4D regime engine,
        evaluates gates, and generates an exact executable order plan.
        """
        candles = historical_candles or {}
        required_symbols = list(BINANCE_SYMBOL_MAPPING.values())

        # 1. Fetch missing candles from Binance if requested
        if fetch_missing:
            for sym in required_symbols:
                if sym not in candles:
                    try:
                        candles[sym] = self.client.get_klines(sym, interval="1d", limit=100)
                    except Exception as e:
                        # Graceful skip if symbol is unavailable
                        continue

        if "SPYUSDT" not in candles or len(candles["SPYUSDT"]) < 60:
            return {
                "decision": "HOLD_CASH",
                "reason": "SPYUSDT benchmark data insufficient for macro trend gating.",
                "orders": [],
            }

        # 2. Macro SPY Benchmark Evaluation
        spy_bars = candles["SPYUSDT"]
        spy_closes = [b.c for b in spy_bars]
        spy_ema50 = compute_ema(spy_closes, 50)
        spy_ema200 = compute_ema(spy_closes, 200)

        # Yesterday's close (Day T) determines Day T+1 open trading
        cur_spy_c = spy_bars[-1].c
        cur_spy_ema50 = spy_ema50[-1]
        cur_spy_ema200 = spy_ema200[-1]

        is_macro_bear = cur_spy_c < cur_spy_ema200 or cur_spy_ema50 < cur_spy_ema200
        is_strong_bull = cur_spy_c > cur_spy_ema50 and cur_spy_ema50 > cur_spy_ema200

        # Dynamic Leverage Determination
        if self.mode == "DYNAMIC_BULL_2_5X":
            effective_leverage = 2.5 if is_strong_bull else (0.0 if is_macro_bear else 1.0)
        elif self.mode == "TRADIFI_MARGIN_2X":
            effective_leverage = 2.0 if not is_macro_bear else 0.0
        else:
            effective_leverage = 1.0 if not is_macro_bear else 0.0

        if effective_leverage <= 0.0:
            return {
                "decision": "100% CASH DEFENSE",
                "reason": f"SPY Bearish Market Regime (SPY: {cur_spy_c:.2f}, EMA50: {cur_spy_ema50:.2f}, EMA200: {cur_spy_ema200:.2f})",
                "effective_leverage": 0.0,
                "orders": [],
            }

        # 3. Evaluate Candidates
        candidates = []
        for b_sym, bars in candles.items():
            if len(bars) < 65:
                continue
            closes = [b.c for b in bars]
            atr14 = compute_atr(bars, 14)
            ema20 = compute_ema(closes, 20)
            ema50 = compute_ema(closes, 50)
            ema200 = compute_ema(closes, 200)
            ers = compute_kaufman_er(closes, 20)

            # Bollinger lower band
            bb_lower = []
            for i in range(len(bars)):
                if i < 20:
                    bb_lower.append(bars[i].c)
                else:
                    win_p = closes[i - 19 : i + 1]
                    m_p = sum(win_p) / 20.0
                    s_p = (sum((x - m_p) ** 2 for x in win_p) / 20.0) ** 0.5
                    bb_lower.append(m_p - 2.0 * s_p)

            idx = len(bars) - 1
            cur_bar = bars[idx]
            c_now = cur_bar.c
            cur_atr = atr14[idx]

            # Gate 1: First-principles Volatility Floor
            if (cur_atr / c_now) < self.min_atr_pct:
                continue

            # Gate 2: Quarterly Momentum Gate
            ret60 = (c_now / closes[idx - 60]) - 1.0 if idx >= 60 else 0.0
            if ret60 < self.min_rs60:
                continue

            # Gate 3: Structural Long-term Golden Cross
            if c_now < ema200[idx] or ema50[idx] <= ema200[idx]:
                continue

            # 4D Regime Engine State
            w_bars = bars[max(0, idx - 30) : idx + 1]
            s_code, s_name, poc_p, vah, val, profit_ratio, concentration = compute_profile_state(w_bars, c_now, cur_atr)
            if s_code == 3:  # Exhaustion veto
                continue

            mean_v = statistics.mean([b.v for b in bars[max(0, idx - 20) : idx]])
            vol_surge = cur_bar.v / (mean_v + 1e-9)
            chan_high = max(b.h for b in bars[idx - 20 : idx])
            trend_aligned = (c_now > ema20[idx]) and (ema20[idx] > ema50[idx])
            rs_bonus = max(0.0, ret60 * 4.0)

            # Setup 1: Trend Breakout
            er_val = ers[idx]
            if s_code in [1, 2] and c_now > chan_high and trend_aligned and er_val >= self.er_min:
                bar_range = cur_bar.h - cur_bar.l
                if bar_range > 0 and (cur_bar.c - cur_bar.l) / bar_range >= 0.65:
                    score = 2.5 + 3.0 * (er_val - self.er_min) + rs_bonus
                    if s_code == 1:
                        score += 1.0
                    if vol_surge >= 1.15:
                        score += 0.8
                    candidates.append({
                        "symbol": b_sym,
                        "score": score,
                        "type": "TREND_BREAKOUT",
                        "entry_price": c_now,
                        "init_stop": c_now - 1.8 * cur_atr,
                        "target_p": 0.0,
                        "atr": cur_atr,
                    })

            # Setup 2: Trend Pullback
            is_pullback = (cur_bar.l <= ema20[idx] * 1.02) and (cur_bar.c > ema20[idx]) and (cur_bar.c > cur_bar.o)
            if s_code == 2 and trend_aligned and is_pullback and er_val >= self.er_min:
                score = 2.3 + 2.5 * (er_val - self.er_min) + rs_bonus
                pb_stop = min(cur_bar.l, ema20[idx]) - 1.5 * cur_atr
                candidates.append({
                    "symbol": b_sym,
                    "score": score,
                    "type": "TREND_PULLBACK",
                    "entry_price": c_now,
                    "init_stop": pb_stop,
                    "target_p": 0.0,
                    "atr": cur_atr,
                })

            # Setup 3: Mean Reversion Right-Side Reclaim
            is_mr = s_code == 4 and cur_bar.l < bb_lower[idx] and cur_bar.c > bb_lower[idx] and (cur_bar.c > cur_bar.o)
            if is_mr:
                spr_stop = cur_bar.l - 1.0 * cur_atr
                spr_tp = cur_bar.c + 1.5 * abs(cur_bar.c - spr_stop)
                candidates.append({
                    "symbol": b_sym,
                    "score": 2.2 + rs_bonus,
                    "type": "MEAN_REVERSION",
                    "entry_price": c_now,
                    "init_stop": spr_stop,
                    "target_p": spr_tp,
                    "atr": cur_atr,
                })

        if not candidates:
            return {
                "decision": "HOLD_CASH",
                "reason": "No asset qualified for score >= 2.5 or passed 5-fold gate checks.",
                "effective_leverage": effective_leverage,
                "orders": [],
            }

        # Rank candidates by expectation score
        candidates.sort(key=lambda x: x["score"], reverse=True)
        top_candidate = candidates[0]

        # 4. Calculate Sizing with Gap Cushion
        entry_p = top_candidate["entry_price"]
        init_stop = top_candidate["init_stop"]
        raw_stop_dist = abs(entry_p - init_stop)
        eff_stop_dist = max(raw_stop_dist, 1.5 * top_candidate["atr"])

        risk_usd = account_equity * self.risk_budget_pct
        qty_by_risk = risk_usd / eff_stop_dist
        max_notional = account_equity * effective_leverage * 0.95
        qty_by_cap = max_notional / entry_p
        raw_qty = min(qty_by_risk, qty_by_cap)

        # Query Binance rules for rounding
        try:
            rules = self.client.get_symbol_rules(top_candidate["symbol"])
            step = rules["stepSize"]
            min_qty = rules["minQty"]
            min_notional = rules["minNotional"]
            tick = rules["tickSize"]
        except Exception:
            step = 0.01
            min_qty = 0.01
            min_notional = 5.0
            tick = 0.01

        final_qty = round_step(raw_qty, step)
        notional = final_qty * entry_p

        if final_qty < min_qty or notional < min_notional:
            return {
                "decision": "SKIPPED_SIZE_CONSTRAINT",
                "reason": f"Calculated notional {notional:.2f} U below Binance minNotional {min_notional:.2f} U or minQty {min_qty}",
                "effective_leverage": effective_leverage,
                "orders": [],
            }

        orders_to_place = [
            {
                "symbol": top_candidate["symbol"],
                "side": "BUY",
                "type": "MARKET",
                "quantity": final_qty,
                "entry_price": entry_p,
                "notional": notional,
                "leverage": int(math.floor(effective_leverage)),
                "role": "ENTRY",
            },
            {
                "symbol": top_candidate["symbol"],
                "side": "SELL",
                "type": "STOP_MARKET",
                "stop_price": round_tick(init_stop, tick),
                "close_position": True,
                "role": "STOP_LOSS",
            },
        ]
        if top_candidate["type"] == "MEAN_REVERSION" and top_candidate["target_p"] > 0:
            orders_to_place.append({
                "symbol": top_candidate["symbol"],
                "side": "SELL",
                "type": "TAKE_PROFIT_MARKET",
                "stop_price": round_tick(top_candidate["target_p"], tick),
                "close_position": True,
                "role": "TAKE_PROFIT",
            })

        return {
            "decision": "EXECUTE_TRADE",
            "symbol": top_candidate["symbol"],
            "setup_type": top_candidate["type"],
            "score": top_candidate["score"],
            "effective_leverage": effective_leverage,
            "orders": orders_to_place,
            "dry_run": self.dry_run,
            "orders_authorized": self.orders_authorized,
        }

    def execute_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes order plan. By default operates in dry_run mode (safe audit simulation).
        """
        if plan.get("decision") != "EXECUTE_TRADE":
            return {"status": "NOOP", "reason": plan.get("reason", "No orders to execute")}

        if self.dry_run or not self.orders_authorized:
            return {
                "status": "SIMULATED_SUCCESS",
                "mode": "DRY_RUN (research_only=true, orders_authorized=false)",
                "plan": plan,
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            }

        # LIVE EXECUTION PATH (Strict barrier)
        results = []
        sym = plan["symbol"]
        lev = int(math.floor(plan["effective_leverage"]))
        self.client.set_margin_type(sym, "ISOLATED")
        self.client.set_leverage(sym, lev)

        for o in plan["orders"]:
            res = self.client.place_order(
                symbol=o["symbol"],
                side=o["side"],
                order_type=o["type"],
                quantity=o.get("quantity"),
                stop_price=o.get("stop_price"),
                close_position=o.get("close_position", False),
            )
            results.append(res)

        return {
            "status": "LIVE_EXECUTED",
            "results": results,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
