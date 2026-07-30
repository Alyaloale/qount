"""L6 microstructure-edge research data layer (Phase 0).

This module is the data access layer for the L6 restart line: swap the
information source to A-share order-by-order Level-2 (Wind-format tick data) and
attack the IC term of ``IR = IC * sqrt(BR)`` with order-flow features, primarily
on T+0 ETFs (intraday round-trip; individual stocks are T+1 and mostly blocked).

Phase 0 scope ONLY: parse the three per-instrument Wind CSV files
(``行情.csv`` depth-10 snapshots, ``逐笔成交.csv`` trades, ``逐笔委托.csv`` orders),
exchange-aware (SZ vs SH cancel encoding differs), build a best-bid/ask mid-price
series, and provide strict as-of (no look-ahead) forward-return alignment. No
features, no IC, no strategy behavior (that is the Phase 1 kill-test).
research-only; nothing here is imported by the live / ``run-once`` path. stdlib
only (``csv``); no new dependencies.

Exchange semantics learned from the 20260407 sample (see
``memory/ashare-l2-tick-data.md``):

- Shenzhen (``*.SZ``): ``逐笔委托`` rows are all order *adds*, direction in the
  ``委托代码`` (B/S) column. Cancellations live in ``逐笔成交`` as rows where
  ``成交代码 == 'C'`` (cancelled qty, the non-zero one of 叫买序号/叫卖序号 is the
  cancelled order). Real trades have ``成交代码 == '0'`` and ``BS标志`` = aggressor.
- Shanghai (``*.SH``): ``逐笔委托`` uses ``委托类型`` ``A`` = add / ``D`` = delete
  (cancel) in the order stream; ``逐笔成交`` is all trades, ``BS标志`` = aggressor.

Prices are integers scaled by 1e4 (``111200`` -> ``11.12``). Times are
``HHMMSSmmm`` integers (``91500030`` -> 09:15:00.030).
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from bisect import bisect_left
from bisect import bisect_right
from pathlib import Path
from typing import Iterator

from qount.legacy.l3.l3_information_edge import _panel_effective_breadth
from qount.strategy_selection import _sharpe
from qount.strategy_selection import _t_stat
from qount.strategy_selection import compute_directional_deflated_sharpe
from qount.strategy_selection import compute_directional_pbo
from qount.strategy_selection import spearman_rank_correlation


L6_MICROSTRUCTURE_VERSION = "l6_microstructure_v1"

# Wind tick prices are integers in units of 1e-4 yuan.
PRICE_SCALE = 10000.0

# Source files are GBK-encoded exports.
SOURCE_ENCODING = "gbk"

ORDER_FILE = "逐笔委托.csv"
TRADE_FILE = "逐笔成交.csv"
QUOTE_FILE = "行情.csv"

DEPTH_LEVELS = 10


@dataclass(frozen=True)
class OrderEvent:
    """A single order-book event (add or cancel)."""

    time_ms: int
    side: str  # 'B' or 'S'
    price: float
    qty: int
    kind: str  # 'add' or 'cancel'
    order_type: str  # raw exchange order-type token (diagnostic)


@dataclass(frozen=True)
class TradeEvent:
    """A single executed trade."""

    time_ms: int
    price: float
    qty: int
    aggressor: str  # 'B' = buyer-initiated, 'S' = seller-initiated, '' = unknown
    buy_seq: int
    sell_seq: int


@dataclass(frozen=True)
class BookSnapshot:
    """A depth-10 order-book snapshot frame."""

    time_ms: int
    last: float
    bid_px: tuple[float, ...]
    bid_qty: tuple[int, ...]
    ask_px: tuple[float, ...]
    ask_qty: tuple[int, ...]

    @property
    def mid(self) -> float | None:
        """Best bid/ask midpoint; ``None`` if the top of book is one-sided."""
        if self.bid_px and self.ask_px and self.bid_px[0] > 0 and self.ask_px[0] > 0:
            return (self.bid_px[0] + self.ask_px[0]) / 2.0
        return None


def exchange_of(wind_code: str) -> str:
    """Return ``'SZ'`` or ``'SH'`` from a Wind code like ``000001.SZ``."""
    suffix = wind_code.strip().rsplit(".", 1)[-1].upper()
    if suffix in ("SZ", "SH"):
        return suffix
    raise ValueError(f"unrecognized Wind code suffix: {wind_code!r}")


def parse_session_time_to_ms(raw: str | int) -> int:
    """``HHMMSSmmm`` integer -> milliseconds since midnight.

    ``91500030`` -> 09:15:00.030 -> 33300030; ``150000000`` -> 15:00:00.000.
    """
    n = int(raw)
    ms = n % 1000
    rest = n // 1000
    sec = rest % 100
    rest //= 100
    minute = rest % 100
    hour = rest // 100
    return ((hour * 60 + minute) * 60 + sec) * 1000 + ms


def _parse_price(raw: str) -> float:
    raw = (raw or "").strip()
    return int(raw) / PRICE_SCALE if raw else 0.0


def _parse_int(raw: str) -> int:
    raw = (raw or "").strip()
    return int(raw) if raw else 0


def _read_rows(path: str | Path) -> Iterator[dict[str, str]]:
    """Yield header-keyed rows from a GBK CSV, stripping the trailing empty col."""
    with open(path, "r", encoding=SOURCE_ENCODING, newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            return
        header = [h.strip() for h in header]
        for raw in reader:
            if not raw or all(not c.strip() for c in raw):
                continue
            yield {header[i]: (raw[i] if i < len(raw) else "") for i in range(len(header))}


def _require_columns(row: dict[str, str], needed: tuple[str, ...], path: str | Path) -> None:
    missing = [c for c in needed if c not in row]
    if missing:
        raise ValueError(f"{path}: missing expected columns {missing}; got {list(row)}")


def parse_orders(path: str | Path) -> list[OrderEvent]:
    """Parse ``逐笔委托.csv`` into order events (exchange-aware).

    The encoding is detected from the ``委托类型`` content, NOT the Wind suffix:
    this dataset mislabels some SH instruments (A/D order stream) with a ``.SZ``
    suffix, so trusting the suffix would silently turn ``D`` cancels into fake
    adds. SH add/delete stream: ``A`` = add, ``D`` = cancel, ``S`` = status (not a
    book event). SZ stream: every row is an add (limit ``0``/``2``, market ``1``,
    best ``U``). Cancels for SZ live in ``逐笔成交`` (see :func:`parse_trades`).
    """
    out: list[OrderEvent] = []
    for row in _read_rows(path):
        _require_columns(row, ("万得代码", "时间", "委托类型", "委托代码", "委托价格", "委托数量"), path)
        otype = (row["委托类型"] or "").strip()
        side = (row["委托代码"] or "").strip().upper()
        token = otype.upper()
        if token in ("A", "D"):  # SH add/delete order stream (content-detected)
            kind = "add" if token == "A" else "cancel"
        elif token == "S":  # SH status record, not a book event
            kind = "other"
        else:  # SZ order stream: every row is an add
            kind = "add"
        out.append(
            OrderEvent(
                time_ms=parse_session_time_to_ms(row["时间"]),
                side=side,
                price=_parse_price(row["委托价格"]),
                qty=_parse_int(row["委托数量"]),
                kind=kind,
                order_type=otype,
            )
        )
    return out


def parse_trades(path: str | Path) -> tuple[list[TradeEvent], list[OrderEvent]]:
    """Parse ``逐笔成交.csv`` -> (trades, cancels).

    SZ encodes cancellations here (``成交代码 == 'C'``); they are returned as
    ``OrderEvent(kind='cancel')`` so callers get a unified cancel stream. SH has
    no cancels in this file, so the second list is empty.
    """
    trades: list[TradeEvent] = []
    cancels: list[OrderEvent] = []
    for row in _read_rows(path):
        _require_columns(
            row,
            ("万得代码", "时间", "成交代码", "BS标志", "成交价格", "成交数量", "叫卖序号", "叫买序号"),
            path,
        )
        time_ms = parse_session_time_to_ms(row["时间"])
        code = (row["成交代码"] or "").strip().upper()
        qty = _parse_int(row["成交数量"])
        buy_seq = _parse_int(row["叫买序号"])
        sell_seq = _parse_int(row["叫卖序号"])
        if code == "C":  # SZ cancellation record
            side = "B" if buy_seq > 0 else "S"
            cancels.append(
                OrderEvent(
                    time_ms=time_ms,
                    side=side,
                    price=_parse_price(row["成交价格"]),
                    qty=qty,
                    kind="cancel",
                    order_type="C",
                )
            )
            continue
        trades.append(
            TradeEvent(
                time_ms=time_ms,
                price=_parse_price(row["成交价格"]),
                qty=qty,
                aggressor=(row["BS标志"] or "").strip().upper(),
                buy_seq=buy_seq,
                sell_seq=sell_seq,
            )
        )
    return trades, cancels


def parse_snapshots(path: str | Path) -> list[BookSnapshot]:
    """Parse ``行情.csv`` into depth-10 order-book snapshot frames."""
    out: list[BookSnapshot] = []
    bid_px_cols = tuple(f"申买价{i}" for i in range(1, DEPTH_LEVELS + 1))
    bid_qty_cols = tuple(f"申买量{i}" for i in range(1, DEPTH_LEVELS + 1))
    ask_px_cols = tuple(f"申卖价{i}" for i in range(1, DEPTH_LEVELS + 1))
    ask_qty_cols = tuple(f"申卖量{i}" for i in range(1, DEPTH_LEVELS + 1))
    for row in _read_rows(path):
        _require_columns(row, ("时间", "成交价") + bid_px_cols + ask_px_cols, path)
        out.append(
            BookSnapshot(
                time_ms=parse_session_time_to_ms(row["时间"]),
                last=_parse_price(row["成交价"]),
                bid_px=tuple(_parse_price(row[c]) for c in bid_px_cols),
                bid_qty=tuple(_parse_int(row[c]) for c in bid_qty_cols),
                ask_px=tuple(_parse_price(row[c]) for c in ask_px_cols),
                ask_qty=tuple(_parse_int(row[c]) for c in ask_qty_cols),
            )
        )
    return out


def mid_price_series(snapshots: list[BookSnapshot]) -> tuple[list[int], list[float]]:
    """Return (times_ms, mids) for snapshots with a valid two-sided top of book.

    Times are guaranteed non-decreasing (input order preserved); frames with a
    one-sided/empty book (mid is None) are dropped.
    """
    times: list[int] = []
    mids: list[float] = []
    for snap in snapshots:
        mid = snap.mid
        if mid is not None:
            times.append(snap.time_ms)
            mids.append(mid)
    return times, mids


def as_of_price(times: list[int], mids: list[float], t: int) -> float | None:
    """Last observed mid at or before ``t`` (strict no look-ahead).

    Returns ``None`` if ``t`` precedes the first observation. Uses the most recent
    price with ``time <= t`` and never a future one.
    """
    idx = bisect_right(times, t) - 1
    if idx < 0:
        return None
    return mids[idx]


def forward_return(
    times: list[int],
    mids: list[float],
    t0: int,
    horizon_ms: int,
) -> float | None:
    """As-of forward mid return over ``[t0, t0 + horizon_ms]``.

    The decision-time anchor uses only data ``<= t0`` (no look-ahead). Returns
    ``None`` if there is no anchor at/before ``t0`` or the series does not extend
    to ``t0 + horizon_ms`` (the horizon is not realizable, e.g. past the close) —
    the forward price is never fabricated by clamping to the last frame.
    """
    if horizon_ms <= 0:
        raise ValueError("horizon_ms must be positive")
    if not times or times[-1] < t0 + horizon_ms:
        return None
    now = as_of_price(times, mids, t0)
    future = as_of_price(times, mids, t0 + horizon_ms)
    if now is None or future is None or now <= 0:
        return None
    return future / now - 1.0


# ----------------------------------------------------------------------------
# Phase 1: order-flow features + IC-vs-horizon kill-test.
#
# The decisive question (same shape as L4's latency wall): how much of the
# order-flow IC survives at a horizon a latency-insensitive operator can act on?
# We measure rank-IC of each feature vs forward mid return across a horizon grid;
# sub-minute horizons are IC-only (cannot be traded T+0 without colocation and
# the m/h/d annualization harness has no seconds), and horizons >= 1min get the
# full LS economics (Sharpe / DSR / PBO / break-even) reused from the §7 harness.
# ----------------------------------------------------------------------------

# Horizon grid in ms. Sub-minute frames map the decay shape; >= 60s are actionable.
HORIZONS_MS: tuple[int, ...] = (3_000, 10_000, 30_000, 60_000, 180_000, 300_000, 600_000, 1_800_000)
ACTIONABLE_MIN_MS = 60_000
_FREQ_BY_MS = {60_000: "1m", 180_000: "3m", 300_000: "5m", 600_000: "10m", 1_800_000: "30m"}

FEATURES: tuple[str, ...] = ("ofi", "depth_imbalance", "micro_price_dev", "trade_sign_imbalance")
DEPTH_K = 5  # levels for depth imbalance
TRADE_SIGN_WINDOW_MS = 60_000  # trailing window for trade-sign and OFI accumulation

# Breadth-adjusted reference: the daily/cross-section ceiling this line must beat.
L6_IC_GATE = 0.05


@dataclass(frozen=True)
class FrameFeatures:
    time_ms: int
    depth_imbalance: float
    micro_price_dev: float
    per_frame_ofi: float  # OFI vs the previous valid frame (accumulated later)


def _l1_ofi(prev: BookSnapshot, cur: BookSnapshot) -> float:
    """Best-level order-flow imbalance (Cont, Kukanov & Stoikov 2014)."""
    pb, cb = prev.bid_px[0], cur.bid_px[0]
    pa, ca = prev.ask_px[0], cur.ask_px[0]
    bid_term = (cb >= pb) * cur.bid_qty[0] - (cb <= pb) * prev.bid_qty[0]
    ask_term = (ca <= pa) * cur.ask_qty[0] - (ca >= pa) * prev.ask_qty[0]
    return float(bid_term - ask_term)


def _depth_imbalance(snap: BookSnapshot, k: int) -> float:
    b = sum(snap.bid_qty[:k])
    a = sum(snap.ask_qty[:k])
    return (b - a) / (b + a) if (b + a) > 0 else 0.0


def _micro_price_dev(snap: BookSnapshot) -> float:
    b1, a1 = snap.bid_px[0], snap.ask_px[0]
    bq, aq = snap.bid_qty[0], snap.ask_qty[0]
    if bq + aq <= 0 or (b1 + a1) <= 0:
        return 0.0
    micro = (aq * b1 + bq * a1) / (bq + aq)  # opposite-side weighting
    mid = (b1 + a1) / 2.0
    return (micro - mid) / mid


def build_frame_features(snapshots: list[BookSnapshot]) -> tuple[list[int], list[float], list[FrameFeatures]]:
    """Return (times, mids, features) for valid two-sided frames, in time order."""
    times: list[int] = []
    mids: list[float] = []
    feats: list[FrameFeatures] = []
    prev: BookSnapshot | None = None
    for snap in snapshots:
        mid = snap.mid
        if mid is None:
            continue
        ofi = _l1_ofi(prev, snap) if prev is not None else 0.0
        times.append(snap.time_ms)
        mids.append(mid)
        feats.append(FrameFeatures(
            time_ms=snap.time_ms,
            depth_imbalance=_depth_imbalance(snap, DEPTH_K),
            micro_price_dev=_micro_price_dev(snap),
            per_frame_ofi=ofi,
        ))
        prev = snap
    return times, mids, feats


def _trailing_signed_trade_imbalance(
    trade_times: list[int],
    cum_signed: list[float],
    cum_total: list[float],
    t: int,
    window_ms: int,
) -> float:
    """Net signed volume over ``(t-window, t]`` / total volume (no look-ahead)."""
    hi = bisect_right(trade_times, t)
    lo = bisect_left(trade_times, t - window_ms)
    if hi <= lo:
        return 0.0
    signed = cum_signed[hi] - cum_signed[lo]
    total = cum_total[hi] - cum_total[lo]
    return signed / total if total > 0 else 0.0


def _trailing_ofi(times: list[int], cum_ofi: list[float], i: int, window_ms: int) -> float:
    """Accumulated per-frame OFI over the trailing window ending at frame ``i``."""
    lo = bisect_left(times, times[i] - window_ms)
    return cum_ofi[i + 1] - cum_ofi[lo]


def _feature_value(name: str, feats: list[FrameFeatures], i: int, times: list[int],
                   cum_ofi: list[float], trade_times: list[int],
                   cum_signed: list[float], cum_total: list[float]) -> float:
    if name == "ofi":
        return _trailing_ofi(times, cum_ofi, i, TRADE_SIGN_WINDOW_MS)
    if name == "depth_imbalance":
        return feats[i].depth_imbalance
    if name == "micro_price_dev":
        return feats[i].micro_price_dev
    if name == "trade_sign_imbalance":
        return _trailing_signed_trade_imbalance(
            trade_times, cum_signed, cum_total, times[i], TRADE_SIGN_WINDOW_MS)
    raise ValueError(f"unknown feature {name!r}")


def evaluate_instrument(
    snapshots: list[BookSnapshot],
    trades: list[TradeEvent],
    horizons_ms: tuple[int, ...] = HORIZONS_MS,
) -> dict[str, dict[int, dict[str, object]]]:
    """Per-instrument: for each (feature, horizon) collect non-overlapping
    (feature, forward-return) pairs via stride sampling, return rank-IC + the
    sign(feature)*forward-return long-short series (gross, pre-cost)."""
    times, mids, feats = build_frame_features(snapshots)
    out: dict[str, dict[int, dict[str, object]]] = {f: {} for f in FEATURES}
    if len(times) < 2:
        return out

    cum_ofi = [0.0]
    for fr in feats:
        cum_ofi.append(cum_ofi[-1] + fr.per_frame_ofi)

    trade_times = [tr.time_ms for tr in trades]
    cum_signed = [0.0]
    cum_total = [0.0]
    for tr in trades:
        s = tr.qty if tr.aggressor == "B" else (-tr.qty if tr.aggressor == "S" else 0)
        cum_signed.append(cum_signed[-1] + s)
        cum_total.append(cum_total[-1] + (tr.qty if tr.aggressor in ("B", "S") else 0))

    for h in horizons_ms:
        # stride sampling: decision points spaced >= h apart (non-overlapping labels).
        decisions: list[int] = []
        last_t = None
        for i in range(len(times)):
            if last_t is None or times[i] - last_t >= h:
                fr = forward_return(times, mids, times[i], h)
                if fr is None:
                    continue
                decisions.append(i)
                last_t = times[i]
        if len(decisions) < 3:
            continue
        fwd = [forward_return(times, mids, times[i], h) for i in decisions]
        for name in FEATURES:
            xs = [_feature_value(name, feats, i, times, cum_ofi, trade_times, cum_signed, cum_total)
                  for i in decisions]
            ic = spearman_rank_correlation(xs, fwd)
            ls = [(1.0 if x > 0 else -1.0) * r for x, r in zip(xs, fwd)]
            out[name][h] = {
                "rank_ic": ic,
                "n": len(decisions),
                "ls_returns": ls,
                "gross_mean": sum(ls) / len(ls),
            }
    return out


def _load_instrument(data_dir: Path, symbol: str) -> tuple[list[BookSnapshot], list[TradeEvent]]:
    d = data_dir / symbol
    snaps = parse_snapshots(d / QUOTE_FILE)
    trades, _cancels = parse_trades(d / TRADE_FILE)
    return snaps, trades


def run_l6_microstructure_ic_scan(
    data_dir: str | Path,
    symbols: list[str],
    *,
    horizons_ms: tuple[int, ...] = HORIZONS_MS,
    cost_per_side_pct: float = 0.0005,
    ic_gate: float = L6_IC_GATE,
    holdout_role: str = "discovery",
) -> dict[str, object]:
    """L6 Phase 1 kill-test: order-flow IC-vs-horizon decay across T+0 ETFs.

    research-only. Reads the local Wind tick slice; no network, no orders.
    """
    data_dir = Path(data_dir)
    per_symbol = {s: evaluate_instrument(*_load_instrument(data_dir, s), horizons_ms=horizons_ms)
                  for s in symbols}

    grid: list[dict[str, object]] = []
    cells_for_harness: list[dict[str, object]] = []
    for name in FEATURES:
        for h in horizons_ms:
            ics = [per_symbol[s][name][h]["rank_ic"] for s in symbols
                   if h in per_symbol[s][name] and per_symbol[s][name][h]["rank_ic"] is not None]
            if not ics:
                continue
            mean_ic = sum(ics) / len(ics)
            sign = 1 if mean_ic >= 0 else -1
            sign_stability = sum(1 for v in ics if (v >= 0) == (sign >= 0)) / len(ics)
            pooled_ls = [r for s in symbols if h in per_symbol[s][name]
                         for r in per_symbol[s][name][h]["ls_returns"]]
            gross_mean = sum(pooled_ls) / len(pooled_ls) if pooled_ls else 0.0
            break_even_round_trip = gross_mean  # per-decision gross vs round-trip cost
            actionable = h >= ACTIONABLE_MIN_MS
            cell = {
                "feature": name,
                "horizon_ms": h,
                "actionable": actionable,
                "n_symbols": len(ics),
                "mean_rank_ic": mean_ic,
                "ic_sign_stability": sign_stability,
                "cross_etf_ic_tstat": _t_stat(ics),
                "gross_mean_per_decision": gross_mean,
                "break_even_round_trip_cost": break_even_round_trip,
                "net_per_decision": gross_mean - 2.0 * cost_per_side_pct,
                "n_decisions_pooled": len(pooled_ls),
            }
            grid.append(cell)
            if actionable and h in _FREQ_BY_MS and len(pooled_ls) >= 2:
                freq = _FREQ_BY_MS[h]
                cells_for_harness.append({
                    "feature": name,
                    "family": name,
                    "frequency": freq,
                    "horizon_ms": h,
                    "portfolio_sharpe": _sharpe(pooled_ls, freq),
                    "portfolio_period_count": len(pooled_ls),
                    "period_returns_by_timestamp": {i: r for i, r in enumerate(pooled_ls)},
                })

    actionable_cells = [c for c in grid if c["actionable"] and c["mean_rank_ic"] is not None]
    best = max(actionable_cells, key=lambda c: abs(c["mean_rank_ic"]), default=None)
    dsr = compute_directional_deflated_sharpe(cells_for_harness)
    pbo = compute_directional_pbo(cells_for_harness)

    decision = "l6_microstructure_no_actionable_signal"
    if best is not None:
        passes = (
            abs(best["mean_rank_ic"]) > ic_gate
            and best["ic_sign_stability"] >= 0.6
            and best["net_per_decision"] > 0.0
        )
        if passes:
            decision = "l6_microstructure_passes_phase1"
        else:
            # is there sub-minute IC that dies before the actionable wall?
            sub = [c for c in grid if not c["actionable"] and c["mean_rank_ic"] is not None]
            sub_best = max(sub, key=lambda c: abs(c["mean_rank_ic"]), default=None)
            if sub_best is not None and abs(sub_best["mean_rank_ic"]) > ic_gate >= abs(best["mean_rank_ic"]):
                decision = "l6_latency_wall_subminute_only"
            else:
                decision = "l6_microstructure_below_gate"

    return {
        "version": L6_MICROSTRUCTURE_VERSION,
        "holdout_role": holdout_role,
        "symbols": symbols,
        "horizons_ms": list(horizons_ms),
        "cost_per_side_pct": cost_per_side_pct,
        "ic_gate": ic_gate,
        "ic_horizon_grid": sorted(grid, key=lambda c: (c["feature"], c["horizon_ms"])),
        "best_actionable_cell": best,
        "deflated_sharpe": dsr,
        "pbo": pbo,
        "decision": decision,
    }


# ----------------------------------------------------------------------------
# L6-daily (main line): L2-derived DAILY informed-flow features.
#
# Intraday is shelved (amplitude < cost). At daily horizon cost is negligible
# (1-3% moves vs ~10bp) and individual-stock breadth is far higher. The bet is
# that tick-reconstructed *true* informed flow beats the ~0.06 daily IC ceiling
# that the broker's crude size-bucketed 主力净流入 (found reverse) and price/volume
# already failed. These features are one vector per (stock, day): the 6TB of raw
# tick collapses to a tiny panel after a one-pass ETL. research-only.
# ----------------------------------------------------------------------------

# Session boundaries, ms since midnight (A-share continuous + close auction).
_OPEN_MS = parse_session_time_to_ms(93000000)            # 09:30:00
_EARLY_END_MS = parse_session_time_to_ms(100000000)      # 10:00:00
_LATE_START_MS = parse_session_time_to_ms(143000000)     # 14:30:00
_CLOSE_AUCTION_MS = parse_session_time_to_ms(145700000)  # 14:57:00
_CLOSE_MS = parse_session_time_to_ms(150000000)          # 15:00:00

DAILY_FEATURES: tuple[str, ...] = (
    "aggressive_ofi",
    "large_aggr_ofi",
    "late_minus_early_flow",
    "close_auction_imbalance",
    "cancel_imbalance",
)


def _signed_vol(trades: list[TradeEvent], t0: int, t1: int) -> tuple[float, float]:
    """(buy_vol, sell_vol) for aggressor-signed trades with t0 <= time < t1."""
    buy = sell = 0.0
    for tr in trades:
        if t0 <= tr.time_ms < t1:
            if tr.aggressor == "B":
                buy += tr.qty
            elif tr.aggressor == "S":
                sell += tr.qty
    return buy, sell


def _imbalance(buy: float, sell: float) -> float:
    tot = buy + sell
    return (buy - sell) / tot if tot > 0 else 0.0


def _percentile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(q * len(s)))
    return float(s[idx])


def daily_flow_features(
    snapshots: list[BookSnapshot],
    trades: list[TradeEvent],
    cancels: list[OrderEvent],
) -> dict[str, float] | None:
    """One informed-flow feature vector for a (stock, day). ``None`` if halted/empty.

    ``cancels`` is the unified cancel stream: SZ from :func:`parse_trades`, SH the
    ``kind == 'cancel'`` entries from :func:`parse_orders`.
    """
    signed = [tr for tr in trades if tr.aggressor in ("B", "S")]
    if not signed:
        return None
    total = float(sum(tr.qty for tr in signed))
    if total <= 0:
        return None

    buy = sum(tr.qty for tr in signed if tr.aggressor == "B")
    sell = total - buy
    aggressive_ofi = _imbalance(buy, sell)

    p90 = _percentile([tr.qty for tr in signed], 0.90)
    large = [tr for tr in signed if tr.qty >= p90]
    lb = sum(tr.qty for tr in large if tr.aggressor == "B")
    ls = sum(tr.qty for tr in large if tr.aggressor == "S")
    large_aggr_ofi = _imbalance(lb, ls)

    eb, es = _signed_vol(signed, _OPEN_MS, _EARLY_END_MS)
    lb2, ls2 = _signed_vol(signed, _LATE_START_MS, _CLOSE_MS)
    late_minus_early = _imbalance(lb2, ls2) - _imbalance(eb, es)

    cb, cs = _signed_vol(signed, _CLOSE_AUCTION_MS, _CLOSE_MS + 1)
    close_auction_imbalance = _imbalance(cb, cs)

    cancel_buy = sum(c.qty for c in cancels if c.side == "B")
    cancel_sell = sum(c.qty for c in cancels if c.side == "S")
    cancel_imbalance = _imbalance(cancel_buy, cancel_sell)

    _times, mids = mid_price_series(snapshots)
    # Quoted relative spread (bps) over two-sided continuous-session snapshots: the
    # empirical taker round-trip cost proxy for the close_auction T+0 line (B).
    rel_spreads = [
        (s.ask_px[0] - s.bid_px[0]) / ((s.bid_px[0] + s.ask_px[0]) / 2.0)
        for s in snapshots
        if s.bid_px and s.ask_px and s.bid_px[0] > 0 and s.ask_px[0] > 0
    ]
    quoted_spread_bps = (sum(rel_spreads) / len(rel_spreads) * 1.0e4) if rel_spreads else 0.0
    return {
        "aggressive_ofi": aggressive_ofi,
        "large_aggr_ofi": large_aggr_ofi,
        "late_minus_early_flow": late_minus_early,
        "close_auction_imbalance": close_auction_imbalance,
        "cancel_imbalance": cancel_imbalance,
        "day_open": mids[0] if mids else 0.0,
        "day_close": mids[-1] if mids else 0.0,
        "quoted_spread_bps": quoted_spread_bps,
        "n_trades": float(len(signed)),
        "day_volume": total,
    }


def compute_daily_feature_panel(
    day_dir: str | Path,
    symbols: list[str],
) -> dict[str, dict[str, float]]:
    """ETL: per-(stock) daily informed-flow features for one trading day.

    The expensive 6TB pass; the output panel is tiny. Halted/empty stocks are
    skipped. research-only; reads local Wind tick folders, no network.
    """
    day_dir = Path(day_dir)
    panel: dict[str, dict[str, float]] = {}
    for sym in symbols:
        try:
            snaps, trades = _load_instrument(day_dir, sym)
            _t, sz_cancels = parse_trades(day_dir / sym / TRADE_FILE)
            orders = parse_orders(day_dir / sym / ORDER_FILE)
        except FileNotFoundError:
            continue
        cancels = sz_cancels + [o for o in orders if o.kind == "cancel"]
        feats = daily_flow_features(snaps, trades, cancels)
        if feats is not None:
            panel[sym] = feats
    return panel


# ----------------------------------------------------------------------------
# D1: cross-day cross-section rank-IC of the daily informed-flow features.
#
# T-day feature -> (T+h)-day close-to-close return, ranked cross-sectionally each
# day; IC aggregated across days with sign stability. Reports top/bottom-decile
# long-short Sharpe, `_panel_effective_breadth` on the forward-return panel (the
# breadth wall that pinned price/volume at ~1.6 — the decisive question for the
# ETF universe), and DSR/PBO across the feature trials. Universe is all / etf /
# top-N most-liquid (turnover proxy = day_volume * day_close); the active ETF
# subset is exactly where the breadth thesis is tested. research-only.
# ----------------------------------------------------------------------------

L6_DAILY_IC_GATE = 0.06
L6_DAILY_BREADTH_GATE = 2.5  # escape threshold; ETF cross-section historically ~1.7

_ETF_CODE_RE = re.compile(r"^(159|51[0-8]|56[0-3]|588)\d")


def is_etf_code(wind_code: str) -> bool:
    """True for exchange-traded funds by A-share code block (suffix-agnostic)."""
    return bool(_ETF_CODE_RE.match(wind_code.split(".")[0]))


def load_daily_panels(paths: list[str | Path]) -> dict[str, dict[str, dict]]:
    """Load D0 panel JSONs keyed by trading day (the day_dir folder name)."""
    out: dict[str, dict[str, dict]] = {}
    for p in paths:
        d = json.loads(Path(p).read_text())
        date = Path(d["day_dir"]).name
        out[date] = d["features"]
    return out


def _decile_long_short(xs: list[float], ys: list[float], top_fraction: float) -> float | None:
    """mean(top-fraction fwd) - mean(bottom-fraction fwd), ranked by feature."""
    pairs = sorted(zip(xs, ys), key=lambda t: t[0])
    n = len(pairs)
    k = max(1, int(n * top_fraction))
    if 2 * k > n:
        return None
    bottom = sum(y for _x, y in pairs[:k]) / k
    top = sum(y for _x, y in pairs[-k:]) / k
    return top - bottom


def evaluate_l6_daily_d1(
    panels: dict[str, dict[str, dict]],
    *,
    feature_names: tuple[str, ...] = DAILY_FEATURES,
    universe: str = "etf",
    active_top_n: int | None = None,
    holding: int = 1,
    top_fraction: float = 0.2,
    ic_gate: float = L6_DAILY_IC_GATE,
    breadth_gate: float = L6_DAILY_BREADTH_GATE,
    min_cross_section: int = 10,
) -> dict[str, object]:
    """Cross-day cross-section rank-IC kill-test (D1). research-only.

    ``panels`` maps trading-day -> {symbol: D0 feature vector}. No look-ahead:
    the T-day feature predicts the (T+holding)-day close-to-close return.
    """
    dates = sorted(panels)
    fwd_panel: dict[str, list[float | None]] = {}
    per_feat_ic: dict[str, list[float]] = {f: [] for f in feature_names}
    per_feat_ls: dict[str, list[float]] = {f: [] for f in feature_names}
    pair_dates: list[str] = []

    for i in range(len(dates) - holding):
        t, t1 = dates[i], dates[i + holding]
        pt, pt1 = panels[t], panels[t1]
        syms = [s for s in pt if s in pt1]
        if universe == "etf":
            syms = [s for s in syms if is_etf_code(s)]
        if active_top_n:
            syms = sorted(
                syms,
                key=lambda s: pt[s].get("day_volume", 0.0) * pt[s].get("day_close", 0.0),
                reverse=True,
            )[:active_top_n]
        fwd: dict[str, float] = {}
        for s in syms:
            c0 = pt[s].get("day_close", 0.0)
            c1 = pt1[s].get("day_close", 0.0)
            if c0 > 0 and c1 > 0:
                fwd[s] = c1 / c0 - 1.0
        valid = [s for s in syms if s in fwd]
        if len(valid) < min_cross_section:
            continue
        pair_dates.append(f"{t}->{t1}")
        col = len(pair_dates) - 1
        for s in valid:
            lst = fwd_panel.setdefault(s, [])
            while len(lst) < col:
                lst.append(None)
            lst.append(fwd[s])
        for f in feature_names:
            xs = [pt[s][f] for s in valid]
            ys = [fwd[s] for s in valid]
            ic = spearman_rank_correlation(xs, ys)
            if ic is not None:
                per_feat_ic[f].append(ic)
            ls = _decile_long_short(xs, ys, top_fraction)
            if ls is not None:
                per_feat_ls[f].append(ls)

    ncol = len(pair_dates)
    for lst in fwd_panel.values():
        while len(lst) < ncol:
            lst.append(None)
    breadth = _panel_effective_breadth(fwd_panel)

    feature_rows: list[dict[str, object]] = []
    cells: list[dict[str, object]] = []
    for f in feature_names:
        ics = per_feat_ic[f]
        ls = per_feat_ls[f]
        if not ics:
            continue
        mean_ic = sum(ics) / len(ics)
        sign = 1 if mean_ic >= 0 else -1
        sign_stab = sum(1 for v in ics if (v >= 0) == (sign >= 0)) / len(ics)
        feature_rows.append({
            "feature": f,
            "n_days": len(ics),
            "mean_rank_ic": mean_ic,
            "ic_t_stat": _t_stat(ics),
            "ic_sign_stability": sign_stab,
            "ls_decile_sharpe": _sharpe(ls, "1d") if len(ls) >= 2 else None,
            "ls_decile_mean": (sum(ls) / len(ls)) if ls else None,
        })
        if len(ls) >= 2:
            cells.append({
                "feature": f, "family": f, "frequency": "1d",
                "portfolio_sharpe": _sharpe(ls, "1d"),
                "portfolio_period_count": len(ls),
                "period_returns_by_timestamp": {i: r for i, r in enumerate(ls)},
            })

    best = max(feature_rows, key=lambda r: abs(r["mean_rank_ic"]), default=None)
    dsr = compute_directional_deflated_sharpe(cells)
    pbo = compute_directional_pbo(cells)

    decision = "l6_daily_d1_no_signal"
    if best is not None:
        ic_ok = abs(best["mean_rank_ic"]) > ic_gate and best["ic_sign_stability"] >= 0.6
        breadth_ok = breadth["effective_breadth"] >= breadth_gate
        if ic_ok and breadth_ok:
            decision = "l6_daily_d1_passes"
        elif ic_ok and not breadth_ok:
            decision = "l6_daily_d1_ic_ok_breadth_wall"
        else:
            decision = "l6_daily_d1_below_gate"

    return {
        "version": L6_MICROSTRUCTURE_VERSION,
        "universe": universe,
        "active_top_n": active_top_n,
        "holding": holding,
        "top_fraction": top_fraction,
        "ic_gate": ic_gate,
        "breadth_gate": breadth_gate,
        "n_trading_days": len(dates),
        "n_cross_sections": ncol,
        "pair_dates": pair_dates,
        "effective_breadth": breadth,
        "feature_ic": sorted(feature_rows, key=lambda r: -abs(r["mean_rank_ic"])),
        "best_feature": best,
        "deflated_sharpe": dsr,
        "pbo": pbo,
        "decision": decision,
    }


# ----------------------------------------------------------------------------
# D2: incremental-IC gate. Is the informed-flow signal new information, or just a
# re-skin of the crowded short-term price/volume reversal? Partial rank-IC of the
# target feature vs forward return, CONTROLLING the trailing close-to-close return
# (the price/volume baseline). If the partial IC keeps most of the raw IC and the
# same sign -> incremental (real new info, worth pursuing); if it collapses -> the
# signal is subsumed by price/volume and L6-daily stops per §7. research-only.
# ----------------------------------------------------------------------------


def _partial_corr(r_xy: float, r_xz: float, r_yz: float) -> float | None:
    """First-order partial correlation of x,y controlling z (rank inputs)."""
    denom = ((1.0 - r_xz * r_xz) * (1.0 - r_yz * r_yz)) ** 0.5
    if denom <= 1e-12:
        return None
    return (r_xy - r_xz * r_yz) / denom


def evaluate_l6_daily_d2(
    panels: dict[str, dict[str, dict]],
    *,
    target_feature: str = "close_auction_imbalance",
    baseline_lookback: int = 1,
    universe: str = "etf",
    active_top_n: int | None = None,
    holding: int = 1,
    min_cross_section: int = 10,
    retain_fraction: float = 0.5,
) -> dict[str, object]:
    """D2 incremental-IC kill-test: target feature vs forward return, controlling
    the trailing close-to-close return (price/volume baseline). research-only."""
    dates = sorted(panels)
    raw: list[float] = []
    partial: list[float] = []
    base: list[float] = []
    feat_vs_base: list[float] = []
    for i in range(baseline_lookback, len(dates) - holding):
        t, t1, tp = dates[i], dates[i + holding], dates[i - baseline_lookback]
        pt, pt1, pp = panels[t], panels[t1], panels[tp]
        syms = [s for s in pt if s in pt1 and s in pp]
        if universe == "etf":
            syms = [s for s in syms if is_etf_code(s)]
        if active_top_n:
            syms = sorted(
                syms,
                key=lambda s: pt[s].get("day_volume", 0.0) * pt[s].get("day_close", 0.0),
                reverse=True,
            )[:active_top_n]
        xs: list[float] = []
        zs: list[float] = []
        ys: list[float] = []
        for s in syms:
            c0 = pt[s].get("day_close", 0.0)
            c1 = pt1[s].get("day_close", 0.0)
            cp = pp[s].get("day_close", 0.0)
            tgt = pt[s].get(target_feature)
            if c0 > 0 and c1 > 0 and cp > 0 and tgt is not None:
                xs.append(tgt)
                zs.append(c0 / cp - 1.0)   # trailing return = price/volume baseline
                ys.append(c1 / c0 - 1.0)   # forward return
        if len(xs) < min_cross_section:
            continue
        r_xy = spearman_rank_correlation(xs, ys)
        r_xz = spearman_rank_correlation(xs, zs)
        r_yz = spearman_rank_correlation(zs, ys)
        if r_xy is None or r_xz is None or r_yz is None:
            continue
        raw.append(r_xy)
        base.append(r_yz)
        feat_vs_base.append(r_xz)
        pc = _partial_corr(r_xy, r_xz, r_yz)
        if pc is not None:
            partial.append(pc)

    def _agg(v: list[float]) -> dict[str, object] | None:
        if not v:
            return None
        m = sum(v) / len(v)
        return {"mean": m, "t_stat": _t_stat(v), "n": len(v)}

    raw_a, par_a, base_a, fb_a = _agg(raw), _agg(partial), _agg(base), _agg(feat_vs_base)
    ratio = None
    if raw_a and par_a and raw_a["mean"] != 0:
        ratio = par_a["mean"] / raw_a["mean"]

    decision = "l6_d2_no_data"
    if raw_a and par_a:
        same_sign = (par_a["mean"] >= 0) == (raw_a["mean"] >= 0)
        retained = abs(par_a["mean"]) >= retain_fraction * abs(raw_a["mean"])
        decision = "l6_d2_incremental" if (same_sign and retained) else "l6_d2_subsumed_by_pricevol"

    return {
        "version": L6_MICROSTRUCTURE_VERSION,
        "target_feature": target_feature,
        "baseline": f"trailing_return_lb{baseline_lookback}",
        "universe": universe,
        "active_top_n": active_top_n,
        "holding": holding,
        "retain_fraction": retain_fraction,
        "raw_ic": raw_a,
        "partial_ic_controlling_pricevol": par_a,
        "baseline_pricevol_ic": base_a,
        "feature_vs_baseline_corr": fb_a,
        "partial_to_raw_ratio": ratio,
        "decision": decision,
    }


# ----------------------------------------------------------------------------
# D4 (first cut): linear multi-feature composite. Combine the 5 informed-flow
# features (cross-section z-score, sign-aligned equal-weight or IC-weight) and ask
# whether the composite cross-section IC beats the breadth-adjusted requirement
# (Grinold IR=1, daily 250 periods: required_ic = 1/sqrt(eff_breadth*250)). GBDT is
# deferred until a linear composite shows headroom — on 16 sections a tree overfits.
# Weights use the full-sample sign/IC (mild in-sample; flagged). research-only.
# ----------------------------------------------------------------------------


def _zscore(xs: list[float]) -> list[float]:
    n = len(xs)
    if n == 0:
        return []
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / n
    sd = var ** 0.5
    return [(x - m) / sd if sd > 0 else 0.0 for x in xs]


def evaluate_l6_daily_d4(
    panels: dict[str, dict[str, dict]],
    *,
    feature_names: tuple[str, ...] = DAILY_FEATURES,
    universe: str = "etf",
    active_top_n: int | None = None,
    holding: int = 1,
    weight_mode: str = "sign_equal",  # or "ic_weighted"
    top_fraction: float = 0.2,
    min_cross_section: int = 10,
    purged_cv: bool = False,
    embargo: int = 1,
) -> dict[str, object]:
    """D4 linear multi-feature composite cross-section IC vs the breadth-adjusted
    requirement. research-only. In-sample weights from full-sample per-feature IC;
    set ``purged_cv`` to also report leave-one-section-out OOS composite IC (weights
    trained on the other sections, embargoed) — the honest test of overfitting."""
    dates = sorted(panels)
    pair_data: list[tuple[list[str], dict[str, list[float]], list[float]]] = []
    fwd_panel: dict[str, list[float | None]] = {}
    pair_dates: list[str] = []
    for i in range(len(dates) - holding):
        t, t1 = dates[i], dates[i + holding]
        pt, pt1 = panels[t], panels[t1]
        syms = [s for s in pt if s in pt1]
        if universe == "etf":
            syms = [s for s in syms if is_etf_code(s)]
        if active_top_n:
            syms = sorted(
                syms,
                key=lambda s: pt[s].get("day_volume", 0.0) * pt[s].get("day_close", 0.0),
                reverse=True,
            )[:active_top_n]
        fwd = {}
        for s in syms:
            c0 = pt[s].get("day_close", 0.0)
            c1 = pt1[s].get("day_close", 0.0)
            if c0 > 0 and c1 > 0:
                fwd[s] = c1 / c0 - 1.0
        valid = [s for s in syms if s in fwd]
        if len(valid) < min_cross_section:
            continue
        pair_dates.append(f"{t}->{t1}")
        col = len(pair_dates) - 1
        for s in valid:
            lst = fwd_panel.setdefault(s, [])
            while len(lst) < col:
                lst.append(None)
            lst.append(fwd[s])
        feats = {f: [pt[s][f] for s in valid] for f in feature_names}
        pair_data.append((valid, feats, [fwd[s] for s in valid]))

    ncol = len(pair_dates)
    for lst in fwd_panel.values():
        while len(lst) < ncol:
            lst.append(None)
    breadth = _panel_effective_breadth(fwd_panel)

    # full-sample per-feature IC -> sign / weight
    feat_ic: dict[str, float] = {}
    for f in feature_names:
        ics = [spearman_rank_correlation(feats[f], ys) for (_v, feats, ys) in pair_data]
        ics = [v for v in ics if v is not None]
        feat_ic[f] = (sum(ics) / len(ics)) if ics else 0.0
    if weight_mode == "ic_weighted":
        weights = {f: feat_ic[f] for f in feature_names}
    else:
        weights = {f: (1.0 if feat_ic[f] >= 0 else -1.0) for f in feature_names}

    comp_ic: list[float] = []
    comp_ls: list[float] = []
    for (valid, feats, ys) in pair_data:
        z = {f: _zscore(feats[f]) for f in feature_names}
        comp = [sum(weights[f] * z[f][j] for f in feature_names) for j in range(len(valid))]
        ic = spearman_rank_correlation(comp, ys)
        if ic is not None:
            comp_ic.append(ic)
        ls = _decile_long_short(comp, ys, top_fraction)
        if ls is not None:
            comp_ls.append(ls)

    mean_ic = (sum(comp_ic) / len(comp_ic)) if comp_ic else None
    sign_stab = None
    if comp_ic:
        sgn = 1 if mean_ic >= 0 else -1
        sign_stab = sum(1 for v in comp_ic if (v >= 0) == (sgn >= 0)) / len(comp_ic)
    eb = breadth["effective_breadth"]
    required_ic = 1.0 / ((eb * 250.0) ** 0.5) if eb > 0 else None

    cells = []
    if len(comp_ls) >= 2:
        cells.append({
            "feature": "composite", "family": "composite", "frequency": "1d",
            "portfolio_sharpe": _sharpe(comp_ls, "1d"),
            "portfolio_period_count": len(comp_ls),
            "period_returns_by_timestamp": {i: r for i, r in enumerate(comp_ls)},
        })
    dsr = compute_directional_deflated_sharpe(cells)
    pbo = compute_directional_pbo(cells)

    # purged leave-one-section-out: weights trained on other sections (embargoed),
    # evaluated OOS on the held-out section — the honest overfit test for ic_weighted.
    oos_ic: list[float] = []
    if purged_cv and len(pair_data) >= 3:
        for i in range(len(pair_data)):
            train = [pair_data[j] for j in range(len(pair_data)) if abs(j - i) > embargo]
            if not train:
                continue
            fic_tr: dict[str, float] = {}
            for f in feature_names:
                ics = [spearman_rank_correlation(ft[f], yy) for (_v, ft, yy) in train]
                ics = [v for v in ics if v is not None]
                fic_tr[f] = (sum(ics) / len(ics)) if ics else 0.0
            if weight_mode == "ic_weighted":
                w = fic_tr
            else:
                w = {f: (1.0 if fic_tr[f] >= 0 else -1.0) for f in feature_names}
            valid_i, feats_i, ys_i = pair_data[i]
            z_i = {f: _zscore(feats_i[f]) for f in feature_names}
            comp_i = [sum(w[f] * z_i[f][k] for f in feature_names) for k in range(len(valid_i))]
            ic = spearman_rank_correlation(comp_i, ys_i)
            if ic is not None:
                oos_ic.append(ic)
    oos_mean = (sum(oos_ic) / len(oos_ic)) if oos_ic else None
    oos_sign_stab = None
    if oos_ic:
        sg = 1 if oos_mean >= 0 else -1
        oos_sign_stab = sum(1 for v in oos_ic if (v >= 0) == (sg >= 0)) / len(oos_ic)
    oos_shrinkage = (oos_mean / mean_ic) if (oos_mean is not None and mean_ic) else None

    decision = "l6_d4_no_data"
    judge_ic = oos_mean if purged_cv else mean_ic
    judge_sign = oos_sign_stab if purged_cv else sign_stab
    if judge_ic is not None and required_ic is not None:
        breaks = abs(judge_ic) > required_ic and (judge_sign or 0) >= 0.6
        decision = "l6_d4_breaks_requirement" if breaks else "l6_d4_below_requirement"

    return {
        "version": L6_MICROSTRUCTURE_VERSION,
        "universe": universe,
        "active_top_n": active_top_n,
        "holding": holding,
        "weight_mode": weight_mode,
        "in_sample_weights_caveat": "in-sample weights from full-sample per-feature IC",
        "n_cross_sections": ncol,
        "effective_breadth": breadth,
        "required_ic_breadth_adjusted": required_ic,
        "per_feature_full_sample_ic": feat_ic,
        "composite_mean_ic": mean_ic,
        "composite_ic_t_stat": _t_stat(comp_ic) if comp_ic else None,
        "composite_ic_sign_stability": sign_stab,
        "composite_ls_decile_sharpe": _sharpe(comp_ls, "1d") if len(comp_ls) >= 2 else None,
        "purged_cv": purged_cv,
        "embargo": embargo,
        "oos_composite_ic": oos_mean,
        "oos_composite_ic_t_stat": _t_stat(oos_ic) if oos_ic else None,
        "oos_composite_ic_sign_stability": oos_sign_stab,
        "oos_to_in_sample_ratio": oos_shrinkage,
        "deflated_sharpe": dsr,
        "pbo": pbo,
        "decision": decision,
    }


# ----------------------------------------------------------------------------
# L6 close_auction × ETF T+0 execution kill-test (line B). The cross-section IR
# bound (IC*sqrt(BR)) killed the broad bet (D1/D4); B asks the orthogonal
# execution question instead. The signal is observed at T's close auction, so a
# slow operator can act no earlier than T+1 OPEN -> the only realizable T+0 trade
# is enter T+1 open / exit T+1 close, capturing the INTRADAY leg; the overnight
# gap (T close -> T+1 open) is NOT capturable. Decompose the next-day reversal:
#     overnight    r_on = open[T+1]/close[T] - 1   (uncapturable T+0)
#     intraday     r_id = close[T+1]/open[T+1] - 1 (the T+0-realizable leg)
#     close2close  r_cc = close[T+1]/close[T] - 1  (what D1 measured)
# and ask whether the reversal lives in the capturable intraday leg, net of the
# ETF round-trip cost. Trade orientation is the close_auction reversal prior
# (short high close-auction buy pressure), fixed a priori from D1/D2 — not fit.
# research-only; no orders, no breadth bound (B deliberately bypasses it).
# ----------------------------------------------------------------------------

L6_T0_ROUND_TRIP_BPS = 6.0  # ETF T+0 round trip: ~2-3bp commission/leg, no stamp duty


def evaluate_l6_t0_execution(
    panels: dict[str, dict[str, dict]],
    *,
    feature: str = "close_auction_imbalance",
    universe: str = "etf",
    active_top_n: int | None = None,
    top_fraction: float = 0.2,
    round_trip_cost_bps: float = L6_T0_ROUND_TRIP_BPS,
    commission_roundtrip_bps: float = 2.5,
    min_cross_section: int = 10,
) -> dict[str, object]:
    """Overnight-vs-intraday decomposition of the close_auction reversal (line B).

    ``panels`` maps trading-day -> {symbol: D0 vector} where each vector carries
    ``day_open`` / ``day_close`` and ``feature``. No look-ahead: the T-day signal
    is acted on at T+1 open. research-only.
    """
    dates = sorted(panels)
    horizons = ("overnight", "intraday", "close_to_close")
    ic_by_h: dict[str, list[float]] = {h: [] for h in horizons}
    # harvest = reversal portfolio return/day = -(decile LS); prior is reversal.
    harvest_by_h: dict[str, list[float]] = {h: [] for h in horizons}
    # per-section (intraday harvest, empirical taker spread cost): cost is the sum
    # of the long-leg and short-leg traded ETFs' own T+1 quoted spreads (cross the
    # spread once each leg); None when any traded ETF lacks a quoted spread.
    id_sections: list[tuple[float, float | None]] = []
    pair_dates: list[str] = []

    for i in range(len(dates) - 1):
        t, t1 = dates[i], dates[i + 1]
        pt, pt1 = panels[t], panels[t1]
        syms = [s for s in pt if s in pt1]
        if universe == "etf":
            syms = [s for s in syms if is_etf_code(s)]
        if active_top_n:
            syms = sorted(
                syms,
                key=lambda s: pt[s].get("day_volume", 0.0) * pt[s].get("day_close", 0.0),
                reverse=True,
            )[:active_top_n]
        rows: list[tuple[float, float, float, float, float | None]] = []
        for s in syms:
            c0 = pt[s].get("day_close", 0.0)
            o1 = pt1[s].get("day_open", 0.0)
            c1 = pt1[s].get("day_close", 0.0)
            x = pt[s].get(feature)
            if c0 > 0 and o1 > 0 and c1 > 0 and x is not None:
                sp = pt1[s].get("quoted_spread_bps")  # trade on T+1 -> T+1 spread
                sp_rel = (sp / 1.0e4) if (sp is not None and sp > 0) else None
                rows.append((x, o1 / c0 - 1.0, c1 / o1 - 1.0, c1 / c0 - 1.0, sp_rel))
        if len(rows) < min_cross_section:
            continue
        pair_dates.append(f"{t}->{t1}")
        xs = [r[0] for r in rows]
        ys = {
            "overnight": [r[1] for r in rows],
            "intraday": [r[2] for r in rows],
            "close_to_close": [r[3] for r in rows],
        }
        for h in horizons:
            ic = spearman_rank_correlation(xs, ys[h])
            if ic is not None:
                ic_by_h[h].append(ic)
            ls = _decile_long_short(xs, ys[h], top_fraction)
            if ls is not None:
                harvest_by_h[h].append(-ls)  # reversal: short high-signal, long low-signal
        # empirical intraday taker cost from the traded tails' own T+1 spreads
        order = sorted(range(len(rows)), key=lambda j: rows[j][0])
        k = max(1, int(len(rows) * top_fraction))
        if 2 * k <= len(rows):
            bottom, top = order[:k], order[-k:]
            harvest_id = (
                sum(rows[j][2] for j in bottom) / k - sum(rows[j][2] for j in top) / k
            )  # long low-signal, short high-signal (reversal)
            sp = [rows[j][4] for j in (*bottom, *top)]
            if all(v is not None for v in sp):
                taker_cost = sum(rows[j][4] for j in bottom) / k + sum(rows[j][4] for j in top) / k
                id_sections.append((harvest_id, taker_cost))
            else:
                id_sections.append((harvest_id, None))

    def _agg(vals: list[float]) -> dict[str, object] | None:
        if not vals:
            return None
        m = sum(vals) / len(vals)
        sgn = 1 if m >= 0 else -1
        return {
            "mean": m,
            "t_stat": _t_stat(vals),
            "n_days": len(vals),
            "sign_stability": sum(1 for v in vals if (v >= 0) == (sgn >= 0)) / len(vals),
        }

    cost = round_trip_cost_bps / 1e4
    ic_summary = {h: _agg(ic_by_h[h]) for h in horizons}
    harvest_gross = {h: _agg(harvest_by_h[h]) for h in horizons}
    id_net = [v - cost for v in harvest_by_h["intraday"]]
    intraday_net = _agg(id_net)
    if intraday_net is not None:
        intraday_net["sharpe"] = _sharpe(id_net, "1d") if len(id_net) >= 2 else None
    intraday_gross_sharpe = (
        _sharpe(harvest_by_h["intraday"], "1d") if len(harvest_by_h["intraday"]) >= 2 else None
    )

    g_cc = harvest_gross["close_to_close"]["mean"] if harvest_gross["close_to_close"] else None
    g_id = harvest_gross["intraday"]["mean"] if harvest_gross["intraday"] else None
    capturable_fraction = (g_id / g_cc) if (g_cc not in (None, 0) and g_id is not None) else None

    # empirical cost: per traded ETF round trip, taker pays its own quoted spread on
    # both legs (continuous-session upper bound); auction-fill pays commission only.
    comm = 2.0 * (commission_roundtrip_bps / 1.0e4)  # long leg + short leg
    costed = [(h, c) for (h, c) in id_sections if c is not None]
    traded_tail_spread_bps = (
        sum(c for _h, c in costed) / len(costed) / 2.0 * 1.0e4 if costed else None
    )
    taker_net = _agg([h - c - comm for h, c in costed]) if costed else None
    auction_net = _agg([h - comm for h, _c in costed]) if costed else None
    for blk, series in ((taker_net, [h - c - comm for h, c in costed]),
                        (auction_net, [h - comm for h, _c in costed])):
        if blk is not None:
            blk["sharpe"] = _sharpe(series, "1d") if len(series) >= 2 else None

    id_sign_ok = ic_summary["intraday"] is not None and ic_summary["intraday"]["sign_stability"] >= 0.6
    mostly_overnight = capturable_fraction is not None and capturable_fraction < 0.34

    def _net_pos(blk: dict | None) -> bool:
        return blk is not None and blk["mean"] > 0 and (blk["t_stat"] or 0) >= 2.0

    decision = "l6_t0_no_data"
    if taker_net is not None:  # empirical-cost path (real ETF spreads available)
        if _net_pos(taker_net) and id_sign_ok:
            decision = "l6_t0_capturable_taker_net_positive"
        elif _net_pos(auction_net) and id_sign_ok:
            decision = "l6_t0_capturable_auction_fill_only"
        elif mostly_overnight:
            decision = "l6_t0_dead_reversal_is_overnight"
        else:
            decision = "l6_t0_intraday_below_empirical_cost"
    elif intraday_net is not None and ic_summary["intraday"] is not None:  # flat-cost fallback
        net_pos = intraday_net["mean"] > 0 and (intraday_net["t_stat"] or 0) >= 2.0
        if net_pos and id_sign_ok:
            decision = "l6_t0_capturable_net_positive"
        elif mostly_overnight:
            decision = "l6_t0_dead_reversal_is_overnight"
        else:
            decision = "l6_t0_intraday_below_cost"

    return {
        "version": L6_MICROSTRUCTURE_VERSION,
        "feature": feature,
        "universe": universe,
        "active_top_n": active_top_n,
        "top_fraction": top_fraction,
        "round_trip_cost_bps": round_trip_cost_bps,
        "commission_roundtrip_bps": commission_roundtrip_bps,
        "n_trading_days": len(dates),
        "n_cross_sections": len(pair_dates),
        "ic_by_horizon": ic_summary,
        "gross_harvest_by_horizon": harvest_gross,
        "intraday_gross_sharpe": intraday_gross_sharpe,
        "intraday_net_of_cost": intraday_net,
        "capturable_intraday_fraction": capturable_fraction,
        "n_empirical_cost_sections": len(costed),
        "traded_tail_spread_bps": traded_tail_spread_bps,
        "intraday_net_taker_empirical": taker_net,
        "intraday_net_auction_fill": auction_net,
        "decision": decision,
    }
