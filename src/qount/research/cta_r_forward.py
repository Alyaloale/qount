"""CTA-R research forward ledger (owner-authorized D1, 2026-09-30). research_only / no orders.

Freezes the rule already run by the CTA-R sidecar (``cta_r_paper._weights``: 63/126/252 sign mean,
63-day inverse vol, 0.35 cap, long-only, 21-bar rebalance from bar 253) and records every new
trading day after ``genesis_date`` into an append-only hash chain.

qfq closes are rewritten by the vendor after each distribution, so the ledger does not require
bit-for-bit replay. Each entry fixes, at recording time, the weights held, the per-asset returns,
any rebalance and the resulting equity. The next entry starts from the recorded state, so later
seed vintages cannot change past forward results. Replay drift against the current seed is
reported as a diagnostic only. The 21-bar cadence counts ledger bars (``bar_index``), not seed rows.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.research.cta_r_inputs import CTA_R_ETF_SYMBOLS
from qount.research.cta_r_paper import COST_PER_SIDE, LOOKBACKS, REBALANCE_DAYS, VOL_LOOKBACK, _read_series, _weights

SEED_SCHEMA = "cta_r_forward_seed_v1"
SOURCE = "tencent_public_qfq"
TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},day,{start},{end},2000,qfq"
FETCH_START = "2015-01-01"
CHUNK_DAYS = 700
MARKETS = {symbol: ("sz" if symbol.startswith("159") else "sh") for symbol in CTA_R_ETF_SYMBOLS}
FIRST_SIGNAL_INDEX = max(LOOKBACKS) + 1

CONTRACT = {
    "contract_id": "cta-r-research-forward",
    "version": "1.0.0",
    "rule": "cta_r_sign_mean_63_126_252_inverse_vol_63_cap_0.35_long_only",
    "lookbacks": list(LOOKBACKS),
    "vol_lookback": VOL_LOOKBACK,
    "weight_cap": 0.35,
    "rebalance_bars": REBALANCE_DAYS,
    "first_signal_bar": FIRST_SIGNAL_INDEX,
    "universe": list(CTA_R_ETF_SYMBOLS),
    "cost_per_side": COST_PER_SIDE,
    "stress_cost_per_side": 0.001,
    "execution": "decision_close_t0_weights_constant_between_rebalances",
    "source": SOURCE,
    "calendar_anchor_date": "2015-01-05",
    "genesis_date": "2026-09-29",
    "forward_start_date": "2026-09-30",
    "initial_equity": 10_000.0,
    "evaluation": "docs/cta-r-forward-ledger-2026-09.md",
    "research_only": True,
    "orders_authorized": False,
    "promotion_evidence": False,
}
CONTRACT_HASH = canonical_hash(CONTRACT)

Getter = Callable[[str], bytes]


class CtaRForwardError(ValueError):
    pass


# ---------------------------------------------------------------- seed

SHANGHAI = dt.timezone(dt.timedelta(hours=8))
SETTLED_HOUR = 17  # a day's bar is accepted only after 17:00 Shanghai time (close 15:00 + vendor lag)


def settled_cutoff(observed_at: dt.datetime) -> dt.date:
    local = observed_at.astimezone(SHANGHAI)
    return local.date() if local.hour >= SETTLED_HOUR else local.date() - dt.timedelta(days=1)


def fetch_tencent_series(getter: Getter, *, observed_at: dt.datetime) -> dict[str, dict[str, float]]:
    """Public Tencent qfq daily closes per ETF, fetched in bounded chunks; unsettled days dropped."""

    if observed_at.tzinfo is None:
        raise CtaRForwardError("observed_at_timezone_required")
    today = settled_cutoff(observed_at)
    out: dict[str, dict[str, float]] = {}
    for symbol in CTA_R_ETF_SYMBOLS:
        market = MARKETS[symbol]
        closes: dict[str, float] = {}
        cursor = dt.date.fromisoformat(FETCH_START)
        while cursor <= today:
            end = min(cursor + dt.timedelta(days=CHUNK_DAYS), today)
            url = TENCENT_URL.format(market=market, code=symbol, start=cursor.isoformat(), end=end.isoformat())
            node = (json.loads(getter(url).decode("utf-8")).get("data") or {}).get(market + symbol) or {}
            rows = node.get("qfqday")
            if rows is None and node.get("day"):
                raise CtaRForwardError(f"tencent_unadjusted_only:{symbol}")
            for row in rows or ():
                try:
                    close = float(row[2])
                except (IndexError, TypeError, ValueError):
                    continue
                day = str(row[0])[:10]
                if close > 0.0 and math.isfinite(close) and day <= today.isoformat():
                    closes[day] = close
            cursor = end + dt.timedelta(days=1)
        if not closes:
            raise CtaRForwardError(f"tencent_series_empty:{symbol}")
        out[symbol] = closes
    return out


def write_seed(path: Path, series: Mapping[str, Mapping[str, float]], *, fetched_at: dt.datetime) -> str:
    """Atomic 0600 seed zip in the member layout ``cta_r_paper`` reads; returns its SHA-256."""

    if set(series) != set(CTA_R_ETF_SYMBOLS):
        raise CtaRForwardError("seed_symbols_invalid")
    manifest = {"schema": SEED_SCHEMA, "source": SOURCE, "adjustment": "qfq", "symbols": list(CTA_R_ETF_SYMBOLS),
                "fetched_at": fetched_at.astimezone(dt.timezone.utc).isoformat(),
                "research_only": True, "orders_authorized": False}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(zipfile.ZipInfo("metadata/manifest.json", (1980, 1, 1, 0, 0, 0)),
                         json.dumps(manifest, sort_keys=True))
        for symbol in CTA_R_ETF_SYMBOLS:
            text = io.StringIO(newline="")
            writer = csv.writer(text)
            writer.writerow(("trade_date", "close"))
            for day, close in sorted(series[symbol].items()):
                writer.writerow((day.replace("-", ""), format(close, ".12g")))
            archive.writestr(zipfile.ZipInfo(f"etf_data/daily/{symbol}.csv", (1980, 1, 1, 0, 0, 0)), text.getvalue())
    raw = buffer.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------- panel

@dataclass(frozen=True)
class Panel:
    dates: tuple[str, ...]
    prices: dict[str, list[float]]
    returns: dict[str, list[float]]
    sha256: str


def load_panel(seed_path: Path) -> Panel:
    raw = seed_path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        series = {symbol: _read_series(archive, symbol) for symbol in CTA_R_ETF_SYMBOLS}
    if any(not values for values in series.values()):
        raise CtaRForwardError("seed_series_missing")
    dates = tuple(sorted(set.intersection(*(set(values) for values in series.values()))))
    if not dates or dates[0] != CONTRACT["calendar_anchor_date"]:
        raise CtaRForwardError("seed_calendar_anchor_mismatch")
    prices = {s: [series[s][d] for d in dates] for s in CTA_R_ETF_SYMBOLS}
    returns = {s: [0.0] + [p[i] / p[i - 1] - 1.0 for i in range(1, len(p))] for s, p in prices.items()}
    return Panel(dates, prices, returns, hashlib.sha256(raw).hexdigest())


def _rounded(weights: Mapping[str, float]) -> dict[str, float]:
    return {k: round(v, 10) for k, v in sorted(weights.items()) if v > 0.0}


def _seal(core: Mapping[str, Any]) -> dict[str, Any]:
    return dict(core) | {"record_hash": canonical_hash(dict(core))}


def genesis(panel: Panel) -> dict[str, Any]:
    """State after the genesis close: the weights the frozen replay holds there, equity = initial."""

    if CONTRACT["genesis_date"] not in panel.dates:
        raise CtaRForwardError("genesis_date_missing_from_seed")
    g = panel.dates.index(CONTRACT["genesis_date"])
    weights: dict[str, float] = {}
    for index in range(FIRST_SIGNAL_INDEX, g + 1):
        if index % REBALANCE_DAYS == 0:
            weights = _weights(panel.prices, panel.returns, index)
    initial = CONTRACT["initial_equity"]
    return _seal({"kind": "genesis", "date": panel.dates[g], "bar_index": g, "panel_index": g,
                  "weights_after_close": _rounded(weights), "equity": initial, "stress_equity": initial,
                  "contract_hash": CONTRACT_HASH, "seed_sha256": panel.sha256, "previous_hash": None})


# ---------------------------------------------------------------- ledger

def read_ledger(path: Path) -> list[dict[str, Any]]:
    """Append-only chain; any break or foreign contract is an error, never skipped."""

    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    previous = None
    for line in path.read_text().splitlines():
        entry = json.loads(line)
        core = {k: v for k, v in entry.items() if k != "record_hash"}
        if (entry.get("previous_hash") != previous or canonical_hash(core) != entry.get("record_hash")
                or entry.get("contract_hash") != CONTRACT_HASH):
            raise CtaRForwardError("forward_ledger_chain_invalid")
        if entries and entry["date"] <= entries[-1]["date"]:
            raise CtaRForwardError("forward_ledger_dates_not_increasing")
        entries.append(entry)
        previous = entry["record_hash"]
    if entries and entries[0].get("kind") != "genesis":
        raise CtaRForwardError("forward_ledger_genesis_missing")
    return entries


def advance(panel: Panel, ledger: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """New entries for every seed date after the ledger head, continuing from the recorded state."""

    reasons: list[str] = []
    entries: list[dict[str, Any]] = [] if ledger else [genesis(panel)]
    head = dict(ledger[-1]) if ledger else entries[0]
    if head["date"] not in panel.dates:
        return entries, ["forward_head_missing_from_seed"]
    rate, stress = CONTRACT["cost_per_side"], CONTRACT["stress_cost_per_side"]
    for p in range(panel.dates.index(head["date"]) + 1, len(panel.dates)):
        held = dict(head["weights_after_close"])
        asset = {s: round(panel.returns[s][p], 12) for s in held}
        gross = sum(w * asset[s] for s, w in held.items())
        equity = head["equity"] * (1.0 + gross)
        stress_equity = head["stress_equity"] * (1.0 + gross)
        bar = head["bar_index"] + 1
        turnover = 0.0
        after = held
        if bar >= FIRST_SIGNAL_INDEX and bar % REBALANCE_DAYS == 0:
            after = _rounded(_weights(panel.prices, panel.returns, p))
            turnover = sum(abs(after.get(s, 0.0) - held.get(s, 0.0)) for s in set(after) | set(held))
            equity -= equity * rate * turnover
            stress_equity -= stress_equity * stress * turnover
        if p != bar and "panel_index_drift" not in reasons:
            reasons.append("panel_index_drift")  # diagnostic: seed rows changed; cadence follows the ledger
        head = _seal({"kind": "bar", "date": panel.dates[p], "bar_index": bar, "panel_index": p,
                      "weights_held": held, "asset_returns": asset, "gross_return": round(gross, 12),
                      "rebalanced": turnover > 0.0 or (bar >= FIRST_SIGNAL_INDEX and bar % REBALANCE_DAYS == 0),
                      "turnover": round(turnover, 10), "weights_after_close": after,
                      "equity": round(equity, 8), "stress_equity": round(stress_equity, 8),
                      "contract_hash": CONTRACT_HASH, "seed_sha256": panel.sha256,
                      "previous_hash": head["record_hash"]})
        entries.append(head)
    return entries, reasons


def append_ledger(path: Path, entries: Sequence[Mapping[str, Any]]) -> int:
    if not entries:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write("".join(json.dumps(e, sort_keys=True) + "\n" for e in entries))
    os.chmod(path, 0o600)
    return len(entries)


def replay_drift(panel: Panel, ledger: Sequence[Mapping[str, Any]]) -> float | None:
    """Max |recorded - current-seed| daily gross return over recorded bars (diagnostic only)."""

    diffs = []
    for entry in ledger:
        if entry.get("kind") != "bar" or entry["date"] not in panel.dates:
            continue
        p = panel.dates.index(entry["date"])
        now = sum(w * panel.returns[s][p] for s, w in entry["weights_held"].items())
        diffs.append(abs(now - entry["gross_return"]))
    return round(max(diffs), 10) if diffs else None


def forward_summary(ledger: Sequence[Mapping[str, Any]], *, drift: float | None) -> dict[str, Any]:
    bars = [e for e in ledger if e.get("kind") == "bar"]
    initial = CONTRACT["initial_equity"]
    peak, worst = initial, 0.0
    for e in bars:
        peak = max(peak, e["equity"])
        worst = min(worst, e["equity"] / peak - 1.0)
    head = ledger[-1] if ledger else None
    return {
        "contract": CONTRACT, "contract_hash": CONTRACT_HASH,
        "genesis_date": CONTRACT["genesis_date"], "start_date": CONTRACT["forward_start_date"],
        "bars": len(bars), "last_date": head["date"] if head else None,
        "return": round(head["equity"] / initial - 1.0, 10) if head else None,
        "stress_return": round(head["stress_equity"] / initial - 1.0, 10) if head else None,
        "max_drawdown": round(worst, 10),
        "rebalances": sum(1 for e in bars if e["rebalanced"]),
        "current_weights": head["weights_after_close"] if head else {},
        "ledger_head_hash": head["record_hash"] if head else None,
        "replay_max_return_diff": drift,
        "points": [{"date": e["date"], "equity": e["equity"]} for e in ledger],
        "in_sample_through": CONTRACT["genesis_date"],
    }
