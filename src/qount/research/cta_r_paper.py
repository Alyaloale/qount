"""Research-only CTA-R paper replay and sidecar contract.

This module intentionally owns a small, deterministic replay instead of importing the
frozen ``legacy.line_a`` implementation.  It reads public ETF closes only, never emits
orders or strategy intents, and keeps stale input visible in the resulting artifact.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import zipfile
from pathlib import Path
from typing import Any

from qount.research.cta_r_inputs import CTA_R_ETF_SYMBOLS


SCHEMA = "cta_r_research_paper_v1"
LOOKBACKS = (63, 126, 252)
VOL_LOOKBACK = 63
REBALANCE_DAYS = 21
COST_PER_SIDE = 0.0002
MAX_AGE_DAYS = 7


class CtaRPaperError(ValueError):
    """Invalid or unusable CTA-R research input."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_series(archive: zipfile.ZipFile, symbol: str) -> dict[str, float]:
    names = set(archive.namelist())
    candidates = (
        f"etf_data/daily/{symbol}.csv",
        f"etf_data/daily/{symbol}.SH.csv",
        f"etf_data/daily/{symbol}.SZ.csv",
    )
    member = next((name for name in candidates if name in names), None)
    if member is None:
        return {}
    result: dict[str, float] = {}
    for row in csv.DictReader(io.TextIOWrapper(archive.open(member), encoding="utf-8")):
        raw_date = str(row.get("trade_date") or row.get("date") or "")[:10]
        if len(raw_date) == 8 and raw_date.isdigit():
            raw_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        try:
            value = float(row.get("close", ""))
        except (TypeError, ValueError):
            continue
        if len(raw_date) == 10 and value > 0 and math.isfinite(value):
            result[raw_date] = value
    return result


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _weights(prices: dict[str, list[float]], returns: dict[str, list[float]], index: int) -> dict[str, float]:
    raw: dict[str, float] = {}
    for symbol, series in prices.items():
        trailing = returns[symbol][max(1, index - VOL_LOOKBACK + 1): index + 1]
        volatility = _sample_std(trailing)
        if volatility <= 0:
            continue
        signs = [
            1.0 if series[index] > series[index - lookback] else (-1.0 if series[index] < series[index - lookback] else 0.0)
            for lookback in LOOKBACKS
            if index >= lookback
        ]
        signal = sum(signs) / len(signs) if signs else 0.0
        if signal > 0:  # long-only account; negative trend is held as cash
            raw[symbol] = signal / volatility
    gross = sum(raw.values())
    if gross <= 0:
        return {}
    unit = {symbol: value / gross for symbol, value in raw.items()}
    return {symbol: min(value, 0.35) for symbol, value in unit.items()}


def build_cta_r_paper_snapshot(
    seed_path: str | Path,
    *,
    observed_at: dt.datetime | None = None,
    initial_equity: float = 10_000.0,
    max_age_days: int = MAX_AGE_DAYS,
) -> dict[str, Any]:
    """Replay the eight-ETF CTA-R basket and return a canonical sidecar payload."""
    path = Path(seed_path).expanduser()
    if not path.is_file() or path.is_symlink():
        raise CtaRPaperError("cta_r_seed_missing")
    observed = observed_at or dt.datetime.now(dt.timezone.utc)
    if observed.tzinfo is None:
        raise CtaRPaperError("cta_r_observed_at_timezone_required")
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise CtaRPaperError("cta_r_seed_zip_invalid") from exc
    with archive:
        series_by_symbol = {symbol: _read_series(archive, symbol) for symbol in CTA_R_ETF_SYMBOLS}
    missing = [symbol for symbol, series in series_by_symbol.items() if not series]
    common_dates = sorted(set.intersection(*(set(series) for series in series_by_symbol.values()))) if not missing else []
    if not common_dates:
        raise CtaRPaperError("cta_r_seed_no_common_dates")
    prices = {symbol: [series_by_symbol[symbol][date] for date in common_dates] for symbol in CTA_R_ETF_SYMBOLS}
    returns = {symbol: [0.0] + [prices[symbol][i] / prices[symbol][i - 1] - 1.0 for i in range(1, len(common_dates))] for symbol in CTA_R_ETF_SYMBOLS}
    latest_date = dt.date.fromisoformat(common_dates[-1])
    age_days = (observed.astimezone(dt.timezone.utc).date() - latest_date).days
    status = "valid" if not missing and age_days <= max_age_days else "insufficient"
    reason_codes = ([f"series_missing:{symbol}" for symbol in missing] + (["series_stale"] if age_days > max_age_days else []))

    equity = float(initial_equity)
    peak = equity
    weights: dict[str, float] = {}
    total_cost = 0.0
    points: list[dict[str, Any]] = [{"date": common_dates[0], "equity": round(equity, 6), "drawdown": 0.0}]
    rebalances: list[dict[str, Any]] = []
    start = max(LOOKBACKS) + 1
    for index in range(1, len(common_dates)):
        equity *= 1.0 + sum(weights.get(symbol, 0.0) * returns[symbol][index] for symbol in CTA_R_ETF_SYMBOLS)
        if index >= start and index % REBALANCE_DAYS == 0:
            new_weights = _weights(prices, returns, index)
            turnover = sum(abs(new_weights.get(symbol, 0.0) - weights.get(symbol, 0.0)) for symbol in CTA_R_ETF_SYMBOLS)
            cost = equity * COST_PER_SIDE * turnover
            equity -= cost
            total_cost += cost
            weights = new_weights
            rebalances.append({"date": common_dates[index], "turnover": round(turnover, 8), "cost": round(cost, 6), "weights": {k: round(v, 8) for k, v in sorted(weights.items())}})
        peak = max(peak, equity)
        points.append({"date": common_dates[index], "equity": round(equity, 6), "drawdown": round(equity / peak - 1.0, 8)})
    peak_equity = max((point["equity"] for point in points), default=equity)
    max_drawdown = min((point["equity"] / max(maximum["equity"] for maximum in points[:i + 1]) - 1.0 for i, point in enumerate(points)), default=0.0)
    # Keep the browser artifact bounded while retaining the complete deterministic summary.
    sampled = points if len(points) <= 160 else [points[min(len(points) - 1, int(i * (len(points) - 1) / 159))] for i in range(160)]
    return {
        "schema": SCHEMA,
        "strategy_id": "cta-r",
        "strategy_label": "CTA-R 跨资产趋势研究模拟",
        "status": status,
        "reason_codes": reason_codes,
        "research_only": True,
        "orders_authorized": False,
        "pnl_evaluated": False,
        "source": "akshare",
        "source_sha256": _sha256(path),
        "data_cutoff": f"{latest_date.isoformat()}T00:00:00Z",
        "observed_at": observed.astimezone(dt.timezone.utc).isoformat(),
        "freshness": {"age_calendar_days": age_days, "max_age_calendar_days": max_age_days},
        "universe": list(CTA_R_ETF_SYMBOLS),
        "parameters": {"lookbacks": list(LOOKBACKS), "vol_lookback": VOL_LOOKBACK, "rebalance_days": REBALANCE_DAYS, "cost_per_side": COST_PER_SIDE, "long_only": True},
        "initial_equity": initial_equity,
        "final_equity": round(equity, 6),
        "total_return": round(equity / initial_equity - 1.0, 8),
        "max_drawdown": round(max_drawdown, 8),
        "cumulative_cost": round(total_cost, 6),
        "rebalance_count": len(rebalances),
        "current_weights": {symbol: round(weight, 8) for symbol, weight in sorted(weights.items())},
        "points": sampled,
        "rebalances": rebalances[-24:],
    }


def write_cta_r_paper_snapshot(
    snapshot: dict[str, Any], output_path: str | Path, *, mode: int = 0o600
) -> Path:
    """Write the sidecar as canonical JSON with restrictive local permissions."""
    if snapshot.get("schema") != SCHEMA or snapshot.get("orders_authorized") is not False:
        raise CtaRPaperError("cta_r_snapshot_guard_invalid")
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    if mode not in {0o600, 0o640, 0o644}:
        raise CtaRPaperError("cta_r_snapshot_mode_invalid")
    path.write_bytes(raw)
    path.chmod(mode)
    return path


__all__ = ["CtaRPaperError", "SCHEMA", "build_cta_r_paper_snapshot", "write_cta_r_paper_snapshot"]
